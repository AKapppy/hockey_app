from __future__ import annotations

import datetime as dt
from typing import TypedDict


class RuntimeSettings(TypedDict):
    season: str
    start_date: dt.date
    end_date: dt.date
    url_simulations: str
    headers: dict[str, str]
    url_logos_base: str
    metrics: dict[str, str]
    tab_order: list[str]
    tab_labels: dict[str, str]
    tab_titles: dict[str, str]
    dark_window_bg: str
    dark_canvas_bg: str
    dark_hilite: str
    base_name: str
