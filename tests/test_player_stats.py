from __future__ import annotations

import datetime as dt
import shutil
import unittest
import uuid

from hockey_app.data.nhl_api import SeasonBoundaries
from hockey_app.data.xml_cache import _xml_season_dir, read_player_stats_xml, write_player_stats_xml
from hockey_app.ui.tabs.player_stats import (
    _phase_date_range_for_nhl,
    _player_payload_is_usable,
    _player_payload_needs_refresh_for_phase,
)


class PlayerStatsPhaseTests(unittest.TestCase):
    def test_regular_season_range_stays_within_regular_bounds(self) -> None:
        bounds = SeasonBoundaries(
            preseason_start=dt.date(2025, 9, 20),
            regular_start=dt.date(2025, 10, 7),
            regular_end=dt.date(2026, 4, 17),
            playoffs_start=dt.date(2026, 4, 19),
            playoffs_end=dt.date(2026, 6, 20),
            first_scheduled_game=dt.date(2025, 9, 20),
            last_scheduled_game=dt.date(2026, 6, 20),
        )

        start, end = _phase_date_range_for_nhl(
            phase="Regular Season",
            bounds=bounds,
            season_start=dt.date(2025, 9, 20),
            season_end=dt.date(2026, 4, 25),
        )

        self.assertEqual(start, dt.date(2025, 10, 7))
        self.assertEqual(end, dt.date(2026, 4, 17))

    def test_payload_phase_must_match_requested_phase(self) -> None:
        payload = {
            "league": "NHL",
            "phase": "Postseason",
            "skaters": {
                "A": {"Goals": 1},
                "C": {"Assists": 2},
            },
            "goalies": {
                "B": {"Wins": 1},
                "D": {"Shutouts": 1},
            },
        }

        self.assertTrue(_player_payload_is_usable(payload, league="NHL", phase="Postseason"))
        self.assertFalse(_player_payload_is_usable(payload, league="NHL", phase="Regular Season"))

    def test_player_stats_xml_preserves_phase(self) -> None:
        season = f"test-player-stats-{uuid.uuid4().hex}"
        try:
            write_player_stats_xml(
                season=season,
                league="NHL",
                payload={
                    "date": "2026-04-25",
                    "league": "NHL",
                    "phase": "Postseason",
                    "updated": "4/25 12:00:00",
                    "skaters": {"Skater": {"team": "BUF", "_pid": 1, "Goals": 5}},
                    "goalies": {"Goalie": {"team": "TBL", "_pid": 2, "Wins": 3}},
                },
            )

            post = read_player_stats_xml(season=season, league="NHL", phase="Postseason")
            reg = read_player_stats_xml(season=season, league="NHL", phase="Regular Season")

            self.assertIsNotNone(post)
            self.assertEqual(post.get("phase"), "Postseason")
            self.assertIsNone(reg)
        finally:
            shutil.rmtree(_xml_season_dir(season), ignore_errors=True)

    def test_payload_refreshes_when_phase_end_has_advanced(self) -> None:
        payload = {
            "date": "2026-04-15",
            "league": "NHL",
            "phase": "Regular Season",
            "skaters": {"Skater": {"Goals": 5}},
            "goalies": {"Goalie": {"Wins": 3}},
        }

        self.assertTrue(
            _player_payload_needs_refresh_for_phase(payload, phase_end=dt.date(2026, 4, 17))
        )
        self.assertFalse(
            _player_payload_needs_refresh_for_phase(payload, phase_end=dt.date(2026, 4, 15))
        )


if __name__ == "__main__":
    unittest.main()
