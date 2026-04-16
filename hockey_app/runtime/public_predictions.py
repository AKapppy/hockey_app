from __future__ import annotations

import datetime as dt
import math
import random
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from hockey_app.data.cache import CacheStore
from hockey_app.data.paths import cache_dir
from hockey_app.domain.teams import TEAM_NAMES, TEAM_TO_CONF, TEAM_TO_DIV, canon_team_code


METRIC_TABLE_KEYS: tuple[str, ...] = (
    "madeplayoffs",
    "round2",
    "round3",
    "round4",
    "woncup",
)
PUBLIC_MODEL_SIMS = 1200
PUBLIC_MODEL_SIMS_BACKFILL = 120
PUBLIC_MODEL_SIMS_BACKFILL_MIN = 20
PUBLIC_MODEL_BACKFILL_WORK_BUDGET = 9000
PUBLIC_STRENGTH_SHRINK = 0.72
PUBLIC_LOGIT_SCALE = 0.95
PUBLIC_MODEL_CACHE_VERSION = 4


@dataclass
class TeamState:
    code: str
    conference: str
    division: str
    points: int = 0
    rw: int = 0
    row: int = 0
    wins: int = 0
    goals_for: int = 0
    goals_against: int = 0
    goal_diff: int = 0
    games_played: int = 0
    strength: float = 0.0

    def clone(self) -> "TeamState":
        return TeamState(**self.__dict__)


@dataclass
class RemainingGame:
    game_id: int
    game_date: dt.date
    home: str
    away: str
    days_out: int


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(float(v))
    except Exception:
        return default


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _is_final_state(state: str) -> bool:
    u = str(state or "").upper().strip()
    return u in {"FINAL", "OFF"} or u.startswith("FINAL")


def _is_ot_or_so(status_text: str) -> bool:
    u = str(status_text or "").upper()
    return "OT" in u or "SO" in u


def _games_xml_path(season: str) -> Path:
    return cache_dir() / "online" / "xml" / str(season) / "games.xml"


def _cache_store_for_season(season: str) -> CacheStore:
    return CacheStore(cache_dir() / "online" / "public_model" / str(season))


def _snapshot_cache_key(season: str, day: dt.date) -> str:
    return f"v{int(PUBLIC_MODEL_CACHE_VERSION)}/snapshot/{str(season).strip()}/{day.isoformat()}"


def _season_start_from_label(season: str, fallback: dt.date) -> dt.date:
    parts = [p for p in str(season).split("-") if p.strip()]
    if len(parts) != 2 or not parts[0].isdigit():
        return fallback
    try:
        return dt.date(int(parts[0]), 10, 1)
    except Exception:
        return fallback


def _iter_days(start: dt.date, end: dt.date) -> list[dt.date]:
    if end < start:
        return []
    out: list[dt.date] = []
    cur = start
    while cur <= end:
        out.append(cur)
        cur += dt.timedelta(days=1)
    return out


