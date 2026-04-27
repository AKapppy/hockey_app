from __future__ import annotations

import datetime as dt
import shutil
import unittest
import uuid
from unittest.mock import patch

import pandas as pd

from hockey_app.data.xml_cache import _xml_season_dir, read_table_xml, write_table_xml
from hockey_app.ui.tabs.game_stats import _phase_auto_scrolls_latest
from hockey_app.ui.tabs.team_stats import _load_nhl_games_for_date
from hockey_app.ui.tabs.points import _is_nhl_game_in_phase


class StatsPhaseViewTests(unittest.TestCase):
    def test_load_nhl_games_for_date_backfills_yesterday_when_cache_misses(self) -> None:
        class _FakeCache:
            def get_json(self, _key: str, ttl_s: int | None = None) -> None:
                return None

        class _FakeApi:
            def __init__(self) -> None:
                self.cache = _FakeCache()
                self.calls: list[dt.date] = []

            def score(self, day: dt.date, *, force_network: bool = False) -> dict[str, object]:
                self.calls.append(day)
                return {"games": [{"id": 1}]}

        api = _FakeApi()
        with patch("hockey_app.ui.tabs.team_stats.read_games_day_xml", return_value=[]):
            out = _load_nhl_games_for_date(api, dt.date.today() - dt.timedelta(days=1))

        self.assertEqual(out, [{"id": 1}])
        self.assertEqual(api.calls, [dt.date.today() - dt.timedelta(days=1)])

    def test_load_nhl_games_for_date_uses_local_games_xml_when_available(self) -> None:
        class _FakeCache:
            def get_json(self, _key: str, ttl_s: int | None = None) -> None:
                return None

        class _FakeApi:
            def __init__(self) -> None:
                self.cache = _FakeCache()
                self.called = False

            def score(self, day: dt.date, *, force_network: bool = False) -> dict[str, object]:
                self.called = True
                return {"games": [{"id": 99}]}

        api = _FakeApi()
        with patch(
            "hockey_app.ui.tabs.team_stats.read_games_day_xml",
            return_value=[
                {"id": 1, "league": "NHL", "gameState": "FINAL"},
                {"id": 2, "league": "PWHL", "gameState": "FINAL"},
                {"id": 3, "league": "NHL", "gameState": "LIVE"},
            ],
        ):
            out = _load_nhl_games_for_date(api, dt.date.today() - dt.timedelta(days=3))

        self.assertEqual(out, [{"id": 1, "league": "NHL", "gameState": "FINAL"}])
        self.assertFalse(api.called)

    def test_load_nhl_games_for_date_fetches_old_dates_when_cache_and_xml_miss(self) -> None:
        class _FakeCache:
            def get_json(self, _key: str, ttl_s: int | None = None) -> None:
                return None

        class _FakeApi:
            def __init__(self) -> None:
                self.cache = _FakeCache()
                self.called = False

            def score(self, day: dt.date, *, force_network: bool = False) -> dict[str, object]:
                self.called = True
                return {"games": [{"id": 1}]}

        api = _FakeApi()
        with patch("hockey_app.ui.tabs.team_stats.read_games_day_xml", return_value=[]):
            out = _load_nhl_games_for_date(api, dt.date.today() - dt.timedelta(days=3))

        self.assertEqual(out, [{"id": 1}])
        self.assertTrue(api.called)

    def test_table_xml_phase_filter_keeps_views_separate(self) -> None:
        season = f"test-table-phase-{uuid.uuid4().hex}"
        try:
            write_table_xml(
                season=season,
                lump="points_history",
                league="NHL",
                start=dt.date(2026, 4, 19),
                end=dt.date(2026, 4, 25),
                df=pd.DataFrame([[2.0]], index=["BUF"], columns=["4/25"]),
                phase="Postseason",
            )

            post = read_table_xml(season=season, lump="points_history", league="NHL", phase="Postseason")
            reg = read_table_xml(season=season, lump="points_history", league="NHL", phase="Regular Season")

            self.assertIsNotNone(post)
            self.assertIsNone(reg)
        finally:
            shutil.rmtree(_xml_season_dir(season), ignore_errors=True)

    def test_nhl_game_phase_classifier_uses_game_type(self) -> None:
        preseason = {"gameType": 1, "id": 2025010001}
        regular = {"gameType": 2, "id": 2025020001}
        postseason = {"gameType": 3, "id": 2025030111}

        self.assertTrue(_is_nhl_game_in_phase(preseason, "Preseason"))
        self.assertFalse(_is_nhl_game_in_phase(preseason, "Regular Season"))
        self.assertTrue(_is_nhl_game_in_phase(regular, "Regular Season"))
        self.assertFalse(_is_nhl_game_in_phase(regular, "Postseason"))
        self.assertTrue(_is_nhl_game_in_phase(postseason, "Postseason"))

    def test_game_stats_postseason_does_not_auto_hide_early_dates(self) -> None:
        self.assertTrue(_phase_auto_scrolls_latest("Regular Season"))
        self.assertFalse(_phase_auto_scrolls_latest("Postseason"))


if __name__ == "__main__":
    unittest.main()
