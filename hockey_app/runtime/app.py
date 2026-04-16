from __future__ import annotations

import datetime as dt
from pathlib import Path

import pandas as pd

from hockey_app.domain.colors import build_team_color_map
from hockey_app.domain.teams import TEAM_NAMES, canon_team_code, division_columns_for_codes
from hockey_app.data.paths import imgs_dir, sims_dir
from hockey_app.data.xml_cache import read_predictions_tables_xml, write_predictions_tables_xml
from hockey_app.runtime import logos as logosvc
from hockey_app.runtime import pipeline as pipesvc
from hockey_app.runtime.prof import StartupProfiler
from hockey_app.runtime.settings import default_settings
from hockey_app.runtime.storage import ensure_dir_writable
from hockey_app.runtime.types import RuntimeSettings


_settings: RuntimeSettings = default_settings()

SEASON = _settings["season"]
START_DATE = _settings["start_date"]
END_DATE = _settings["end_date"]

URL_SIMULATIONS = _settings["url_simulations"]
HEADERS = dict(_settings["headers"])
URL_LOGOS_BASE = _settings["url_logos_base"]

METRICS: dict[str, str] = dict(_settings["metrics"])
TAB_ORDER = list(_settings["tab_order"])
TAB_LABELS: dict[str, str] = dict(_settings["tab_labels"])
TAB_TITLES: dict[str, str] = dict(_settings["tab_titles"])

DARK_WINDOW_BG = _settings["dark_window_bg"]
DARK_CANVAS_BG = _settings["dark_canvas_bg"]
DARK_HILITE = _settings["dark_hilite"]

BASE = Path(__file__).resolve().parents[2]
ICLOUD_AVAILABLE = False
SIMS_DIR = sims_dir(SEASON)
# NHL logos are project-local so all machines use the same source files.
LOGOS_DIR = Path(__file__).resolve().parents[1] / "assets" / "nhl_logos"
LOGOS_DIR.mkdir(parents=True, exist_ok=True)
IMAGES_DIR = imgs_dir()


date_from_filename = pipesvc.date_from_filename
date_range = pipesvc.date_range
md_label = pipesvc.md_label


def download_missing_simulations(
    start_date: dt.date,
    end_date: dt.date,
    sims_dir: Path,
    index_url: str = URL_SIMULATIONS,
) -> list[str]:
    return pipesvc.download_missing_simulations(
        start_date=start_date,
        end_date=end_date,
        sims_dir=sims_dir,
        headers=HEADERS,
        ensure_dir_writable=ensure_dir_writable,
        index_url=index_url,
    )


def compile_probability_tables(
    sims_dir: Path,
    start_date: dt.date,
    end_date: dt.date,
) -> dict[str, pd.DataFrame]:
    return pipesvc.compile_probability_tables(
        sims_dir=sims_dir,
        start_date=start_date,
        end_date=end_date,
        metrics=METRICS,
        canon_team_code=canon_team_code,
    )


def logo_url(team_code: str) -> str:
    return logosvc.logo_url(team_code=team_code, canon_team_code=canon_team_code, url_base=URL_LOGOS_BASE)


def logo_path(team_code: str) -> Path:
    return logosvc.logo_path(team_code=team_code, canon_team_code=canon_team_code, logos_dir=LOGOS_DIR)


def ensure_logo_cached(team_code: str) -> None:
    logosvc.ensure_logo_cached(
        team_code=team_code,
        canon_team_code=canon_team_code,
        logos_dir=LOGOS_DIR,
        url_base=URL_LOGOS_BASE,
        headers=HEADERS,
    )


def launch_predictions_ui(tables: dict[str, pd.DataFrame]) -> None:
    from hockey_app.ui.app_window import launch_predictions_ui_window

    launch_predictions_ui_window(
        tables,
        season=SEASON,
        start_date=START_DATE,
        images_dir=IMAGES_DIR,
        tab_order=TAB_ORDER,
        tab_labels=TAB_LABELS,
        tab_titles=TAB_TITLES,
        team_names=TEAM_NAMES,
        dark_window_bg=DARK_WINDOW_BG,
        dark_canvas_bg=DARK_CANVAS_BG,
        dark_hilite=DARK_HILITE,
        canon_team_code=canon_team_code,
        division_columns_for_codes=division_columns_for_codes,
        build_team_color_map=build_team_color_map,
        ensure_logo_cached=ensure_logo_cached,
        logo_path=logo_path,
    )


def main() -> None:
    print("Starting process...")
    prof = StartupProfiler()

    try:
        ensure_dir_writable(SIMS_DIR)
    except Exception as e:
        print(f"ERROR: {e}")
        return
    prof.mark("ensure_dir_writable")

    tables = read_predictions_tables_xml(season=SEASON, metrics=TAB_ORDER)
    expected_last_col = f"{END_DATE.month}/{END_DATE.day}"
    has_complete_xml = bool(tables) and all(
        k in tables and not tables[k].empty and len(tables[k].columns) > 0 and str(tables[k].columns[-1]) == expected_last_col
        for k in TAB_ORDER
    )

    if not has_complete_xml:
        errs = download_missing_simulations(START_DATE, END_DATE, SIMS_DIR)
        prof.mark("download_missing_simulations")
        if errs:
            print("ERRORS occurred during download:")
            for msg in errs:
                print(f"- {msg}")

        try:
            tables = compile_probability_tables(SIMS_DIR, START_DATE, END_DATE)
        except Exception as e:
            print(f"ERROR: failed to compile tables: {e}")
            return
        try:
            write_predictions_tables_xml(
                season=SEASON,
                start=START_DATE,
                end=END_DATE,
                tables=tables,
            )
        except Exception:
            pass
        prof.mark("compile_probability_tables")
    else:
        prof.mark("load_predictions_tables_xml")

    try:
        launch_predictions_ui(tables)
    except Exception as e:
        print(f"ERROR: failed to launch UI: {e}")
        return
    prof.mark("launch_predictions_ui")
    prof.emit()

    print("Done.")


if __name__ == "__main__":
    main()
