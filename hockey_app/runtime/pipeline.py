from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Callable

import pandas as pd

from hockey_app.services import simulations as simsvc


def download_missing_simulations(
    *,
    start_date: dt.date,
    end_date: dt.date,
    sims_dir: Path,
    headers: dict[str, str],
    ensure_dir_writable: Callable[[Path], None],
    index_url: str,
) -> list[str]:
    return simsvc.download_missing_simulations(
        start_date,
        end_date,
        sims_dir,
        headers=headers,
        ensure_dir_writable=ensure_dir_writable,
        index_url=index_url,
    )


def compile_probability_tables(
    *,
    sims_dir: Path,
    start_date: dt.date,
    end_date: dt.date,
    metrics: dict[str, str],
    canon_team_code: Callable[[str], str],
) -> dict[str, pd.DataFrame]:
    return simsvc.compile_probability_tables(
        sims_dir,
        start_date,
        end_date,
        metrics=metrics,
        canon_team_code=canon_team_code,
    )


date_from_filename = simsvc.date_from_filename
date_range = simsvc.date_range
md_label = simsvc.md_label
