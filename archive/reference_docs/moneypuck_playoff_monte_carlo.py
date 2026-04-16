from __future__ import annotations

"""MoneyPuck-style playoff Monte Carlo simulator.

This script simulates the rest of the NHL regular season, builds the playoff
bracket using NHL-style seeding, simulates each playoff round, and returns one
team's odds to make the playoffs, make round 2, make round 3, make the Finals,
and win the Stanley Cup.

Best accuracy comes when each remaining game already has a cached `p_home_win`
value. If not, the script can fall back to a simple team-strength model using
MoneyPuck-inspired component weights.
"""

from dataclasses import dataclass
import math
import random
from typing import Dict, List, Optional, Tuple


@dataclass
class TeamState:
    team: str
    conference: str
    division: str
    points: int
    rw: int
    row: int
    wins: int
    goal_diff: int = 0
    goals_for: int = 0
    ability_to_win: Optional[float] = None
    scoring_chances: Optional[float] = None
    goaltending: Optional[float] = None
    strength: Optional[float] = None

    def clone(self) -> "TeamState":
        return TeamState(**self.__dict__)


@dataclass
class Game:
    home: str
    away: str
    p_home_win: Optional[float] = None
    p_ot: float = 0.23
    days_out: int = 0
    rest_edge: int = 0  # +1 => home rested vs away B2B, -1 => opposite


@dataclass
class SimConfig:
    n_sims: int = 10000
    seed: int = 7

    # Used only if Game.p_home_win is missing:
    strength_beta: float = 1.25
    home_ice_logit: float = math.log(0.54 / 0.46)  # ~54% home-win baseline
    rest_edge_logit: float = 0.16                  # ~4 percentage points near 50/50
    future_half_life_days: float = 30.0            # regress matchup edge toward 0 over time

    # MoneyPuck-style team strength weights:
    w_ability: float = 0.17
    w_chances: float = 0.54
    w_goalie: float = 0.29


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def team_strength(team: TeamState, cfg: SimConfig) -> float:
    if team.strength is not None:
        return team.strength

    if None in (team.ability_to_win, team.scoring_chances, team.goaltending):
        raise ValueError(
            f"{team.team} needs either `strength` or all of "
            "`ability_to_win`, `scoring_chances`, and `goaltending`."
        )

    return (
        cfg.w_ability * float(team.ability_to_win)
        + cfg.w_chances * float(team.scoring_chances)
        + cfg.w_goalie * float(team.goaltending)
    )


def game_probabilities(
    game: Game,
    teams: Dict[str, TeamState],
    cfg: SimConfig,
    playoff: bool = False,
) -> Tuple[float, float]:
    # If you already have MoneyPuck-style game win probs cached, use them directly.
    if game.p_home_win is not None and not playoff:
        return game.p_home_win, game.p_ot

    home = teams[game.home]
    away = teams[game.away]

    edge = team_strength(home, cfg) - team_strength(away, cfg)

    # Regress farther-out games toward league average.
    if not playoff and cfg.future_half_life_days > 0:
        edge *= 0.5 ** (game.days_out / cfg.future_half_life_days)

    logit = cfg.strength_beta * edge + cfg.home_ice_logit
    if not playoff:
        logit += cfg.rest_edge_logit * game.rest_edge

    return sigmoid(logit), game.p_ot


def sample_regular_season_outcome(
    rng: random.Random,
    p_home_win: float,
    p_ot: float,
) -> str:
    # Split into 4 outcomes:
    # home reg win / home OT win / away OT win / away reg win
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


def update_head_to_head(
    h2h_points: Dict[Tuple[str, str], int],
    h2h_games: Dict[Tuple[str, str], int],
    home: str,
    away: str,
    home_points: int,
    away_points: int,
) -> None:
    h2h_points[(home, away)] = h2h_points.get((home, away), 0) + home_points
    h2h_points[(away, home)] = h2h_points.get((away, home), 0) + away_points
    h2h_games[(home, away)] = h2h_games.get((home, away), 0) + 1
    h2h_games[(away, home)] = h2h_games.get((away, home), 0) + 1


def simulate_regular_season(
    teams_in: Dict[str, TeamState],
    remaining_games: List[Game],
    h2h_points_in: Optional[Dict[Tuple[str, str], int]],
    h2h_games_in: Optional[Dict[Tuple[str, str], int]],
    cfg: SimConfig,
    rng: random.Random,
) -> Tuple[Dict[str, TeamState], Dict[Tuple[str, str], int], Dict[Tuple[str, str], int]]:
    teams = {k: v.clone() for k, v in teams_in.items()}
    h2h_points = dict(h2h_points_in or {})
    h2h_games = dict(h2h_games_in or {})

    for game in remaining_games:
        p_home_win, p_ot = game_probabilities(game, teams, cfg, playoff=False)
        outcome = sample_regular_season_outcome(rng, p_home_win, p_ot)

        home = teams[game.home]
        away = teams[game.away]

        if outcome == "HOME_REG":
            home.points += 2
            home.rw += 1
            home.row += 1
            home.wins += 1
            update_head_to_head(h2h_points, h2h_games, home.team, away.team, 2, 0)

        elif outcome == "HOME_OT":
            home.points += 2
            away.points += 1
            home.row += 1
            home.wins += 1
            update_head_to_head(h2h_points, h2h_games, home.team, away.team, 2, 1)

        elif outcome == "AWAY_OT":
            away.points += 2
            home.points += 1
            away.row += 1
            away.wins += 1
            update_head_to_head(h2h_points, h2h_games, home.team, away.team, 1, 2)

        else:  # AWAY_REG
            away.points += 2
            away.rw += 1
            away.row += 1
            away.wins += 1
            update_head_to_head(h2h_points, h2h_games, home.team, away.team, 0, 2)

    return teams, h2h_points, h2h_games


