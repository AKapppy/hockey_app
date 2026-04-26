from __future__ import annotations

import csv
import datetime as dt
import io
import math
import xml.etree.ElementTree as ET
from collections import defaultdict
from typing import Any

from hockey_app.config import SEASON, TEAM_NAMES, canon_team_code
from hockey_app.data.cache import DiskCache
from hockey_app.data.paths import cache_dir, nhl_dir


def series_key(a: str, b: str) -> tuple[str, str]:
    aa = str(a or "").upper().strip()
    bb = str(b or "").upper().strip()
    return (aa, bb) if aa <= bb else (bb, aa)


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        try:
            return int(float(value))
        except Exception:
            return int(default)


def _is_final_state_text(state: Any) -> bool:
    u = str(state or "").upper().strip()
    return u in {"FINAL", "OFF"} or u.startswith("FINAL")


def _parse_moneypuck_season_text(season_text: str) -> tuple[int, int] | None:
    txt = str(season_text or "").strip()
    if len(txt) == 9 and txt[4] == "-" and txt[:4].isdigit() and txt[5:].isdigit():
        return int(txt[:4]), int(txt[5:])
    if len(txt) == 7 and txt[4] == "-" and txt[:4].isdigit() and txt[5:].isdigit():
        y0 = int(txt[:4])
        y1 = (y0 // 100) * 100 + int(txt[5:])
        if y1 < y0:
            y1 += 100
        return y0, y1
    return None


def _moneypuck_season_candidates_for_game(
    *,
    season_text: str,
    selected_date: dt.date,
    game_id: int,
) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()

    def _add(y0: int, y1: int) -> None:
        key = f"{int(y0):04d}{int(y1):04d}"
        if key not in seen:
            seen.add(key)
            out.append(key)

    parsed = _parse_moneypuck_season_text(season_text)
    if parsed is not None:
        _add(parsed[0], parsed[1])

    gid_txt = str(int(game_id)) if int(game_id) > 0 else ""
    if len(gid_txt) >= 4 and gid_txt[:4].isdigit():
        y0 = int(gid_txt[:4])
        _add(y0, y0 + 1)

    y0_date = selected_date.year if selected_date.month >= 7 else (selected_date.year - 1)
    _add(y0_date, y0_date + 1)
    _add(y0_date - 1, y0_date)
    _add(y0_date + 1, y0_date + 2)
    return out


def _parse_latest_game_data_win_probs(csv_text: str) -> tuple[float, float] | None:
    if not csv_text:
        return None
    try:
        reader = csv.DictReader(io.StringIO(csv_text))
    except Exception:
        return None

    def _to_prob(raw: Any) -> float | None:
        s = str(raw or "").strip()
        if not s:
            return None
        try:
            v = float(s)
        except Exception:
            return None
        if v < 0.0:
            return None
        if v > 1.0:
            if v <= 100.0:
                v /= 100.0
            else:
                return None
        return max(0.0, min(1.0, v))

    latest_pair: tuple[float, float] | None = None
    for row in reader:
        if not isinstance(row, dict):
            continue
        away_prob = _to_prob(row.get("liveAwayTeamWinOverallScore"))
        home_prob = _to_prob(row.get("liveHomeTeamWinOverallScore"))
        if away_prob is None or home_prob is None:
            home_alt = _to_prob(row.get("homeWinProbability"))
            if home_alt is not None:
                home_prob = home_alt
                away_alt = _to_prob(row.get("awayWinProbability"))
                away_prob = away_alt if away_alt is not None else max(0.0, min(1.0, 1.0 - home_alt))
        if away_prob is None or home_prob is None:
            continue
        total = float(away_prob) + float(home_prob)
        if total <= 0.0:
            continue
        if 0.90 <= total <= 1.10:
            latest_pair = (float(away_prob), float(home_prob))
        else:
            latest_pair = (
                max(0.0, min(1.0, float(away_prob) / total)),
                max(0.0, min(1.0, float(home_prob) / total)),
            )
    return latest_pair


def _cached_live_game_probabilities(
    game_id: int,
    selected_date: dt.date,
    *,
    season_text: str,
) -> tuple[float, float] | None:
    if int(game_id) <= 0:
        return None
    cache = DiskCache(nhl_dir(SEASON))
    for season_compact in _moneypuck_season_candidates_for_game(
        season_text=season_text,
        selected_date=selected_date,
        game_id=game_id,
    ):
        key = f"moneypuck/gamedata/{season_compact}/{int(game_id)}.csv"
        try:
            blob = cache.get_bytes(key, ttl_s=None)
        except Exception:
            blob = None
        if not blob:
            continue
        try:
            txt = blob.decode("utf-8", errors="ignore")
        except Exception:
            continue
        pair = _parse_latest_game_data_win_probs(txt)
        if pair is not None:
            return pair
    return None


def _game_rows_through(day: dt.date) -> list[dict[str, Any]]:
    path = cache_dir() / "online" / "xml" / str(SEASON) / "games.xml"
    if not path.exists():
        return []
    try:
        root = ET.parse(path).getroot()
    except Exception:
        return []

    out: list[dict[str, Any]] = []
    for day_node in root.findall("day"):
        raw_day = str(day_node.get("date") or "").strip()
        try:
            game_day = dt.date.fromisoformat(raw_day[:10])
        except Exception:
            continue
        if game_day > day:
            continue
        for game in day_node.findall("game"):
            away_code = canon_team_code(str(game.get("away_code") or "").upper())
            home_code = canon_team_code(str(game.get("home_code") or "").upper())
            if not away_code or not home_code:
                continue
            out.append(
                {
                    "date": game_day,
                    "id": _to_int(game.get("id") or 0, default=0),
                    "league": str(game.get("league") or "").upper().strip(),
                    "state": str(game.get("state") or "").upper().strip(),
                    "status_text": str(game.get("status_text") or "").upper().strip(),
                    "start_utc": str(game.get("start_utc") or "").strip(),
                    "game_type": str(
                        game.get("game_type")
                        or game.get("game_type_id")
                        or game.get("game_type_code")
                        or ""
                    ).upper().strip(),
                    "away_code": away_code,
                    "home_code": home_code,
                    "away_score": _to_int(game.get("away_score") or 0, default=0),
                    "home_score": _to_int(game.get("home_score") or 0, default=0),
                }
            )
    out.sort(
        key=lambda row: (
            row.get("date") or dt.date.min,
            str(row.get("start_utc") or ""),
            _to_int(row.get("id") or 0, default=0),
        )
    )
    return out


def live_playoff_series_probabilities(
    day: dt.date,
    *,
    season_text: str = SEASON,
    league: str = "NHL",
) -> dict[tuple[str, str], dict[str, Any]]:
    if str(league or "NHL").upper() != "NHL":
        return {}
    rows = _game_rows_through(day)
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        if row.get("date") != day:
            continue
        if str(row.get("league") or "").upper() != "NHL":
            continue
        if _is_final_state_text(row.get("state")):
            continue
        game_type = str(row.get("game_type") or "").upper()
        gid = str(row.get("id") or "")
        if game_type not in {"3", "P"} and not gid.startswith("202503"):
            continue
        away = str(row.get("away_code") or "").upper()
        home = str(row.get("home_code") or "").upper()
        if not away or not home:
            continue
        pair = _cached_live_game_probabilities(
            _to_int(row.get("id") or 0, default=0),
            day,
            season_text=season_text,
        )
        if pair is None:
            continue
        out[series_key(away, home)] = {
            "id": _to_int(row.get("id") or 0, default=0),
            "away": away,
            "home": home,
            "away_prob": float(pair[0]),
            "home_prob": float(pair[1]),
        }
    return out


def team_strength_snapshot(day: dt.date, *, league: str = "NHL") -> dict[str, float]:
    if str(league or "NHL").upper() != "NHL":
        return {}
    rows = _game_rows_through(day)
    if not rows:
        return {}

    point_results: dict[str, list[float]] = defaultdict(list)
    win_results: dict[str, list[float]] = defaultdict(list)
    seen_games: set[int] = set()
    for row in rows:
        if str(row.get("league") or "").upper() != "NHL":
            continue
        gid = _to_int(row.get("id") or 0, default=0)
        if gid > 0 and gid in seen_games:
            continue
        if not _is_final_state_text(row.get("state")):
            continue
        away = str(row.get("away_code") or "").upper()
        home = str(row.get("home_code") or "").upper()
        if away not in TEAM_NAMES or home not in TEAM_NAMES:
            continue
        away_score = _to_int(row.get("away_score") or 0, default=0)
        home_score = _to_int(row.get("home_score") or 0, default=0)
        if away_score == home_score:
            continue
        status = str(row.get("status_text") or "").upper()
        ot_or_so = ("OT" in status) or ("SO" in status)
        game_type = str(row.get("game_type") or "").upper()
        is_regular = game_type in {"2", "R"} or str(gid).startswith("202502")

        away_win = away_score > home_score
        home_win = home_score > away_score
        away_point = 1.0 if away_win else (0.5 if is_regular and ot_or_so else 0.0)
        home_point = 1.0 if home_win else (0.5 if is_regular and ot_or_so else 0.0)
        point_results[away].append(float(away_point))
        point_results[home].append(float(home_point))
        win_results[away].append(1.0 if away_win else 0.0)
        win_results[home].append(1.0 if home_win else 0.0)
        if gid > 0:
            seen_games.add(gid)

    out: dict[str, float] = {}
    for code in sorted(set(point_results) | set(win_results)):
        pvals = [float(v) for v in point_results.get(code, [])]
        wvals = [float(v) for v in win_results.get(code, [])]
        if not pvals or not wvals:
            continue
        overall_blend = (sum(pvals) / len(pvals) + sum(wvals) / len(wvals)) / 2.0
        recent_n = min(10, len(pvals), len(wvals))
        recent_weights = [float(i + 1) for i in range(recent_n)]
        recent_points = pvals[-recent_n:]
        recent_wins = wvals[-recent_n:]
        weight_total = sum(recent_weights) or 1.0
        recent_point_blend = sum(v * w for v, w in zip(recent_points, recent_weights)) / weight_total
        recent_win_blend = sum(v * w for v, w in zip(recent_wins, recent_weights)) / weight_total
        recent_blend = (recent_point_blend + recent_win_blend) / 2.0
        out[code] = max(0.0, min(1.0, (0.72 * overall_blend) + (0.28 * recent_blend)))
    return out


def matchup_game_win_prob(a: str, b: str, team_strength: dict[str, float] | None) -> float:
    ra = float((team_strength or {}).get(a, 0.5))
    rb = float((team_strength or {}).get(b, 0.5))
    diff = ra - rb
    p = 1.0 / (1.0 + math.exp(-(diff / 0.12)))
    return max(0.08, min(0.92, float(p)))


def best_of_7_lengths_from_score(
    p: float,
    wins_for: int,
    wins_against: int,
) -> tuple[float, float, float, float]:
    p = max(0.001, min(0.999, float(p)))
    q = 1.0 - p
    wf = max(0, int(wins_for))
    wa = max(0, int(wins_against))
    played = wf + wa

    if wf >= 4:
        return tuple(1.0 if total == played else 0.0 for total in range(4, 8))  # type: ignore[return-value]
    if wa >= 4:
        return (0.0, 0.0, 0.0, 0.0)

    out: list[float] = []
    wins_needed = 4 - wf
    for total_games in range(4, 8):
        remaining_games = total_games - played
        if remaining_games < wins_needed or remaining_games <= 0:
            out.append(0.0)
            continue
        opp_future_wins = remaining_games - wins_needed
        if (wa + opp_future_wins) >= 4:
            out.append(0.0)
            continue
        before_final = remaining_games - 1
        needed_before_final = wins_needed - 1
        if before_final < needed_before_final or needed_before_final < 0:
            out.append(0.0)
            continue
        out.append(float(math.comb(before_final, needed_before_final)) * (p**wins_needed) * (q**opp_future_wins))
    return tuple(out)  # type: ignore[return-value]


def series_probability_table(
    a: str,
    b: str,
    *,
    team_strength: dict[str, float] | None,
    series_scores: dict[tuple[str, str], dict[str, int]] | None = None,
    live_series_probs: dict[tuple[str, str], dict[str, Any]] | None = None,
) -> dict[str, object]:
    wins = (series_scores or {}).get(series_key(a, b), {})
    a_wins = int(wins.get(a, 0))
    b_wins = int(wins.get(b, 0))
    p = matchup_game_win_prob(a, b, team_strength)

    live = (live_series_probs or {}).get(series_key(a, b), {})
    live_a_prob: float | None = None
    if isinstance(live, dict):
        away = str(live.get("away") or "").upper()
        home = str(live.get("home") or "").upper()
        if away == a:
            live_a_prob = float(live.get("away_prob") or 0.0)
        elif home == a:
            live_a_prob = float(live.get("home_prob") or 0.0)
        if live_a_prob is not None:
            live_a_prob = max(0.0, min(1.0, live_a_prob))

    if live_a_prob is not None and a_wins < 4 and b_wins < 4:
        a_if_win = best_of_7_lengths_from_score(p, a_wins + 1, b_wins)
        a_if_lose = best_of_7_lengths_from_score(p, a_wins, b_wins + 1)
        b_after_a_win = best_of_7_lengths_from_score(1.0 - p, b_wins, a_wins + 1)
        b_after_b_win = best_of_7_lengths_from_score(1.0 - p, b_wins + 1, a_wins)
        a_probs = tuple((live_a_prob * x) + ((1.0 - live_a_prob) * y) for x, y in zip(a_if_win, a_if_lose))
        b_probs = tuple((live_a_prob * x) + ((1.0 - live_a_prob) * y) for x, y in zip(b_after_a_win, b_after_b_win))
    else:
        a_probs = best_of_7_lengths_from_score(p, a_wins, b_wins)
        b_probs = best_of_7_lengths_from_score(1.0 - p, b_wins, a_wins)

    a_win = float(sum(a_probs))
    b_win = float(sum(b_probs))
    outcomes = [
        (a, 4, float(a_probs[0])),
        (a, 5, float(a_probs[1])),
        (a, 6, float(a_probs[2])),
        (a, 7, float(a_probs[3])),
        (b, 4, float(b_probs[0])),
        (b, 5, float(b_probs[1])),
        (b, 6, float(b_probs[2])),
        (b, 7, float(b_probs[3])),
    ]
    pred_team, pred_len, pred_p = max(outcomes, key=lambda item: item[2])
    winner = a if a_win >= b_win else b
    return {
        "a": a,
        "b": b,
        "a_probs": a_probs,
        "b_probs": b_probs,
        "a_win": a_win,
        "b_win": b_win,
        "pred": f"{pred_team} in {pred_len}",
        "winner": winner,
        "pred_p": float(pred_p),
        "a_wins": a_wins,
        "b_wins": b_wins,
        "game_prob": p,
        "live_a_prob": live_a_prob,
    }


def pick_series_winner(
    a: str,
    b: str,
    *,
    team_strength: dict[str, float] | None,
    series_scores: dict[tuple[str, str], dict[str, int]] | None = None,
    live_series_probs: dict[tuple[str, str], dict[str, Any]] | None = None,
) -> str:
    if not a and not b:
        return ""
    if a and not b:
        return a
    if b and not a:
        return b
    table = series_probability_table(
        a,
        b,
        team_strength=team_strength,
        series_scores=series_scores,
        live_series_probs=live_series_probs,
    )
    return str(table.get("winner") or "")
