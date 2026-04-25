from __future__ import annotations

import unittest

from hockey_app.ui.tabs.team_stats import _team_stats_row_has_data


class TeamStatsRowFilterTests(unittest.TestCase):
    def test_hides_rows_without_games_played(self) -> None:
        self.assertFalse(_team_stats_row_has_data({"team": "CBJ", "gp": 0, "pts": 0}))
        self.assertFalse(_team_stats_row_has_data({"team": "CGY", "gp": "0"}))

    def test_keeps_rows_with_games_played(self) -> None:
        self.assertTrue(_team_stats_row_has_data({"team": "ANA", "gp": 3, "pts": 4}))
        self.assertTrue(_team_stats_row_has_data({"team": "CAR", "gp": "3"}))


if __name__ == "__main__":
    unittest.main()