def h2h_pct_within_group(
    team: str,
    group: List[str],
    h2h_points: Dict[Tuple[str, str], int],
    h2h_games: Dict[Tuple[str, str], int],
) -> float:
    earned = 0
    available = 0
    for opp in group:
        if opp == team:
            continue
        earned += h2h_points.get((team, opp), 0)
        available += 2 * h2h_games.get((team, opp), 0)
    return earned / available if available else 0.0


def sorted_group(
    group: List[str],
    teams: Dict[str, TeamState],
    h2h_points: Dict[Tuple[str, str], int],
    h2h_games: Dict[Tuple[str, str], int],
) -> List[str]:
    return sorted(
        group,
        key=lambda t: (
            teams[t].points,
            teams[t].rw,
            teams[t].row,
            teams[t].wins,
            h2h_pct_within_group(t, group, h2h_points, h2h_games),
            teams[t].goal_diff,
            teams[t].goals_for,
        ),
        reverse=True,
    )


def standings_order(
    team_names: List[str],
    teams: Dict[str, TeamState],
    h2h_points: Dict[Tuple[str, str], int],
    h2h_games: Dict[Tuple[str, str], int],
) -> List[str]:
    by_points: Dict[int, List[str]] = {}
    for t in team_names:
        by_points.setdefault(teams[t].points, []).append(t)

    ordered: List[str] = []
    for pts in sorted(by_points.keys(), reverse=True):
        ordered.extend(sorted_group(by_points[pts], teams, h2h_points, h2h_games))
    return ordered


def better_team_for_home_ice(
    a: str,
    b: str,
    teams: Dict[str, TeamState],
    h2h_points: Dict[Tuple[str, str], int],
    h2h_games: Dict[Tuple[str, str], int],
) -> str:
    ordered = sorted_group([a, b], teams, h2h_points, h2h_games)
    return ordered[0]


def build_conference_bracket(
    conference: str,
    teams: Dict[str, TeamState],
    h2h_points: Dict[Tuple[str, str], int],
    h2h_games: Dict[Tuple[str, str], int],
) -> Optional[Dict[str, List[Tuple[str, str]]]]:
    conf_teams = [t.team for t in teams.values() if t.conference == conference]
    if not conf_teams:
        return None

    divisions = sorted({teams[t].division for t in conf_teams})
    if len(divisions) != 2:
        raise ValueError(f"{conference} needs exactly 2 divisions, found {divisions}")

    div_top3: Dict[str, List[str]] = {}
    division_winners: List[str] = []

    for div in divisions:
        div_teams = [t for t in conf_teams if teams[t].division == div]
        ordered = standings_order(div_teams, teams, h2h_points, h2h_games)
        div_top3[div] = ordered[:3]
        division_winners.append(ordered[0])

    locked = {t for div in divisions for t in div_top3[div]}
    wildcard_pool = [t for t in conf_teams if t not in locked]
    wildcards = standings_order(wildcard_pool, teams, h2h_points, h2h_games)[:2]

    if len(wildcards) < 2:
        raise ValueError(f"{conference} does not have 2 wildcard teams.")

    top_div_winners = standings_order(division_winners, teams, h2h_points, h2h_games)
    best_div_winner = top_div_winners[0]
    wc1, wc2 = wildcards[0], wildcards[1]  # wc1 is the better wildcard

    bracket: Dict[str, List[Tuple[str, str]]] = {}
    for div in divisions:
        seed1, seed2, seed3 = div_top3[div]
        wildcard = wc2 if seed1 == best_div_winner else wc1
        bracket[div] = [(seed1, wildcard), (seed2, seed3)]

    all_playoff_teams = {
        t for series_list in bracket.values() for series in series_list for t in series
    }
    if len(all_playoff_teams) != 8:
        raise ValueError(f"{conference} bracket has {len(all_playoff_teams)} teams instead of 8.")

    return bracket


