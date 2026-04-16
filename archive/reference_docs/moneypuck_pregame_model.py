from __future__ import annotations

"""
MoneyPuck-style pregame win probability model.

This is a public approximation based on MoneyPuck's published methodology:
- Team strength = 17% ability to win + 54% scoring chances + 29% goaltending
- Individual game predictions also include home-ice and rest effects

Important:
This is NOT the exact hidden MoneyPuck production model. The site does not
publish the live coefficients that map strength differences to win probability,
so this script uses transparent, editable defaults that are easy to calibrate.
"""

from dataclasses import dataclass, asdict
import math
from typing import Optional, Dict


@dataclass
class TeamInputs:
    """
    Inputs for one team entering a game.

    Provide either:
    1) direct strength, or
    2) ability_to_win + scoring_chances + goaltending

    Suggested scale for components: roughly centered near 0.0, where positive
    values mean stronger than league average and negative values mean weaker.
    """

    team: str
    strength: Optional[float] = None
    ability_to_win: Optional[float] = None
    scoring_chances: Optional[float] = None
    goaltending: Optional[float] = None


@dataclass
class PregameModelConfig:
    """
    Tunable constants for the public approximation.

    strength_beta:
        Controls how aggressively a strength gap turns into win probability.
        Larger values make favorites more extreme.

    home_ice_logit:
        logit(0.54) ~= 0.160343, matching MoneyPuck's published note that home
        teams win about 54% of NHL games.

    rest_edge_logit:
        About 0.16 corresponds to roughly a 4 percentage-point swing near a
        50/50 baseline, matching MoneyPuck's published note about rest.

    future_half_life_days:
        Regresses matchup edges toward 0 farther into the future.

    ot_*:
        Heuristic overtime model. MoneyPuck publishes OT probabilities on game
        pages but does not publish the exact live formula, so this part is a
        practical approximation.
    """

    strength_beta: float = 1.25
    home_ice_logit: float = math.log(0.54 / 0.46)
    rest_edge_logit: float = 0.16
    future_half_life_days: float = 30.0

    w_ability: float = 0.17
    w_chances: float = 0.54
    w_goalie: float = 0.29

    ot_base: float = 0.23
    ot_bonus_max: float = 0.04
    ot_edge_decay: float = 3.0
    ot_min: float = 0.18
    ot_max: float = 0.28


@dataclass
class GamePrediction:
    home: str
    away: str
    home_strength: float
    away_strength: float
    strength_edge: float
    logit: float
    p_home_win: float
    p_away_win: float
    p_ot: float
    p_home_reg_win: float
    p_home_ot_win: float
    p_away_ot_win: float
    p_away_reg_win: float

    def as_dict(self) -> Dict[str, float | str]:
        return asdict(self)


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def compute_team_strength(team: TeamInputs, cfg: PregameModelConfig) -> float:
    if team.strength is not None:
        return float(team.strength)

    missing = [
        name
        for name, value in {
            "ability_to_win": team.ability_to_win,
            "scoring_chances": team.scoring_chances,
            "goaltending": team.goaltending,
        }.items()
        if value is None
    ]
    if missing:
        raise ValueError(
            f"{team.team} is missing {missing}. Provide either `strength` or all three components."
        )

    return (
        cfg.w_ability * float(team.ability_to_win)
        + cfg.w_chances * float(team.scoring_chances)
        + cfg.w_goalie * float(team.goaltending)
    )


def regress_edge(edge: float, days_out: int, cfg: PregameModelConfig) -> float:
    if days_out <= 0 or cfg.future_half_life_days <= 0:
        return edge
    factor = 0.5 ** (days_out / cfg.future_half_life_days)
    return edge * factor


