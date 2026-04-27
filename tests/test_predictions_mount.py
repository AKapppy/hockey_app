from __future__ import annotations

import datetime as dt
import unittest
from unittest.mock import patch

import pandas as pd

from hockey_app.ui.predictions_mount import (
    _first_locked_prediction_column,
    _prediction_visible_row_count,
    _prepare_prediction_render_df,
    _rightmost_column_team_order,
    _trim_prediction_df_at_locked_column,
)


class PredictionsMountTests(unittest.TestCase):
    def test_first_locked_prediction_column_finds_first_all_zero_or_one_column(self) -> None:
        df = pd.DataFrame(
            {
                "d0": [0.55, 0.45],
                "d1": [1.0, 0.0],
                "d2": [1.0, 0.0],
            },
            index=["A", "B"],
        )

        self.assertEqual(_first_locked_prediction_column(df), 1)

    def test_trim_prediction_df_keeps_first_locked_column_and_stops(self) -> None:
        df = pd.DataFrame(
            {
                "d0": [0.55, 0.45],
                "d1": [1.0, 0.0],
                "d2": [1.0, 0.0],
            },
            index=["A", "B"],
        )

        out = _trim_prediction_df_at_locked_column(df)

        self.assertEqual(list(out.columns), ["d0", "d1"])

    def test_prepare_prediction_render_df_filters_round2_to_playoff_field_after_round1_starts(self) -> None:
        df = pd.DataFrame(
            {
                "d0": [0.40, 0.35, 0.00, 0.00],
                "d1": [1.0, 0.0, 0.0, 0.0],
            },
            index=["WPG", "DAL", "CGY", "SEA"],
        )

        with patch("hockey_app.ui.tabs.models_data.playoffs_have_started", return_value=True), patch(
            "hockey_app.ui.tabs.models_data.playoff_field_order",
            return_value=["DAL", "WPG", "TOR", "FLA"],
        ):
            out = _prepare_prediction_render_df(
                df,
                tab_key="round2",
                start_date=dt.date(2026, 4, 10),
                league="NHL",
            )

        self.assertEqual(list(out.index), ["DAL", "WPG", "CGY", "SEA"])
        self.assertEqual(list(out.columns), ["d0", "d1"])

    def test_prepare_prediction_render_df_leaves_make_playoffs_rows_unfiltered(self) -> None:
        df = pd.DataFrame(
            {
                "d0": [0.80, 0.10, 0.10],
                "d1": [1.0, 0.0, 0.0],
            },
            index=["DAL", "WPG", "CGY"],
        )

        with patch("hockey_app.ui.tabs.models_data.playoffs_have_started", return_value=True), patch(
            "hockey_app.ui.tabs.models_data.playoff_field_order",
            return_value=["DAL", "WPG"],
        ):
            out = _prepare_prediction_render_df(
                df,
                tab_key="madeplayoffs",
                start_date=dt.date(2026, 4, 10),
                league="NHL",
            )

        self.assertEqual(list(out.index), ["DAL", "WPG", "CGY"])
        self.assertEqual(list(out.columns), ["d0", "d1"])

    def test_rightmost_column_team_order_uses_last_column_descending(self) -> None:
        df = pd.DataFrame(
            {
                "d0": [0.20, 0.90, 0.50],
                "d1": [0.70, 0.40, 0.70],
            },
            index=["SEA", "DAL", "BOS"],
        )

        self.assertEqual(_rightmost_column_team_order(df), ["BOS", "SEA", "DAL"])

    def test_rightmost_column_team_order_breaks_ties_by_scanning_left(self) -> None:
        df = pd.DataFrame(
            {
                "d0": [0.10, 0.90, 0.20],
                "d1": [0.40, 0.40, 0.30],
                "d2": [0.70, 0.70, 0.60],
            },
            index=["SEA", "DAL", "BOS"],
        )

        self.assertEqual(_rightmost_column_team_order(df), ["DAL", "SEA", "BOS"])

    def test_prediction_visible_row_count_uses_prior_round_qualifiers(self) -> None:
        prepared = pd.DataFrame(
            {
                "d0": [0.3, 0.3, 0.2],
                "d1": [0.6, 0.4, 0.0],
            },
            index=["DAL", "WPG", "CGY"],
        )

        with patch("hockey_app.ui.predictions_mount._playoff_started_round", return_value=2):
            count = _prediction_visible_row_count(
                {},
                tab_key="round3",
                start_date=dt.date(2026, 4, 10),
                league="NHL",
                prepared_df=prepared,
            )

        self.assertEqual(count, 3)

    def test_prediction_visible_row_count_keeps_round3_at_sixteen_during_round1(self) -> None:
        prepared = pd.DataFrame({"d0": [0.3] * 20}, index=[f"T{i}" for i in range(20)])

        with patch("hockey_app.ui.predictions_mount._playoff_started_round", return_value=1):
            count = _prediction_visible_row_count(
                {},
                tab_key="round3",
                start_date=dt.date(2026, 4, 10),
                league="NHL",
                prepared_df=prepared,
            )

        self.assertEqual(count, 16)

    def test_prediction_visible_row_count_keeps_round3_at_eight_after_round2_starts(self) -> None:
        prepared = pd.DataFrame({"d0": [0.3] * 20}, index=[f"T{i}" for i in range(20)])

        with patch("hockey_app.ui.predictions_mount._playoff_started_round", return_value=3):
            count = _prediction_visible_row_count(
                {},
                tab_key="round3",
                start_date=dt.date(2026, 4, 10),
                league="NHL",
                prepared_df=prepared,
            )

        self.assertEqual(count, 8)


if __name__ == "__main__":
    unittest.main()
