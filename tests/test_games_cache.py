from __future__ import annotations

import datetime as dt
import unittest
from zoneinfo import ZoneInfo

from hockey_app.data.xml_cache import _status_time_sort_value
from hockey_app.ui.tabs.games import _parse_status_time_local, _preserve_cached_game_rows


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


if __name__ == "__main__":
    unittest.main()
