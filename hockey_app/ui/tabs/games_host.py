from __future__ import annotations

import tkinter as tk
from typing import Any, Dict

from hockey_app.config import END_DATE, SEASON, SEASON_PROBE_DATE, START_DATE, TIMEZONE
from hockey_app.data.cache import DiskCache
from hockey_app.data.espn_api import ESPNApi
from hockey_app.data.nhl_api import NHLApi
from hockey_app.data.pwhl_api import PWHLApi
from hockey_app.data.paths import espn_dir, nhl_dir, pwhl_dir
from hockey_app.ui.tabs.games import build_games_tab


def populate_games_tab(
    parent: tk.Frame,
    logo_bank: Any,
    *,
    team_names: Dict[str, str],
    bg: str,
    card_bg: str,
    accent: str,
    on_data_refresh=None,
) -> None:
    """
    Legacy adapter: mount the modern Games-tab renderer inside the legacy shell.
    Signature is intentionally kept for compatibility with legacy call sites.
    """
    # Keep legacy API surface stable; these are not used by the modern renderer.
    _ = team_names, bg, card_bg, accent

    for child in parent.winfo_children():
        child.destroy()

    cache = DiskCache(nhl_dir(SEASON))
    api = NHLApi(cache)
    espn = ESPNApi(DiskCache(espn_dir(SEASON)))
    pwhl = PWHLApi(DiskCache(pwhl_dir(SEASON)))

    ctx = {
        "nhl": api,
        "espn": espn,
        "pwhl": pwhl,
        "logos": logo_bank,
        "season": SEASON,
        "season_start": START_DATE,
        "season_end": END_DATE,
        "season_probe_date": SEASON_PROBE_DATE,
        "timezone": TIMEZONE,
        "on_data_refresh": on_data_refresh,
    }
    view = build_games_tab(parent, ctx)
    view.pack(fill="both", expand=True)
