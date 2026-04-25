from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
from pathlib import Path
from typing import Any

import pandas as pd

from hockey_app.data.paths import sims_dir
from hockey_app.data.xml_cache import (
    read_game_stats_xml,
    read_games_day_xml,
    read_player_stats_xml,
    read_table_xml,
    read_team_stats_xml,
)
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


def _df_payload(df: pd.DataFrame | None) -> dict[str, Any] | None:
    if not isinstance(df, pd.DataFrame) or df.empty:
        return None
    return {
        "columns": [str(col) for col in df.columns],
        "rows": _frame_to_rows(df),
    }


def _jsonable(value: Any) -> Any:
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(_jsonable(k)): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, tuple):
        return [_jsonable(v) for v in value]
    if isinstance(value, float):
        if pd.isna(value):
            return None
        return round(float(value), 6)
    return value


def _latest_value(table: dict[str, list[float | None]], team_code: str) -> float:
    values = table.get(team_code, [])
    for value in reversed(values):
        if value is not None:
            return float(value)
    return 0.0


def _date_range(start: dt.date, end: dt.date) -> list[dt.date]:
    if end < start:
        return []
    return [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]


def _export_games(season: str, start: dt.date, end: dt.date) -> dict[str, Any]:
    days: dict[str, list[dict[str, Any]]] = {}
    latest_day = ""
    for day in _date_range(start, end):
        rows = read_games_day_xml(season=season, day=day)
        if not rows:
            continue
        slim_rows: list[dict[str, Any]] = []
        for game in rows:
            away = game.get("awayTeam") if isinstance(game.get("awayTeam"), dict) else {}
            home = game.get("homeTeam") if isinstance(game.get("homeTeam"), dict) else {}
            slim_rows.append(
                {
                    "id": game.get("id"),
                    "gameType": str(
                        game.get("gameType")
                        or game.get("gameTypeId")
                        or game.get("game_type")
                        or game.get("game_type_id")
                        or ""
                    ),
                    "league": game.get("league") or "NHL",
                    "state": str(game.get("gameState") or "").upper(),
                    "status": game.get("statusText") or "",
                    "stage": game.get("displayStage") or "",
                    "startUtc": game.get("startTimeUTC") or "",
                    "away": {
                        "code": str(away.get("abbrev") or "").upper(),
                        "name": ((away.get("name") or {}).get("default") if isinstance(away.get("name"), dict) else away.get("name")) or "",
                        "score": away.get("score"),
                        "shots": away.get("shotsOnGoal"),
                    },
                    "home": {
                        "code": str(home.get("abbrev") or "").upper(),
                        "name": ((home.get("name") or {}).get("default") if isinstance(home.get("name"), dict) else home.get("name")) or "",
                        "score": home.get("score"),
                        "shots": home.get("shotsOnGoal"),
                    },
                }
            )
        iso = day.isoformat()
        days[iso] = slim_rows
        latest_day = iso
    return {"days": days, "latestDay": latest_day}


def _export_team_stats(season: str, league: str) -> dict[str, Any] | None:
    payload = read_team_stats_xml(season=season, league=league)
    if not isinstance(payload, dict):
        return None
    out: dict[str, Any] = {}
    for phase, blob in payload.items():
        if not isinstance(blob, dict):
            continue
        dates = [d for d in blob.get("dates", []) if isinstance(d, dt.date)]
        rows_by_date = blob.get("rows_by_date", {})
        phase_rows: dict[str, Any] = {}
        for day in sorted(dates):
            rows = rows_by_date.get(day, []) if isinstance(rows_by_date, dict) else []
            phase_rows[day.isoformat()] = _jsonable(rows)
        out[str(phase)] = {
            "dates": [d.isoformat() for d in sorted(dates)],
            "rowsByDate": phase_rows,
        }
    return out or None


def _export_desktop_data(season: str, start: dt.date, end: dt.date) -> dict[str, Any]:
    league = "NHL"
    points = _df_payload(read_table_xml(season=season, lump="points_history", league=league))
    goal_diff = _df_payload(read_table_xml(season=season, lump="goal_differential", league=league))
    return {
        "league": league,
        "scoreboard": _export_games(season, start, end),
        "stats": {
            "teamStats": _export_team_stats(season, league),
            "gameStats": _jsonable(read_game_stats_xml(season=season, league=league)),
            "playerStats": _jsonable(read_player_stats_xml(season=season, league=league)),
            "points": points,
            "goalDifferential": goal_diff,
        },
        "models": {
            "points": points,
            "teamStats": _export_team_stats(season, league),
            "gameStats": _jsonable(read_game_stats_xml(season=season, league=league)),
        },
    }


def _has_desktop_data(payload: dict[str, Any]) -> bool:
    desktop = payload.get("desktop")
    if not isinstance(desktop, dict):
        return False
    stats = desktop.get("stats")
    scoreboard = desktop.get("scoreboard")
    return bool(
        isinstance(stats, dict)
        and (
            stats.get("teamStats")
            or stats.get("gameStats")
            or stats.get("playerStats")
            or stats.get("points")
            or stats.get("goalDifferential")
        )
    ) or bool(isinstance(scoreboard, dict) and scoreboard.get("days"))


def _read_existing_payload(out_dir: Path) -> dict[str, Any] | None:
    path = out_dir / "data.json"
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else None
    except Exception:
        return None


def _copy_logo_assets(out_dir: Path) -> None:
    assets_src = Path(__file__).resolve().parents[1] / "assets"
    src = assets_src / "nhl_logos"
    dst = out_dir / "assets" / "nhl_logos"
    dst.mkdir(parents=True, exist_ok=True)
    if not src.exists():
        return
    for png in sorted(src.glob("*.png")):
        shutil.copy2(png, dst / png.name)
    cup_src = assets_src / "stanley_cup.png"
    if cup_src.exists():
        (out_dir / "assets").mkdir(parents=True, exist_ok=True)
        shutil.copy2(cup_src, out_dir / "assets" / "stanley_cup.png")


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

    # Desktop-backed tabs should export the same current cache range the desktop
    # app can render, not just the span covered by simulation CSVs.
    desktop_start = _season_start(season)
    desktop_end = max(end, dt.date.today())

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
        "desktop": _export_desktop_data(season, desktop_start, desktop_end),
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
    existing = _read_existing_payload(out_dir)
    if existing and not _has_desktop_data(payload) and _has_desktop_data(existing):
        payload["desktop"] = existing["desktop"]

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
