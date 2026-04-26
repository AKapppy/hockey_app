from __future__ import annotations

import datetime as dt
import unittest

from hockey_app.ui.tabs.models_playoff_math import series_probability_table
from hockey_app.ui.tabs.models_playoff_picture import _bracket_snapshot, _pick_bracket_winner, playoff_status_map
from hockey_app.ui.tabs.points import _is_nhl_regular_season_game
from hockey_app.ui.tabs.models_playoff_win_probabilities import _best_of_7_lengths_from_score


class PlayoffBracketSnapshotTests(unittest.TestCase):
    def test_regular_season_filter_excludes_playoff_games(self) -> None:
        self.assertTrue(_is_nhl_regular_season_game({"gameType": 2, "id": 2025020001}))
        self.assertFalse(_is_nhl_regular_season_game({"gameType": 3, "id": 2025030111}))
        self.assertFalse(_is_nhl_regular_season_game({"id": 2025030111}))

    def test_stronger_division_winner_gets_lower_wildcard(self) -> None:
        pts = {
            "BUF": 108.0,
            "TBL": 100.0,
            "MTL": 96.0,
            "BOS": 97.0,
            "CAR": 112.0,
            "PIT": 101.0,
            "PHI": 99.0,
            "OTT": 95.0,
            "VGK": 105.0,
            "EDM": 101.0,
            "ANA": 98.0,
            "UTA": 99.0,
            "COL": 118.0,
            "DAL": 104.0,
            "MIN": 97.0,
            "LAK": 96.0,
        }
        standings = {
            "BUF": {"divisionSequence": 1, "conferenceSequence": 2},
            "TBL": {"divisionSequence": 2, "conferenceSequence": 4},
            "MTL": {"divisionSequence": 3, "conferenceSequence": 6},
            "BOS": {"conferenceSequence": 5},
            "CAR": {"divisionSequence": 1, "conferenceSequence": 1},
            "PIT": {"divisionSequence": 2, "conferenceSequence": 3},
            "PHI": {"divisionSequence": 3, "conferenceSequence": 4},
            "OTT": {"conferenceSequence": 8},
            "VGK": {"divisionSequence": 1, "conferenceSequence": 2},
            "EDM": {"divisionSequence": 2, "conferenceSequence": 4},
            "ANA": {"divisionSequence": 3, "conferenceSequence": 6},
            "UTA": {"conferenceSequence": 5},
            "COL": {"divisionSequence": 1, "conferenceSequence": 1},
            "DAL": {"divisionSequence": 2, "conferenceSequence": 3},
            "MIN": {"divisionSequence": 3, "conferenceSequence": 7},
            "LAK": {"conferenceSequence": 8},
        }

        bracket = _bracket_snapshot(pts, standings)

        self.assertEqual(bracket["East_R1"], ["BUF", "BOS", "TBL", "MTL", "CAR", "OTT", "PIT", "PHI"])
        self.assertEqual(bracket["West_R1"], ["VGK", "UTA", "EDM", "ANA", "COL", "LAK", "DAL", "MIN"])

    def test_points_fallback_still_assigns_lower_wildcard_to_better_winner(self) -> None:
        pts = {
            "VGK": 105.0,
            "EDM": 101.0,
            "ANA": 98.0,
            "UTA": 99.0,
            "COL": 118.0,
            "DAL": 104.0,
            "MIN": 97.0,
            "LAK": 96.0,
        }

        bracket = _bracket_snapshot(pts, standings=None)

        self.assertEqual(bracket["West_R1"], ["VGK", "MIN", "EDM", "ANA", "COL", "LAK", "DAL", "UTA"])

    def test_finished_series_overrides_points_projection(self) -> None:
        pts = {"BOS": 110.0, "OTT": 95.0}
        series_scores = {("BOS", "OTT"): {"BOS": 2, "OTT": 4}}

        winner = _pick_bracket_winner("BOS", "OTT", pts, series_scores)

        self.assertEqual(winner, "OTT")

    def test_in_progress_series_still_projects_next_round_matchup(self) -> None:
        pts = {"BOS": 110.0, "OTT": 95.0}
        series_scores = {("BOS", "OTT"): {"BOS": 2, "OTT": 1}}

        winner = _pick_bracket_winner("BOS", "OTT", pts, series_scores)

        self.assertEqual(winner, "BOS")

    def test_playoff_status_map_marks_finished_series_loser_eliminated(self) -> None:
        statuses = playoff_status_map(
            dt.date(2026, 4, 25),
            {"BOS": 110.0, "OTT": 95.0},
            {},
            league="NHL",
            series_scores={("BOS", "OTT"): {"BOS": 4, "OTT": 2}},
        )

        self.assertEqual(statuses.get("OTT"), "eliminated")


class PlayoffSeriesProbabilityTests(unittest.TestCase):
    def test_series_probability_table_uses_live_game_branch_when_available(self) -> None:
        team_strength = {"BOS": 0.58, "OTT": 0.55}
        table = series_probability_table(
            "BOS",
            "OTT",
            team_strength=team_strength,
            series_scores={("BOS", "OTT"): {"BOS": 2, "OTT": 1}},
            live_series_probs={("BOS", "OTT"): {"away": "BOS", "home": "OTT", "away_prob": 0.2, "home_prob": 0.8}},
        )

        self.assertAlmostEqual(float(table["live_a_prob"]), 0.2)
        self.assertGreater(float(table["a_win"]) + float(table["b_win"]), 0.99)
        self.assertLessEqual(float(table["a_win"]) + float(table["b_win"]), 1.01)

    def test_series_lengths_zero_out_impossible_results_after_games_are_played(self) -> None:
        ana = _best_of_7_lengths_from_score(0.5, 2, 1)
        edm = _best_of_7_lengths_from_score(0.5, 1, 2)

        self.assertEqual(ana[0], 0.0)
        self.assertEqual(edm[0], 0.0)
        self.assertEqual(edm[1], 0.0)
        self.assertAlmostEqual(sum(ana), 0.6875)
        self.assertAlmostEqual(sum(edm), 0.3125)
        self.assertGreater(ana[1], 0.0)
        self.assertGreater(ana[2], 0.0)
        self.assertGreater(ana[3], 0.0)
        self.assertGreater(edm[2], 0.0)
        self.assertGreater(edm[3], 0.0)

    def test_finished_series_collapses_to_actual_length(self) -> None:
        probs = _best_of_7_lengths_from_score(0.6, 4, 1)
        self.assertEqual(probs, (0.0, 1.0, 0.0, 0.0))


if __name__ == "__main__":
    unittest.main()
