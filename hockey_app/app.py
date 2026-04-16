from __future__ import annotations

import datetime as dt
import errno
import importlib
import sys
import time
from typing import Any

import tkinter as tk
from tkinter import messagebox

from . import config as cfg
from .data.paths import sims_dir


def _import_runtime_app() -> object:
    """Import canonical runtime module."""
    return importlib.import_module("hockey_app.runtime.app")


def _is_deadlock_error(exc: Exception) -> bool:
    if isinstance(exc, OSError) and exc.errno == errno.EDEADLK:
        return True
    return "Resource deadlock avoided" in str(exc)


def main() -> None:
    """Entry point: run the canonical runtime pipeline, then launch the UI."""

    mp = _import_runtime_app()

    # Sync season + derived dirs inside the runtime module.
    try:
        setattr(mp, "SEASON", cfg.SEASON)
        setattr(mp, "SIMS_DIR", sims_dir(cfg.SEASON))
    except Exception:
        pass

    start = getattr(cfg, "START_DATE", dt.date.today() - dt.timedelta(days=7))
    end = getattr(cfg, "END_DATE", dt.date.today())

    # Download all missing simulations from season start to today.
    sims_dir = getattr(mp, "SIMS_DIR")
    errors: list[str] = []
    tables: dict[str, Any] = {}
    max_retries = 5
    for i in range(max_retries + 1):
        try:
            errors = mp.download_missing_simulations(start, end, sims_dir)  # type: ignore[attr-defined]
            tables = mp.compile_probability_tables(sims_dir, start, end)  # type: ignore[attr-defined]
            break
        except Exception as e:
            if _is_deadlock_error(e) and i < max_retries:
                time.sleep(0.15 * (i + 1))
                continue
            errors = [f"MoneyPuck pipeline failed: {e}"]
            tables = {}
            break

    if not tables:
        # If something went wrong, show a friendly error and exit.
        root = tk.Tk()
        root.withdraw()

        details = "\n".join(errors) if errors else "No CSVs were downloaded or found."
        messagebox.showerror(
            "MoneyPuck simulations missing",
            "Couldn't load MoneyPuck simulation CSVs.\n\n"
            f"Season: {cfg.SEASON}\nRange: {start} → {end}\n\n"
            f"Details:\n{details}",
        )
        try:
            root.destroy()
        except Exception:
            pass
        return

    # NOTE: UI launcher creates its own Tk root.
    mp.launch_predictions_ui(tables)  # type: ignore[attr-defined]


if __name__ == "__main__":
    # Support running as: python hockey_app/app.py
    # Ensure the *project root* (parent of the package) is on sys.path
    # so absolute imports like `import hockey_app` work.
    from pathlib import Path

    project_root = str(Path(__file__).resolve().parents[1])
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    main()