def _historical_sim_count(max_sims: int, remaining_games: int) -> int:
    cap = max(int(PUBLIC_MODEL_SIMS_BACKFILL_MIN), int(max_sims))
    if remaining_games <= 0:
        return cap
    by_work = int(PUBLIC_MODEL_BACKFILL_WORK_BUDGET // max(1, int(remaining_games)))
    return max(int(PUBLIC_MODEL_SIMS_BACKFILL_MIN), min(cap, max(1, by_work)))


def _empty_tables_for_days(days: list[dt.date]) -> dict[str, pd.DataFrame]:
    if not days:
        days = [dt.date.today()]
    cols = [f"{d.month}/{d.day}" for d in days]
    codes = sorted(TEAM_NAMES.keys())
    out: dict[str, pd.DataFrame] = {}
    for key in METRIC_TABLE_KEYS:
        out[key] = pd.DataFrame(
            [[0.0 for _ in cols] for _ in codes],
            index=codes,
            columns=cols,
            dtype="float64",
        )
    return out


def _empty_tables(day: dt.date) -> dict[str, pd.DataFrame]:
    return _empty_tables_for_days([day])


def _load_games_from_xml(season: str) -> list[dict[str, Any]]:
    path = _games_xml_path(season)
    if not path.exists():
        return []
    try:
        tree = ET.parse(path)
    except Exception:
        return []
    root = tree.getroot()
    out: list[dict[str, Any]] = []
    for day_node in root.findall("day"):
        day_raw = str(day_node.get("date") or "").strip()
        try:
            day = dt.date.fromisoformat(day_raw[:10])
        except Exception:
            continue
        for g in day_node.findall("game"):
            league_u = str(g.get("league") or "NHL").upper().strip()
            if league_u and league_u != "NHL":
                continue
            away = canon_team_code(str(g.get("away_code") or "").upper().strip())
            home = canon_team_code(str(g.get("home_code") or "").upper().strip())
            if away not in TEAM_NAMES or home not in TEAM_NAMES:
                continue
            row = {
                "id": _safe_int(g.get("id"), default=0),
                "date": day,
                "state": str(g.get("state") or "").upper().strip(),
                "status_text": str(g.get("status_text") or "").strip(),
                "away": away,
                "home": home,
                "away_score": _safe_int(g.get("away_score"), default=0),
                "home_score": _safe_int(g.get("home_score"), default=0),
            }
            out.append(row)
    return out


def _dedupe_games(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key: dict[Any, dict[str, Any]] = {}
    for g in rows:
        gid = _safe_int(g.get("id"), default=0)
        if gid > 0:
            key: Any = ("id", gid)
        else:
            key = ("composite", g.get("date"), g.get("away"), g.get("home"))
        prev = by_key.get(key)
        if prev is None:
            by_key[key] = g
            continue
        prev_final = _is_final_state(str(prev.get("state") or ""))
        cur_final = _is_final_state(str(g.get("state") or ""))
        if cur_final and not prev_final:
            by_key[key] = g
            continue
        if cur_final == prev_final and str(g.get("status_text") or ""):
            by_key[key] = g
    return list(by_key.values())


def _blank_team_states() -> dict[str, TeamState]:
    out: dict[str, TeamState] = {}
    for code in sorted(TEAM_NAMES.keys()):
        out[code] = TeamState(
            code=code,
            conference=str(TEAM_TO_CONF.get(code, "East")),
            division=str(TEAM_TO_DIV.get(code, "Metro")),
        )
    return out


def _update_h2h(
    h2h_points: dict[tuple[str, str], int],
    h2h_games: dict[tuple[str, str], int],
    home: str,
    away: str,
    home_points: int,
    away_points: int,
) -> None:
    h2h_points[(home, away)] = int(h2h_points.get((home, away), 0)) + int(home_points)
    h2h_points[(away, home)] = int(h2h_points.get((away, home), 0)) + int(away_points)
    h2h_games[(home, away)] = int(h2h_games.get((home, away), 0)) + 1
    h2h_games[(away, home)] = int(h2h_games.get((away, home), 0)) + 1


def _apply_final_result(
    teams: dict[str, TeamState],
    h2h_points: dict[tuple[str, str], int],
    h2h_games: dict[tuple[str, str], int],
    *,
    home: str,
    away: str,
    home_score: int,
    away_score: int,
    ot_or_so: bool,
) -> None:
    if home not in teams or away not in teams:
        return
    th = teams[home]
    ta = teams[away]

    hs = int(home_score)
    as_ = int(away_score)
    th.goals_for += hs
    th.goals_against += as_
    th.goal_diff = th.goals_for - th.goals_against
    th.games_played += 1

    ta.goals_for += as_
    ta.goals_against += hs
    ta.goal_diff = ta.goals_for - ta.goals_against
    ta.games_played += 1

    if hs == as_:
        return

    if hs > as_:
        winner = th
        loser = ta
        home_points, away_points = (2, 1) if ot_or_so else (2, 0)
        if ot_or_so:
            winner.row += 1
        else:
            winner.rw += 1
            winner.row += 1
    else:
        winner = ta
        loser = th
        home_points, away_points = (1, 2) if ot_or_so else (0, 2)
        if ot_or_so:
            winner.row += 1
        else:
            winner.rw += 1
            winner.row += 1

    winner.wins += 1
    winner.points += 2
    loser.points += 1 if ot_or_so else 0

    _update_h2h(
        h2h_points,
        h2h_games,
        home,
        away,
        home_points=home_points,
        away_points=away_points,
    )


def _zscore_by_team(values: dict[str, float]) -> dict[str, float]:
    if not values:
        return {}
    vals = [float(v) for v in values.values()]
    mean = sum(vals) / float(len(vals))
    var = sum((v - mean) ** 2 for v in vals) / float(len(vals))
    std = math.sqrt(var)
    if std <= 1e-9:
        return {k: 0.0 for k in values}
    return {k: (float(v) - mean) / std for k, v in values.items()}


def _estimate_team_strengths(teams: dict[str, TeamState]) -> None:
    ppct: dict[str, float] = {}
    gdpg: dict[str, float] = {}
    goalie: dict[str, float] = {}

    ga_values: list[float] = []
    for t in teams.values():
        gp = max(1, int(t.games_played))
        ga_values.append(float(t.goals_against) / float(gp))
    league_ga_avg = (sum(ga_values) / float(len(ga_values))) if ga_values else 3.0

    for code, t in teams.items():
        gp = max(1, int(t.games_played))
        ppct[code] = float(t.points) / float(2 * gp)
        gdpg[code] = float(t.goal_diff) / float(gp)
        ga_pg = float(t.goals_against) / float(gp)
        goalie[code] = league_ga_avg - ga_pg

    ppct_z = _zscore_by_team(ppct)
    gdpg_z = _zscore_by_team(gdpg)
    goalie_z = _zscore_by_team(goalie)
    for code, t in teams.items():
        t.strength = float(PUBLIC_STRENGTH_SHRINK) * (
            0.17 * float(ppct_z.get(code, 0.0))
            + 0.54 * float(gdpg_z.get(code, 0.0))
            + 0.29 * float(goalie_z.get(code, 0.0))
        )


def _regular_game_probs(game: RemainingGame, teams: dict[str, TeamState]) -> tuple[float, float]:
    home = teams[game.home]
    away = teams[game.away]
    edge = float(home.strength) - float(away.strength)
    if game.days_out > 0:
        edge *= 0.5 ** (float(game.days_out) / 30.0)
    logit = float(PUBLIC_LOGIT_SCALE) * edge + math.log(0.54 / 0.46)
    p_home = _clamp(_sigmoid(logit), 0.01, 0.99)
    closeness = math.exp(-3.0 * abs(edge))
    p_ot = _clamp(0.23 + 0.04 * closeness, 0.18, 0.28)
    return p_home, p_ot


def _playoff_game_home_win_prob(home: str, away: str, teams: dict[str, TeamState]) -> float:
    edge = float(teams[home].strength) - float(teams[away].strength)
    logit = float(PUBLIC_LOGIT_SCALE) * edge + math.log(0.54 / 0.46)
    return _clamp(_sigmoid(logit), 0.01, 0.99)


def _sample_regular_outcome(rng: random.Random, p_home_win: float, p_ot: float) -> str:
    p_home_reg = p_home_win * (1.0 - p_ot)
    p_home_ot = p_home_win * p_ot
    p_away_ot = (1.0 - p_home_win) * p_ot
    r = rng.random()
    if r < p_home_reg:
        return "HOME_REG"
    if r < p_home_reg + p_home_ot:
        return "HOME_OT"
    if r < p_home_reg + p_home_ot + p_away_ot:
        return "AWAY_OT"
    return "AWAY_REG"


def _apply_simulated_regular_outcome(
    teams: dict[str, TeamState],
    h2h_points: dict[tuple[str, str], int],
    h2h_games: dict[tuple[str, str], int],
    *,
    home: str,
    away: str,
    outcome: str,
) -> None:
    th = teams[home]
    ta = teams[away]
    th.games_played += 1
    ta.games_played += 1

    home_goals = 0
    away_goals = 0
    if outcome == "HOME_REG":
        th.points += 2
        th.rw += 1
        th.row += 1
        th.wins += 1
        home_goals = 4
        away_goals = 2
        _update_h2h(h2h_points, h2h_games, home, away, home_points=2, away_points=0)
    elif outcome == "HOME_OT":
        th.points += 2
        ta.points += 1
        th.row += 1
        th.wins += 1
        home_goals = 3
        away_goals = 2
        _update_h2h(h2h_points, h2h_games, home, away, home_points=2, away_points=1)
    elif outcome == "AWAY_OT":
        ta.points += 2
        th.points += 1
        ta.row += 1
        ta.wins += 1
        home_goals = 2
        away_goals = 3
        _update_h2h(h2h_points, h2h_games, home, away, home_points=1, away_points=2)
    else:
        ta.points += 2
        ta.rw += 1
        ta.row += 1
        ta.wins += 1
        home_goals = 2
        away_goals = 4
        _update_h2h(h2h_points, h2h_games, home, away, home_points=0, away_points=2)

    th.goals_for += int(home_goals)
    th.goals_against += int(away_goals)
    th.goal_diff = th.goals_for - th.goals_against
    ta.goals_for += int(away_goals)
    ta.goals_against += int(home_goals)
    ta.goal_diff = ta.goals_for - ta.goals_against


def _h2h_pct_within_group(
    team: str,
    group: list[str],
    h2h_points: dict[tuple[str, str], int],
    h2h_games: dict[tuple[str, str], int],
) -> float:
    earned = 0
    available = 0
    for opp in group:
        if opp == team:
            continue
        earned += int(h2h_points.get((team, opp), 0))
        available += 2 * int(h2h_games.get((team, opp), 0))
    return (float(earned) / float(available)) if available > 0 else 0.0


def _sorted_group(
    group: list[str],
    teams: dict[str, TeamState],
    h2h_points: dict[tuple[str, str], int],
    h2h_games: dict[tuple[str, str], int],
) -> list[str]:
    return sorted(
        group,
        key=lambda t: (
            int(teams[t].points),
            int(teams[t].rw),
            int(teams[t].row),
            int(teams[t].wins),
            _h2h_pct_within_group(t, group, h2h_points, h2h_games),
            int(teams[t].goal_diff),
            int(teams[t].goals_for),
        ),
        reverse=True,
    )


def _standings_order(
    team_names: list[str],
    teams: dict[str, TeamState],
    h2h_points: dict[tuple[str, str], int],
    h2h_games: dict[tuple[str, str], int],
) -> list[str]:
    by_points: dict[int, list[str]] = {}
    for t in team_names:
        by_points.setdefault(int(teams[t].points), []).append(t)
    ordered: list[str] = []
    for pts in sorted(by_points.keys(), reverse=True):
        ordered.extend(_sorted_group(by_points[pts], teams, h2h_points, h2h_games))
    return ordered


def _better_team_for_home_ice(
    a: str,
    b: str,
    teams: dict[str, TeamState],
    h2h_points: dict[tuple[str, str], int],
    h2h_games: dict[tuple[str, str], int],
) -> str:
    return _sorted_group([a, b], teams, h2h_points, h2h_games)[0]


def _build_conference_bracket(
    conference: str,
    teams: dict[str, TeamState],
    h2h_points: dict[tuple[str, str], int],
    h2h_games: dict[tuple[str, str], int],
) -> dict[str, list[tuple[str, str]]] | None:
    conf_teams = [t.code for t in teams.values() if t.conference == conference]
    if not conf_teams:
        return None
    divisions = sorted({teams[t].division for t in conf_teams})
    if len(divisions) != 2:
        return None

    div_top3: dict[str, list[str]] = {}
    division_winners: list[str] = []
    for div in divisions:
        div_teams = [t for t in conf_teams if teams[t].division == div]
        ordered = _standings_order(div_teams, teams, h2h_points, h2h_games)
        if len(ordered) < 3:
            return None
        div_top3[div] = ordered[:3]
        division_winners.append(ordered[0])

    locked = {t for div in divisions for t in div_top3[div]}
    wildcard_pool = [t for t in conf_teams if t not in locked]
    wildcards = _standings_order(wildcard_pool, teams, h2h_points, h2h_games)[:2]
    if len(wildcards) < 2:
        return None

    top_div_winners = _standings_order(division_winners, teams, h2h_points, h2h_games)
    best_div_winner = top_div_winners[0]
    wc1, wc2 = wildcards[0], wildcards[1]

    bracket: dict[str, list[tuple[str, str]]] = {}
    for div in divisions:
        seed1, seed2, seed3 = div_top3[div]
        wildcard = wc2 if seed1 == best_div_winner else wc1
        bracket[div] = [(seed1, wildcard), (seed2, seed3)]
    return bracket


def _simulate_series(
    team_a: str,
    team_b: str,
    teams: dict[str, TeamState],
    h2h_points: dict[tuple[str, str], int],
    h2h_games: dict[tuple[str, str], int],
    rng: random.Random,
) -> str:
    home_ice = _better_team_for_home_ice(team_a, team_b, teams, h2h_points, h2h_games)
    road = team_b if home_ice == team_a else team_a
    schedule = [home_ice, home_ice, road, road, home_ice, road, home_ice]
    wins = {team_a: 0, team_b: 0}
    for home in schedule:
        away = road if home == home_ice else home_ice
        p_home = _playoff_game_home_win_prob(home, away, teams)
        if rng.random() < p_home:
            wins[home] += 1
        else:
            wins[away] += 1
        if wins[team_a] == 4:
            return team_a
        if wins[team_b] == 4:
            return team_b
    return team_a if wins[team_a] >= wins[team_b] else team_b


def _simulate_playoffs(
    teams: dict[str, TeamState],
    h2h_points: dict[tuple[str, str], int],
    h2h_games: dict[tuple[str, str], int],
    rng: random.Random,
) -> dict[str, int]:
    # 0=no playoffs, 1=playoffs, 2=round2, 3=round3, 4=finals, 5=cup
    result = {code: 0 for code in teams}

    brackets: dict[str, dict[str, list[tuple[str, str]]]] = {}
    playoff_teams: set[str] = set()
    for conf in sorted({t.conference for t in teams.values()}):
        bracket = _build_conference_bracket(conf, teams, h2h_points, h2h_games)
        if not bracket:
            continue
        brackets[conf] = bracket
        for series_list in bracket.values():
            for a, b in series_list:
                playoff_teams.add(a)
                playoff_teams.add(b)
    for t in playoff_teams:
        result[t] = max(result[t], 1)

    conference_champs: dict[str, str] = {}
    for conf, bracket in brackets.items():
        division_winners: dict[str, str] = {}
        for div, round1 in bracket.items():
            winners: list[str] = []
            for a, b in round1:
                w = _simulate_series(a, b, teams, h2h_points, h2h_games, rng)
                result[w] = max(result[w], 2)
                winners.append(w)
            if len(winners) < 2:
                continue
            div_w = _simulate_series(winners[0], winners[1], teams, h2h_points, h2h_games, rng)
            result[div_w] = max(result[div_w], 3)
            division_winners[div] = div_w

        divs = list(division_winners.keys())
        if len(divs) < 2:
            continue
        conf_w = _simulate_series(
            division_winners[divs[0]],
            division_winners[divs[1]],
            teams,
            h2h_points,
            h2h_games,
            rng,
        )
        result[conf_w] = max(result[conf_w], 4)
        conference_champs[conf] = conf_w

    confs = list(conference_champs.keys())
    if len(confs) == 2:
        cup_w = _simulate_series(
            conference_champs[confs[0]],
            conference_champs[confs[1]],
            teams,
            h2h_points,
            h2h_games,
            rng,
        )
        result[cup_w] = max(result[cup_w], 5)

    return result


def _build_sim_inputs(
    season: str,
    today: dt.date,
) -> tuple[dict[str, TeamState], list[RemainingGame], dict[tuple[str, str], int], dict[tuple[str, str], int]]:
    teams = _blank_team_states()
    h2h_points: dict[tuple[str, str], int] = {}
    h2h_games: dict[tuple[str, str], int] = {}
    rows = _dedupe_games(_load_games_from_xml(season))
    remaining: list[RemainingGame] = []

    for g in rows:
        home = str(g.get("home") or "").upper()
        away = str(g.get("away") or "").upper()
        if home not in teams or away not in teams:
            continue
        day = g.get("date")
        if not isinstance(day, dt.date):
            continue
        state = str(g.get("state") or "").upper()
        status_text = str(g.get("status_text") or "")
        hs = _safe_int(g.get("home_score"), default=0)
        as_ = _safe_int(g.get("away_score"), default=0)

        if _is_final_state(state) and day <= today:
            _apply_final_result(
                teams,
                h2h_points,
                h2h_games,
                home=home,
                away=away,
                home_score=hs,
                away_score=as_,
                ot_or_so=_is_ot_or_so(status_text),
            )
            continue

        gid = _safe_int(g.get("id"), default=0)
        days_out = max(0, int((day - today).days))
        remaining.append(
            RemainingGame(
                game_id=gid,
                game_date=day,
                home=home,
                away=away,
                days_out=days_out,
            )
        )

    remaining.sort(key=lambda x: (x.game_date, x.game_id, x.home, x.away))
    return teams, remaining, h2h_points, h2h_games


def _playoff_math_overrides(
    teams: dict[str, TeamState],
    remaining_games: list[RemainingGame],
) -> dict[str, float]:
    rem_by_team: dict[str, int] = {code: 0 for code in teams}
    for gm in remaining_games:
        if gm.home in rem_by_team:
            rem_by_team[gm.home] += 1
        if gm.away in rem_by_team:
            rem_by_team[gm.away] += 1

    cur_pts = {code: int(ts.points) for code, ts in teams.items()}
    max_pts = {code: int(ts.points) + (2 * int(rem_by_team.get(code, 0))) for code, ts in teams.items()}
    conf_to_codes: dict[str, list[str]] = {}
    for code, ts in teams.items():
        conf_to_codes.setdefault(str(ts.conference), []).append(code)

    out: dict[str, float] = {}
    for conf_codes in conf_to_codes.values():
        for code in conf_codes:
            others = [x for x in conf_codes if x != code]
            if not others:
                continue

            # Guaranteed playoffs if at most 7 others can still reach this team's
            # current points total.
            can_reach_or_pass = sum(1 for opp in others if int(max_pts.get(opp, 0)) >= int(cur_pts.get(code, 0)))
            if can_reach_or_pass <= 7:
                out[code] = 1.0
                continue

            # Mathematically eliminated if at least 8 others are already above
            # this team's maximum possible points.
            already_above_max = sum(1 for opp in others if int(cur_pts.get(opp, 0)) > int(max_pts.get(code, 0)))
            if already_above_max >= 8:
                out[code] = 0.0
    return out


def _run_monte_carlo(
    teams_base: dict[str, TeamState],
    remaining_games: list[RemainingGame],
    h2h_points_base: dict[tuple[str, str], int],
    h2h_games_base: dict[tuple[str, str], int],
    *,
    n_sims: int = PUBLIC_MODEL_SIMS,
    seed: int = 17,
) -> dict[str, dict[str, float]]:
    n = max(20, int(n_sims))
    rng = random.Random(int(seed))
    codes = sorted(teams_base.keys())
    counts: dict[str, dict[str, int]] = {
        c: {"make_playoffs": 0, "round2": 0, "round3": 0, "finals": 0, "cup": 0}
        for c in codes
    }

    for _ in range(n):
        teams = {k: v.clone() for k, v in teams_base.items()}
        h2h_points = dict(h2h_points_base)
        h2h_games = dict(h2h_games_base)

        last_sim_day: dt.date | None = None
        for gm in remaining_games:
            if last_sim_day != gm.game_date:
                _estimate_team_strengths(teams)
                last_sim_day = gm.game_date
            p_home, p_ot = _regular_game_probs(gm, teams)
            outcome = _sample_regular_outcome(rng, p_home, p_ot)
            _apply_simulated_regular_outcome(
                teams,
                h2h_points,
                h2h_games,
                home=gm.home,
                away=gm.away,
                outcome=outcome,
            )

        _estimate_team_strengths(teams)
        reached = _simulate_playoffs(teams, h2h_points, h2h_games, rng)
        for code in codes:
            stage = int(reached.get(code, 0))
            if stage >= 1:
                counts[code]["make_playoffs"] += 1
            if stage >= 2:
                counts[code]["round2"] += 1
            if stage >= 3:
                counts[code]["round3"] += 1
            if stage >= 4:
                counts[code]["finals"] += 1
            if stage >= 5:
                counts[code]["cup"] += 1

    out: dict[str, dict[str, float]] = {}
    for code in codes:
        c = counts[code]
        out[code] = {
            "make_playoffs": _clamp(float(c["make_playoffs"]) / float(n), 0.0, 1.0),
            "round2": _clamp(float(c["round2"]) / float(n), 0.0, 1.0),
            "round3": _clamp(float(c["round3"]) / float(n), 0.0, 1.0),
            "finals": _clamp(float(c["finals"]) / float(n), 0.0, 1.0),
            "cup": _clamp(float(c["cup"]) / float(n), 0.0, 1.0),
        }

    # Apply strict playoff 0/100 bounds only when mathematically forced.
    overrides = _playoff_math_overrides(teams_base, remaining_games)
    for code, forced in overrides.items():
        if code not in out:
            continue
        out[code]["make_playoffs"] = float(forced)
        if forced <= 0.0:
            out[code]["round2"] = 0.0
            out[code]["round3"] = 0.0
            out[code]["finals"] = 0.0
            out[code]["cup"] = 0.0
    return out


def _tables_from_probs(day: dt.date, probs: dict[str, dict[str, float]]) -> dict[str, pd.DataFrame]:
    col = f"{day.month}/{day.day}"
    codes = sorted(TEAM_NAMES.keys())

    make_playoffs = [float(probs.get(c, {}).get("make_playoffs", 0.0)) for c in codes]
    round2 = [float(probs.get(c, {}).get("round2", 0.0)) for c in codes]
    round3 = [float(probs.get(c, {}).get("round3", 0.0)) for c in codes]
    finals = [float(probs.get(c, {}).get("finals", 0.0)) for c in codes]
    cup = [float(probs.get(c, {}).get("cup", 0.0)) for c in codes]

    return {
        "madeplayoffs": pd.DataFrame({col: make_playoffs}, index=codes, dtype="float64"),
        "round2": pd.DataFrame({col: round2}, index=codes, dtype="float64"),
        "round3": pd.DataFrame({col: round3}, index=codes, dtype="float64"),
        "round4": pd.DataFrame({col: finals}, index=codes, dtype="float64"),
        "woncup": pd.DataFrame({col: cup}, index=codes, dtype="float64"),
    }


def _tables_from_daily_probs(
    days: list[dt.date],
    probs_by_day: dict[dt.date, dict[str, dict[str, float]]],
) -> dict[str, pd.DataFrame]:
    if not days:
        return _empty_tables(dt.date.today())

    cols = [f"{d.month}/{d.day}" for d in days]
    codes = sorted(TEAM_NAMES.keys())
    metric_map: dict[str, str] = {
        "madeplayoffs": "make_playoffs",
        "round2": "round2",
        "round3": "round3",
        "round4": "finals",
        "woncup": "cup",
    }
    out: dict[str, pd.DataFrame] = {}
    for table_key, prob_key in metric_map.items():
        matrix: list[list[float]] = []
        for code in codes:
            row: list[float] = []
            for day in days:
                row.append(float(probs_by_day.get(day, {}).get(code, {}).get(prob_key, 0.0)))
            matrix.append(row)
        out[table_key] = pd.DataFrame(matrix, index=codes, columns=cols, dtype="float64")
    return out


def _payload_to_probs(payload: Any) -> dict[str, dict[str, float]] | None:
    if not isinstance(payload, dict):
        return None
    raw = payload.get("probs")
    if not isinstance(raw, dict):
        return None
    out: dict[str, dict[str, float]] = {}
    for code, row in raw.items():
        c = canon_team_code(str(code).upper().strip())
        if c not in TEAM_NAMES or not isinstance(row, dict):
            continue
        out[c] = {
            "make_playoffs": _clamp(float(row.get("make_playoffs", 0.0)), 0.0, 1.0),
            "round2": _clamp(float(row.get("round2", 0.0)), 0.0, 1.0),
            "round3": _clamp(float(row.get("round3", 0.0)), 0.0, 1.0),
            "finals": _clamp(float(row.get("finals", 0.0)), 0.0, 1.0),
            "cup": _clamp(float(row.get("cup", 0.0)), 0.0, 1.0),
        }
    return out


def _snapshot_probs_for_day(
    season: str,
    day: dt.date,
    *,
    live_day: dt.date,
    cache: CacheStore,
    n_sims: int,
) -> dict[str, dict[str, float]]:
    cache_key = _snapshot_cache_key(season, day)

    ttl_seconds: int | None = 60 * 30 if day == live_day else None
    cached = cache.get_json(cache_key, ttl_seconds=ttl_seconds)
    cached_probs = _payload_to_probs(cached)
    if cached_probs:
        return cached_probs

    teams, remaining, h2h_points, h2h_games = _build_sim_inputs(season, day)
    if not teams:
        return {}

    run_sims = max(20, int(n_sims))
    if day != live_day:
        run_sims = _historical_sim_count(run_sims, len(remaining))

    _estimate_team_strengths(teams)
    probs = _run_monte_carlo(
        teams,
        remaining,
        h2h_points,
        h2h_games,
        n_sims=run_sims,
        seed=17 + int(day.toordinal()),
    )
    if not probs:
        return {}

    try:
        cache.set_json(
            cache_key,
            {
                "season": str(season),
                "snapshot_date": day.isoformat(),
                "n_sims": int(run_sims),
                "probs": probs,
                "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
            },
        )
    except Exception:
        pass
    return probs


def build_public_probability_tables(
    season: str,
    *,
    today: dt.date | None = None,
    start_date: dt.date | None = None,
    end_date: dt.date | None = None,
) -> dict[str, pd.DataFrame]:
    live_day = today or dt.date.today()
    day_end = end_date or live_day
    day_start = start_date or _season_start_from_label(season, day_end)
    if day_end < day_start:
        day_start = day_end

    days = _iter_days(day_start, day_end)
    if not days:
        return _empty_tables(day_end)

    cache = _cache_store_for_season(season)
    probs_by_day: dict[dt.date, dict[str, dict[str, float]]] = {}

    for snap_day in days:
        use_sims = PUBLIC_MODEL_SIMS if snap_day == day_end else PUBLIC_MODEL_SIMS_BACKFILL
        probs = _snapshot_probs_for_day(
            season,
            snap_day,
            live_day=live_day,
            cache=cache,
            n_sims=use_sims,
        )
        if probs:
            probs_by_day[snap_day] = probs

    if not probs_by_day:
        return _empty_tables_for_days(days)
    return _tables_from_daily_probs(days, probs_by_day)