def estimate_ot_probability(edge: float, cfg: PregameModelConfig) -> float:
    """
    Heuristic OT model:
    closer matchups are more likely to reach OT.

    When |edge| = 0, OT probability is at its maximum.
    As the matchup becomes more lopsided, OT probability decays toward ot_base.
    """
    closeness = math.exp(-cfg.ot_edge_decay * abs(edge))
    p_ot = cfg.ot_base + cfg.ot_bonus_max * closeness
    return clamp(p_ot, cfg.ot_min, cfg.ot_max)


def predict_game(
    home: TeamInputs,
    away: TeamInputs,
    *,
    cfg: Optional[PregameModelConfig] = None,
    days_out: int = 0,
    rest_edge: int = 0,
    p_ot_override: Optional[float] = None,
) -> GamePrediction:
    """
    Predict a game's win probability.

    Parameters
    ----------
    home, away:
        TeamInputs for each side.

    days_out:
        Number of days until the game. Used to regress edge toward 0 as the game
        gets farther away in time.

    rest_edge:
        +1 if home is more rested than away in a back-to-back style spot
        -1 if away is more rested than home
         0 if neutral / unknown

    p_ot_override:
        Use this if you already have an OT estimate from elsewhere.

    Returns
    -------
    GamePrediction
        Includes win probabilities and a 4-way regular-season outcome split.
    """
    cfg = cfg or PregameModelConfig()

    home_strength = compute_team_strength(home, cfg)
    away_strength = compute_team_strength(away, cfg)

    raw_edge = home_strength - away_strength
    edge = regress_edge(raw_edge, days_out, cfg)

    logit = (
        cfg.strength_beta * edge
        + cfg.home_ice_logit
        + cfg.rest_edge_logit * rest_edge
    )
    p_home_win = sigmoid(logit)
    p_away_win = 1.0 - p_home_win

    p_ot = estimate_ot_probability(edge, cfg) if p_ot_override is None else float(p_ot_override)
    p_ot = clamp(p_ot, 0.0, 1.0)

    # Split into regular-season outcomes.
    p_home_reg_win = p_home_win * (1.0 - p_ot)
    p_home_ot_win = p_home_win * p_ot
    p_away_ot_win = p_away_win * p_ot
    p_away_reg_win = p_away_win * (1.0 - p_ot)

    return GamePrediction(
        home=home.team,
        away=away.team,
        home_strength=home_strength,
        away_strength=away_strength,
        strength_edge=edge,
        logit=logit,
        p_home_win=p_home_win,
        p_away_win=p_away_win,
        p_ot=p_ot,
        p_home_reg_win=p_home_reg_win,
        p_home_ot_win=p_home_ot_win,
        p_away_ot_win=p_away_ot_win,
        p_away_reg_win=p_away_reg_win,
    )


def pretty_print_prediction(pred: GamePrediction) -> None:
    print(f"{pred.away} at {pred.home}")
    print(f"Strengths: {pred.home}={pred.home_strength:.4f}, {pred.away}={pred.away_strength:.4f}")
    print(f"Strength edge (home-away): {pred.strength_edge:+.4f}")
    print(f"Home win: {pred.p_home_win:.2%}")
    print(f"Away win: {pred.p_away_win:.2%}")
    print(f"OT probability: {pred.p_ot:.2%}")
    print("Outcome split:")
    print(f"  Home reg win: {pred.p_home_reg_win:.2%}")
    print(f"  Home OT win : {pred.p_home_ot_win:.2%}")
    print(f"  Away OT win : {pred.p_away_ot_win:.2%}")
    print(f"  Away reg win: {pred.p_away_reg_win:.2%}")


if __name__ == "__main__":
    # Example usage with component inputs.
    home = TeamInputs(
        team="NYR",
        ability_to_win=0.08,
        scoring_chances=0.05,
        goaltending=0.03,
    )
    away = TeamInputs(
        team="CAR",
        ability_to_win=0.10,
        scoring_chances=0.09,
        goaltending=0.01,
    )

    prediction = predict_game(home, away, days_out=0, rest_edge=0)
    pretty_print_prediction(prediction)