def simulate_series(
    team_a: str,
    team_b: str,
    teams: Dict[str, TeamState],
    h2h_points: Dict[Tuple[str, str], int],
    h2h_games: Dict[Tuple[str, str], int],
    cfg: SimConfig,
    rng: random.Random,
) -> str:
    home_ice_team = better_team_for_home_ice(team_a, team_b, teams, h2h_points, h2h_games)
    road_team = team_b if home_ice_team == team_a else team_a

    # 2-2-1-1-1
    schedule = [
        home_ice_team, home_ice_team,
        road_team, road_team,
        home_ice_team,
        road_team,
        home_ice_team,
    ]

    wins = {team_a: 0, team_b: 0}

    for home in schedule:
        away = road_team if home == home_ice_team else home_ice_team
        p_home_win, _ = game_probabilities(Game(home=home, away=away, p_ot=0.23), teams, cfg, playoff=True)

        if rng.random() < p_home_win:
            wins[home] += 1
        else:
            wins[away] += 1

        if wins[team_a] == 4:
            return team_a
        if wins[team_b] == 4:
            return team_b

    raise RuntimeError("Series simulation reached an impossible state.")


def simulate_playoffs(
    teams: Dict[str, TeamState],
    h2h_points: Dict[Tuple[str, str], int],
    h2h_games: Dict[Tuple[str, str], int],
    cfg: SimConfig,
    rng: random.Random,
) -> Dict[str, int]:
    # 0=no playoffs, 1=playoffs, 2=round2, 3=round3, 4=finals, 5=cup
    result = {t: 0 for t in teams}

    brackets = {}
    playoff_teams = set()

    for conf in sorted({t.conference for t in teams.values()}):
        bracket = build_conference_bracket(conf, teams, h2h_points, h2h_games)
        if bracket is None:
            continue
        brackets[conf] = bracket
        for series_list in bracket.values():
            for a, b in series_list:
                playoff_teams.add(a)
                playoff_teams.add(b)

    for t in playoff_teams:
        result[t] = max(result[t], 1)

    conference_champs = {}

    for conf, bracket in brackets.items():
        division_winners = {}

        for div, round1_series in bracket.items():
            r1_winners = []
            for a, b in round1_series:
                winner = simulate_series(a, b, teams, h2h_points, h2h_games, cfg, rng)
                result[winner] = max(result[winner], 2)
                r1_winners.append(winner)

            div_winner = simulate_series(r1_winners[0], r1_winners[1], teams, h2h_points, h2h_games, cfg, rng)
            result[div_winner] = max(result[div_winner], 3)
            division_winners[div] = div_winner

        divs = list(division_winners.keys())
        conf_champ = simulate_series(
            division_winners[divs[0]],
            division_winners[divs[1]],
            teams,
            h2h_points,
            h2h_games,
            cfg,
            rng,
        )
        result[conf_champ] = max(result[conf_champ], 4)
        conference_champs[conf] = conf_champ

    confs = list(conference_champs.keys())
    if len(confs) != 2:
        raise ValueError(f"Need exactly 2 conferences for Stanley Cup Final, found {confs}")

    cup_winner = simulate_series(
        conference_champs[confs[0]],
        conference_champs[confs[1]],
        teams,
        h2h_points,
        h2h_games,
        cfg,
        rng,
    )
    result[cup_winner] = max(result[cup_winner], 5)

    return result


def simulate_team_odds(
    target_team: str,
    teams: Dict[str, TeamState],
    remaining_games: List[Game],
    cfg: Optional[SimConfig] = None,
    h2h_points: Optional[Dict[Tuple[str, str], int]] = None,
    h2h_games: Optional[Dict[Tuple[str, str], int]] = None,
) -> Dict[str, float]:
    """
    Returns one team's probabilities to:
    - make_playoffs
    - round2
    - round3
    - finals
    - cup
    """
    if target_team not in teams:
        raise KeyError(f"{target_team} is not in the `teams` dictionary.")

    cfg = cfg or SimConfig()
    rng = random.Random(cfg.seed)

    counts = {
        "make_playoffs": 0,
        "round2": 0,
        "round3": 0,
        "finals": 0,
        "cup": 0,
    }

    for _ in range(cfg.n_sims):
        sim_teams, sim_h2h_points, sim_h2h_games = simulate_regular_season(
            teams, remaining_games, h2h_points, h2h_games, cfg, rng
        )
        playoff_result = simulate_playoffs(sim_teams, sim_h2h_points, sim_h2h_games, cfg, rng)
        reached = playoff_result.get(target_team, 0)

        if reached >= 1:
            counts["make_playoffs"] += 1
        if reached >= 2:
            counts["round2"] += 1
        if reached >= 3:
            counts["round3"] += 1
        if reached >= 4:
            counts["finals"] += 1
        if reached >= 5:
            counts["cup"] += 1

    return {
        "team": target_team,
        "n_sims": cfg.n_sims,
        "make_playoffs": counts["make_playoffs"] / cfg.n_sims,
        "round2": counts["round2"] / cfg.n_sims,
        "round3": counts["round3"] / cfg.n_sims,
        "finals": counts["finals"] / cfg.n_sims,
        "cup": counts["cup"] / cfg.n_sims,
    }


if __name__ == "__main__":
    print(
        "This file defines TeamState, Game, SimConfig, and simulate_team_odds().\n"
        "Import it into your project and pass in your cached team/game data."
    )
