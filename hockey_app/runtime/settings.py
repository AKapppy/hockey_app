from __future__ import annotations

import datetime as dt

from hockey_app import config as cfg
from hockey_app.runtime.types import RuntimeSettings


def _fallback_season() -> str:
    d = dt.date.today()
    y0 = d.year if d.month >= 10 else d.year - 1
    return f"{y0}-{y0 + 1}"


def _fallback_start_date(season: str) -> dt.date:
    parts = [p for p in str(season).split("-") if p.strip()]
    if len(parts) == 2 and parts[0].isdigit():
        return dt.date(int(parts[0]), 10, 1)
    d = dt.date.today()
    return dt.date(d.year, 10, 1)


def _fallback_end_date() -> dt.date:
    return dt.date.today()


def default_settings() -> RuntimeSettings:
    season = str(getattr(cfg, "SEASON", _fallback_season()))
    start_date = getattr(cfg, "START_DATE", _fallback_start_date(season))
    end_date = getattr(cfg, "END_DATE", _fallback_end_date())
    return {
        "season": season,
        "start_date": start_date,
        "end_date": end_date,
        "url_simulations": "https://moneypuck.com/moneypuck/simulations/",
        "headers": {"User-Agent": "Mozilla/5.0 (compatible; MoneyPuckDownloader/1.0)"},
        "url_logos_base": "https://peter-tanner.com/moneypuck/logos/",
        "metrics": {
            "madeplayoffs": "madePlayoffs",
            "round2": "round2",
            "round3": "round3",
            "round4": "round4",
            "woncup": "wonCup",
        },
        "tab_order": ["madeplayoffs", "round2", "round3", "round4", "woncup"],
        "tab_labels": {
            "madeplayoffs": "Make Playoffs",
            "round2": "Make Round 2",
            "round3": "Make Conference Final",
            "round4": "Make Cup Final",
            "woncup": "Win Cup",
        },
        "tab_titles": {
            "madeplayoffs": "Playoff Race",
            "round2": "Win First Round",
            "round3": "Win Second Round",
            "round4": "Win Conference Finals",
            "woncup": "Win Stanley Cup",
        },
        "dark_window_bg": "#2c2c2c",
        "dark_canvas_bg": "#262626",
        "dark_hilite": "#0A84FF",
        "base_name": "MoneyPuck Data",
    }
