from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
from pathlib import Path
from typing import Any

import pandas as pd

from hockey_app.data.paths import sims_dir
from hockey_app.domain.colors import build_team_color_map, theme_adjusted_line_color
from hockey_app.domain.teams import TEAM_NAMES, TEAM_TO_CONF, TEAM_TO_DIV, canon_team_code
from hockey_app.services.simulations import (
    compile_probability_tables,
    date_from_filename,
    download_missing_simulations,
)

METRICS: dict[str, str] = {
    "madeplayoffs": "madePlayoffs",
    "round2": "round2",
    "round3": "round3",
    "round4": "round4",
    "woncup": "wonCup",
}

METRIC_LABELS: dict[str, str] = {
    "madeplayoffs": "Make Playoffs",
    "round2": "Make Round 2",
    "round3": "Make Conference Final",
    "round4": "Make Cup Final",
    "woncup": "Win Cup",
}

METRIC_TITLES: dict[str, str] = {
    "madeplayoffs": "Playoff Race",
    "round2": "Round 2",
    "round3": "Conference Final",
    "round4": "Cup Final",
    "woncup": "Stanley Cup",
}

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; HockeyAppWebExporter/1.0)"}
URL_SIMULATIONS = "https://moneypuck.com/moneypuck/simulations/"


def _default_season(today: dt.date | None = None) -> str:
    d = today or dt.date.today()
    y0 = d.year if d.month >= 10 else d.year - 1
    return f"{y0}-{y0 + 1}"


def _season_start(season: str) -> dt.date:
    try:
        y0 = int(str(season).split("-", 1)[0])
    except Exception:
        y0 = dt.date.today().year
    return dt.date(y0, 10, 1)


def _parse_date(value: str | None) -> dt.date | None:
    if not value:
        return None
    return dt.date.fromisoformat(value)


def _csv_dates(path: Path) -> list[dt.date]:
    dates: list[dt.date] = []
    for csv_path in sorted(path.glob("*.csv")):
        file_date = date_from_filename(csv_path.name)
        if file_date is not None:
            dates.append(file_date)
    return sorted(set(dates))


def _ensure_writable(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    probe = path / ".write-test"
    probe.write_text("ok", encoding="utf-8")
    probe.unlink(missing_ok=True)


def _frame_to_rows(df: pd.DataFrame) -> dict[str, list[float | None]]:
    rows: dict[str, list[float | None]] = {}
    for team_code, row in df.iterrows():
        values: list[float | None] = []
        for value in row.tolist():
            if pd.isna(value):
                values.append(None)
            else:
                values.append(round(float(value), 4))
        rows[str(team_code)] = values
    return rows


def _latest_value(table: dict[str, list[float | None]], team_code: str) -> float:
    values = table.get(team_code, [])
    for value in reversed(values):
        if value is not None:
            return float(value)
    return 0.0


def _copy_logo_assets(out_dir: Path) -> None:
    src = Path(__file__).resolve().parents[1] / "assets" / "nhl_logos"
    dst = out_dir / "assets" / "nhl_logos"
    dst.mkdir(parents=True, exist_ok=True)
    if not src.exists():
        return
    for png in sorted(src.glob("*.png")):
        shutil.copy2(png, dst / png.name)


def build_payload(
    *,
    season: str,
    start: dt.date,
    end: dt.date,
    simulations_dir: Path,
) -> dict[str, Any]:
    tables = compile_probability_tables(
        simulations_dir,
        start,
        end,
        metrics=METRICS,
        canon_team_code=canon_team_code,
    )
    if not tables or all(df.empty for df in tables.values()):
        raise SystemExit(f"No simulation data found in {simulations_dir}")

    table_payload: dict[str, dict[str, Any]] = {}
    all_codes: set[str] = set()
    for metric, df in tables.items():
        all_codes.update(str(code) for code in df.index)
        table_payload[metric] = {
            "columns": [str(col) for col in df.columns],
            "rows": _frame_to_rows(df),
        }

    colors = build_team_color_map(all_codes)
    made_playoffs = table_payload.get("madeplayoffs", {}).get("rows", {})
    team_rows = []
    for code in sorted(all_codes):
        base = colors.get(code, "#888888")
        team_rows.append(
            {
                "code": code,
                "name": TEAM_NAMES.get(code, code),
                "division": TEAM_TO_DIV.get(code, ""),
                "conference": TEAM_TO_CONF.get(code, ""),
                "color": theme_adjusted_line_color(code, base),
                "logo": f"assets/nhl_logos/{code}.png",
                "sortValue": round(_latest_value(made_playoffs, code), 4),
            }
        )
    team_rows.sort(key=lambda team: (-float(team["sortValue"]), str(team["name"])))

    return {
        "metadata": {
            "season": season,
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "source": "MoneyPuck simulations",
        },
        "metrics": [
            {"key": key, "label": METRIC_LABELS[key], "title": METRIC_TITLES[key]}
            for key in METRICS
        ],
        "teams": team_rows,
        "tables": table_payload,
    }


def export_web(
    *,
    out_dir: Path,
    season: str,
    start: dt.date | None,
    end: dt.date | None,
    refresh: bool,
) -> Path:
    simulations_dir = sims_dir(season)
    if refresh:
        refresh_start = start or _season_start(season)
        refresh_end = end or dt.date.today()
        errors = download_missing_simulations(
            refresh_start,
            refresh_end,
            simulations_dir,
            headers=HEADERS,
            ensure_dir_writable=_ensure_writable,
            index_url=URL_SIMULATIONS,
        )
        if errors:
            joined = "\n".join(f"- {msg}" for msg in errors)
            raise SystemExit(f"Failed to refresh simulations:\n{joined}")

    dates = _csv_dates(simulations_dir)
    if not dates:
        raise SystemExit(
            f"No cached simulations found in {simulations_dir}. "
            "Run again with --refresh to download them."
        )

    export_start = start or dates[0]
    export_end = end or dates[-1]
    payload = build_payload(
        season=season,
        start=export_start,
        end=export_end,
        simulations_dir=simulations_dir,
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    _copy_logo_assets(out_dir)
    data_json = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    (out_dir / "data.json").write_text(data_json + "\n", encoding="utf-8")
    (out_dir / "data.js").write_text(
        "window.HOCKEY_APP_DATA = " + data_json + ";\n",
        encoding="utf-8",
    )
    return out_dir / "data.js"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export the static GitHub Pages web app data.")
    parser.add_argument("--out", default="docs", help="Output directory for static web files.")
    parser.add_argument("--season", default=_default_season(), help="Season key, for example 2025-2026.")
    parser.add_argument("--start", help="Optional export start date, YYYY-MM-DD.")
    parser.add_argument("--end", help="Optional export end date, YYYY-MM-DD.")
    parser.add_argument("--refresh", action="store_true", help="Download missing simulation CSVs first.")
    args = parser.parse_args(argv)

    data_path = export_web(
        out_dir=Path(args.out),
        season=str(args.season),
        start=_parse_date(args.start),
        end=_parse_date(args.end),
        refresh=bool(args.refresh),
    )
    print(f"Wrote {data_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
