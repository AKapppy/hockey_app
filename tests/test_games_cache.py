from __future__ import annotations

import datetime as dt
import shutil
import unittest
import uuid
from zoneinfo import ZoneInfo

from hockey_app.data.xml_cache import _status_time_sort_value, _xml_season_dir, read_games_day_xml, write_games_day_xml
from hockey_app.ui.tabs.games import (
    _live_status,
    _parse_status_time_local,
    _preserve_cached_game_rows,
    _promote_live_game_row_from_gamecenter,
)


class GamesCachePreserveTests(unittest.TestCase):
    def test_preserves_missing_cached_league_rows_during_partial_render(self) -> None:
        current = [
            {"id": 326, "league": "PWHL", "awayTeam": {"abbrev": "MTL"}, "homeTeam": {"abbrev": "SEA"}},
        ]
        cached = [
            {"id": 2025030124, "league": "NHL", "awayTeam": {"abbrev": "BUF"}, "homeTeam": {"abbrev": "TBL"}},
            {"id": 326, "league": "PWHL", "awayTeam": {"abbrev": "MTL"}, "homeTeam": {"abbrev": "SEA"}},
        ]

        merged = _preserve_cached_game_rows(current, cached)

        self.assertEqual([g["id"] for g in merged], [326, 2025030124])
        self.assertEqual({str(g.get("league")) for g in merged}, {"PWHL", "NHL"})

    def test_status_text_time_parser_orders_half_hour_before_later_hour(self) -> None:
        tz = ZoneInfo("America/New_York")
        selected_date = dt.date(2026, 4, 25)
        game_1230 = {"statusText": "12:30 PM EDT"}
        game_2pm = {"statusText": "2 PM EDT"}

        t1 = _parse_status_time_local(game_1230, tz, selected_date)
        t2 = _parse_status_time_local(game_2pm, tz, selected_date)

        self.assertIsNotNone(t1)
        self.assertIsNotNone(t2)
        self.assertLess(t1, t2)

    def test_xml_status_sort_value_handles_hour_only_times(self) -> None:
        selected_date = dt.date(2026, 4, 25)

        first = _status_time_sort_value(selected_date, "12:30 PM EDT")
        second = _status_time_sort_value(selected_date, "2 PM EDT")

        self.assertTrue(first)
        self.assertTrue(second)
        self.assertLess(first, second)

    def test_xml_round_trip_preserves_live_clock_period_and_shots(self) -> None:
        season = f"test-live-{uuid.uuid4().hex}"
        day = dt.date(2026, 4, 25)
        try:
            write_games_day_xml(
                season=season,
                day=day,
                games=[
                    {
                        "id": 2026020001,
                        "league": "NHL",
                        "gameState": "LIVE",
                        "statusText": "Live",
                        "clock": {"timeRemaining": "12:34"},
                        "periodDescriptor": {"number": 2},
                        "awayTeam": {"abbrev": "BUF", "score": 2, "shotsOnGoal": 22},
                        "homeTeam": {"abbrev": "TBL", "score": 1, "shotsOnGoal": 18},
                    }
                ],
            )

            rows = read_games_day_xml(season=season, day=day)

            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row.get("clock"), {"timeRemaining": "12:34"})
            self.assertEqual(row.get("periodDescriptor"), {"number": 2})
            self.assertEqual(row.get("awayTeam", {}).get("shotsOnGoal"), 22)
            self.assertEqual(row.get("homeTeam", {}).get("shotsOnGoal"), 18)
            self.assertEqual(_live_status(row), "2ND - 12:34")
        finally:
            shutil.rmtree(_xml_season_dir(season), ignore_errors=True)

    def test_promotes_live_gamecenter_fields_for_cached_rerender(self) -> None:
        game = {
            "id": 2026020001,
            "gameState": "LIVE",
            "statusText": "Live",
            "awayTeam": {"abbrev": "BUF", "score": 2},
            "homeTeam": {"abbrev": "TBL", "score": 1},
        }
        boxscore = {
            "awayTeam": {"sog": 25},
            "homeTeam": {"shotsOnGoal": 19},
        }
        pbp = {
            "gameState": "LIVE",
            "clock": {"timeRemaining": "8:41"},
            "periodDescriptor": {"number": 3},
            "plays": [],
        }

        out = _promote_live_game_row_from_gamecenter(game, boxscore=boxscore, pbp=pbp)

        self.assertEqual(out.get("awayTeam", {}).get("shotsOnGoal"), 25)
        self.assertEqual(out.get("homeTeam", {}).get("shotsOnGoal"), 19)
        self.assertEqual(out.get("clock"), {"timeRemaining": "8:41"})
        self.assertEqual(out.get("periodDescriptor"), {"number": 3})
        self.assertEqual(_live_status(out), "3RD - 8:41")


if __name__ == "__main__":
    unittest.main()
