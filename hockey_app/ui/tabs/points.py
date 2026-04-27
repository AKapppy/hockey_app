from __future__ import annotations

import datetime as dt
import tkinter as tk
from typing import Any, Callable, Dict
from tkinter import ttk

import pandas as pd

from hockey_app.config import END_DATE, SEASON, SEASON_PROBE_DATE, START_DATE, TEAM_NAMES, canon_team_code
from hockey_app.data.cache import DiskCache
from hockey_app.data.nhl_api import NHLApi
from hockey_app.data.pwhl_api import PWHLApi
from hockey_app.data.paths import nhl_dir, pwhl_dir
from hockey_app.data.xml_cache import read_game_stats_xml, read_table_xml, write_table_xml


NHL_PHASE_CHOICES = ["Regular Season", "Preseason", "Postseason"]


def _normalize_nhl_phase_name(value: str) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"preseason", "pre-season", "pre"}:
        return "Preseason"
    if raw in {"postseason", "post-season", "playoffs", "playoff", "post"}:
        return "Postseason"
    return "Regular Season"


def _phase_cache_token(value: str) -> str:
    return _normalize_nhl_phase_name(value).lower().replace(" ", "_")


def _nhl_phase_table_key(value: str) -> str:
    phase_name = _normalize_nhl_phase_name(value)
    if phase_name == "Preseason":
        return "preseason"
    if phase_name == "Postseason":
        return "postseason"
    return "regular"


def _nhl_phase_bounds(bounds: Any, phase: str, *, season_start: dt.date, season_end: dt.date) -> tuple[dt.date, dt.date]:
    phase_name = _normalize_nhl_phase_name(phase)
    preseason_start = getattr(bounds, "preseason_start", None) or season_start
    regular_start = getattr(bounds, "regular_start", None) or season_start
    regular_end = getattr(bounds, "regular_end", None) or season_end
    playoffs_start = getattr(bounds, "playoffs_start", None) or season_end
    playoffs_end = getattr(bounds, "playoffs_end", None) or season_end

    if phase_name == "Preseason":
        start = preseason_start
        end = regular_start - dt.timedelta(days=1)
    elif phase_name == "Postseason":
        start = playoffs_start
        end = playoffs_end
    else:
        start = regular_start
        end = regular_end

    start = max(season_start, start)
    end = min(season_end, end)
    if end < start:
        end = start
    return start, end


def _date_labels(start: dt.date, end: dt.date) -> list[tuple[dt.date, str]]:
    out: list[tuple[dt.date, str]] = []
    d = start
    while d <= end:
        out.append((d, f"{d.month}/{d.day}"))
        d += dt.timedelta(days=1)
    return out


def _is_final(g: dict[str, Any]) -> bool:
    s = str(g.get("gameState") or g.get("gameStatus") or "").upper()
    return s in {"FINAL", "OFF"} or s.startswith("FINAL")


def _team_code(team_obj: dict[str, Any]) -> str:
    raw = team_obj.get("abbrev") or team_obj.get("abbreviation") or team_obj.get("teamAbbrev") or ""
    return canon_team_code(str(raw).upper())


def _is_extra_time(g: dict[str, Any]) -> bool:
    pdx = g.get("periodDescriptor") or {}
    ptype = str(pdx.get("periodType") or "").upper()
    if ptype in {"OT", "SO"}:
        return True
    go = g.get("gameOutcome") or {}
    lp = str(go.get("lastPeriodType") or "").upper()
    return lp in {"OT", "SO"}


def _is_nhl_game_in_phase(g: dict[str, Any], phase: str) -> bool:
    phase_name = _normalize_nhl_phase_name(phase)
    gt = g.get("gameType") or g.get("gameTypeId") or g.get("gameTypeCode")
    gt_txt = str(gt or "").strip().upper()
    if phase_name == "Preseason":
        if gt_txt in {"1", "PR", "PRE"}:
            return True
        if gt_txt in {"2", "R", "3", "P"}:
            return False
    elif phase_name == "Postseason":
        if gt_txt in {"3", "P"}:
            return True
        if gt_txt in {"1", "PR", "PRE", "2", "R"}:
            return False
    else:
        if gt_txt in {"2", "R"}:
            return True
        if gt_txt in {"1", "PR", "PRE", "3", "P"}:
            return False
    gid = str(g.get("id") or g.get("gameId") or "").strip()
    if phase_name == "Preseason":
        return gid.startswith("202501")
    if phase_name == "Postseason":
        return gid.startswith("202503")
    if gid.startswith("202502"):
        return True
    if gid.startswith(("202501", "202503")):
        return False
    return False


def _is_nhl_regular_season_game(g: dict[str, Any]) -> bool:
    return _is_nhl_game_in_phase(g, "Regular Season")


def _points_from_game_result(result: str, *, league: str) -> int:
    code = str(result or "").upper().strip()
    if not code:
        return 0
    if league == "PWHL":
        if code == "W":
            return 3
        if code in {"OTW", "SOW"}:
            return 2
        if code in {"OTL", "SOL"}:
            return 1
        return 0
    if code in {"W", "OTW", "SOW"}:
        return 2
    if code in {"OTL", "SOL"}:
        return 1
    return 0


def _build_points_df_from_game_stats_xml(
    *,
    league: str,
    teams: list[str],
    start: dt.date,
    end: dt.date,
    phase: str,
) -> pd.DataFrame | None:
    if end < start:
        return None
    phase_tables = read_game_stats_xml(season=SEASON, league=league)
    if not isinstance(phase_tables, dict):
        return None
    phase_table = phase_tables.get(_nhl_phase_table_key(phase))
    if not isinstance(phase_table, dict):
        return None

    rows = phase_table.get("rows")
    date_cols = phase_table.get("date_cols")
    if not isinstance(rows, list) or not isinstance(date_cols, list):
        return None

    labels = [lbl for _d, lbl in _date_labels(start, end)]
    if not labels:
        return None
    col_set = {str(c) for c in date_cols}
    if any(lbl not in col_set for lbl in labels):
        return None

    row_map: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = canon_team_code(str(row.get("team") or "").upper())
        if code in teams:
            row_map[code] = row

    running: dict[str, int] = {t: 0 for t in teams}
    by_col: dict[str, list[float]] = {}
    for lbl in labels:
        for t in teams:
            row = row_map.get(t) or {}
            running[t] += _points_from_game_result(str(row.get(lbl) or ""), league=league)
        by_col[lbl] = [float(running[t]) for t in teams]
    return pd.DataFrame(by_col, index=teams, dtype="float64")


def _build_points_df(api: NHLApi, start: dt.date, end: dt.date, *, phase: str) -> tuple[pd.DataFrame, list[str]]:
    teams = [canon_team_code(c) for c in TEAM_NAMES.keys()]
    teams = sorted(set(teams), key=lambda c: (TEAM_NAMES.get(c, c), c))
    from_game_stats = _build_points_df_from_game_stats_xml(
        league="NHL",
        teams=teams,
        start=start,
        end=end,
        phase=phase,
    )
    if isinstance(from_game_stats, pd.DataFrame) and not from_game_stats.empty:
        return from_game_stats, teams

    running: Dict[str, int] = {t: 0 for t in teams}

    by_col: dict[str, list[float]] = {}
    seen_games: set[int] = set()
    today = dt.date.today()

    def _load_day_games(d: dt.date) -> list[dict[str, Any]]:
        iso = d.isoformat()
        try:
            final_hit = api.cache.get_json(f"nhl/score/final/{iso}", ttl_s=None)  # type: ignore[attr-defined]
        except Exception:
            final_hit = None
        if isinstance(final_hit, dict):
            return list((final_hit.get("games") or []))

        try:
            live_hit = api.cache.get_json(f"nhl/score/live/{iso}", ttl_s=None)  # type: ignore[attr-defined]
        except Exception:
            live_hit = None
        if isinstance(live_hit, dict):
            live_games = list((live_hit.get("games") or []))
            # If a cached past-day live payload still has in-progress states,
            # force one refresh so completed games become visible in points.
            if d < today and live_games and any(not _is_final(g) for g in live_games):
                try:
                    fresh = api.score(d, force_network=True) or {}
                    return list((fresh.get("games") or []))
                except Exception:
                    pass
            return live_games
        try:
            return list(((api.score(d) or {}).get("games") or []))
        except Exception:
            return []

    for d, col in _date_labels(start, end):
        games = _load_day_games(d)

        for g in games:
            gid = int(g.get("id") or g.get("gameId") or 0)
            if gid and gid in seen_games:
                continue
            if not _is_nhl_game_in_phase(g, phase):
                if gid:
                    seen_games.add(gid)
                continue
            if not _is_final(g):
                continue

            away = g.get("awayTeam") or {}
            home = g.get("homeTeam") or {}
            ac = _team_code(away)
            hc = _team_code(home)
            if ac not in running or hc not in running:
                if gid:
                    seen_games.add(gid)
                continue

            try:
                ascore = int(away.get("score") or 0)
                hscore = int(home.get("score") or 0)
            except Exception:
                if gid:
                    seen_games.add(gid)
                continue

            if ascore == hscore:
                if gid:
                    seen_games.add(gid)
                continue

            extra = _is_extra_time(g)
            if ascore > hscore:
                running[ac] += 2
                running[hc] += 1 if extra else 0
            else:
                running[hc] += 2
                running[ac] += 1 if extra else 0

            if gid:
                seen_games.add(gid)

        by_col[col] = [float(running[t]) for t in teams]

    df = pd.DataFrame(by_col, index=teams, dtype="float64")
    return df, teams


PWHL_TEAM_NAMES: dict[str, str] = {
    "BOS": "Boston Fleet",
    "MIN": "Minnesota Frost",
    "MTL": "Montreal Victoire",
    "NY": "New York Sirens",
    "OTT": "Ottawa Charge",
    "TOR": "Toronto Sceptres",
    "VAN": "Vancouver",
    "SEA": "Seattle",
}


def _build_points_df_pwhl(api: PWHLApi, start: dt.date, end: dt.date) -> tuple[pd.DataFrame, list[str]]:
    teams = sorted(PWHL_TEAM_NAMES.keys(), key=lambda c: (PWHL_TEAM_NAMES.get(c, c), c))
    from_game_stats = _build_points_df_from_game_stats_xml(
        league="PWHL",
        teams=teams,
        start=start,
        end=end,
        phase="Regular Season",
    )
    if isinstance(from_game_stats, pd.DataFrame) and not from_game_stats.empty:
        return from_game_stats, teams

    running: Dict[str, int] = {t: 0 for t in teams}
    by_col: dict[str, list[float]] = {}
    seen_games: set[int] = set()

    for d, col in _date_labels(start, end):
        try:
            games = list(api.get_games_for_date(d, allow_network=True))
        except Exception:
            games = []

        for g in games:
            gid = int(g.get("id") or g.get("gameId") or 0)
            if gid and gid in seen_games:
                continue
            if not _is_final(g):
                continue

            away = g.get("awayTeam") or {}
            home = g.get("homeTeam") or {}
            ac = canon_team_code(str(away.get("abbrev") or "").upper())
            hc = canon_team_code(str(home.get("abbrev") or "").upper())
            if ac not in running or hc not in running:
                if gid:
                    seen_games.add(gid)
                continue

            try:
                ascore = int(away.get("score") or 0)
                hscore = int(home.get("score") or 0)
            except Exception:
                if gid:
                    seen_games.add(gid)
                continue

            if ascore == hscore:
                if gid:
                    seen_games.add(gid)
                continue

            status = str(g.get("statusText") or "").upper()
            extra = ("OT" in status) or ("SO" in status)
            # PWHL standings points: regulation win=3, OT/SO win=2, OT/SO loss=1.
            if ascore > hscore:
                running[ac] += 2 if extra else 3
                running[hc] += 1 if extra else 0
            else:
                running[hc] += 2 if extra else 3
                running[ac] += 1 if extra else 0

            if gid:
                seen_games.add(gid)

        by_col[col] = [float(running[t]) for t in teams]

    df = pd.DataFrame(by_col, index=teams, dtype="float64")
    return df, teams


def _df_to_payload(df: pd.DataFrame, original_order: list[str]) -> dict[str, Any]:
    return {
        "index": [str(x) for x in df.index],
        "columns": [str(c) for c in df.columns],
        "data": [[None if pd.isna(v) else float(v) for v in row] for row in df.to_numpy()],
        "original_order": [str(x) for x in original_order],
    }


def _df_from_payload(payload: dict[str, Any]) -> tuple[pd.DataFrame, list[str]] | None:
    try:
        idx = list(map(str, payload.get("index") or []))
        cols = list(map(str, payload.get("columns") or []))
        data = payload.get("data") or []
        original_order = list(map(str, payload.get("original_order") or idx))
        df = pd.DataFrame(data, index=idx, columns=cols, dtype="float64")
        return df, original_order
    except Exception:
        return None


def populate_points_tab(
    parent,
    logo_bank: Any,
    *,
    team_colors: dict[str, str],
    team_col_width: int,
    cell_width: int,
    league: str = "NHL",
    get_selected_team_code: Callable[[], str | None],
    set_selected_team_code: Callable[[str | None], None] | None = None,
    render_heatmap_with_graph: Callable[..., dict[str, Callable[[], None]]],
) -> dict[str, Callable[[], None]]:
    for child in parent.winfo_children():
        child.destroy()

    league_u = str(league or "NHL").upper()
    cache = DiskCache(nhl_dir(SEASON))
    real_today = dt.date.today()
    today = END_DATE
    if league_u == "PWHL":
        pwhl_cache = DiskCache(pwhl_dir(SEASON))
        pwhl_api = PWHLApi(pwhl_cache)
        p_start, p_end = pwhl_api.get_season_boundaries(SEASON_PROBE_DATE, allow_network=True)
        start = p_start or START_DATE
        end = min(today, p_end) if isinstance(p_end, dt.date) else today
        if end < start:
            end = start
        key = f"stats/points_df_pwhl_v2/{SEASON}/{start.isoformat()}_{end.isoformat()}"
        expected_last_col = f"{end.month}/{end.day}"
        # Avoid same-day stale reads: points can change while column labels don't.
        xml_df = read_table_xml(season=SEASON, lump="points_history", league=league_u) if end < real_today else None
        if isinstance(xml_df, pd.DataFrame) and not xml_df.empty and len(xml_df.columns) > 0 and str(xml_df.columns[-1]) == expected_last_col:
            df = xml_df.copy()
            original_order = [str(x) for x in list(df.index)]
        else:
            cached_payload = cache.get_json(key, ttl_s=600) if end < real_today else None
            parsed = _df_from_payload(cached_payload) if isinstance(cached_payload, dict) else None
            if parsed is not None:
                df, original_order = parsed
            else:
                df, original_order = _build_points_df_pwhl(pwhl_api, start, end)
                cache.set_json(key, _df_to_payload(df, original_order))
        return render_heatmap_with_graph(
            parent,
            df,
            tab_key="points",
            tab_title="Points",
            team_colors=team_colors,
            logo_bank=logo_bank,
            original_order=original_order,
            team_col_width=team_col_width,
            cell_width=cell_width,
            get_selected_team_code=get_selected_team_code,
            set_selected_team_code=set_selected_team_code,
            cell_height=22,
            graph_pad_y=12,
            hscroll_units=1,
            start_date=start,
            value_kind="number",
            stats_league=league_u if league_u in {"NHL", "PWHL"} else "NHL",
        )

    api = NHLApi(cache)
    try:
        bounds = api.get_season_boundaries(SEASON_PROBE_DATE)
    except Exception:
        bounds = None

    start, end = _nhl_phase_bounds(bounds, "Regular Season", season_start=START_DATE, season_end=today)
    key = f"stats/points_df_nhl_v2/{SEASON}/{_phase_cache_token('Regular Season')}/{start.isoformat()}_{end.isoformat()}"
    expected_last_col = f"{end.month}/{end.day}"
    xml_df = read_table_xml(
        season=SEASON,
        lump="points_history",
        league=league_u,
        phase="Regular Season",
    ) if end < real_today else None
    if isinstance(xml_df, pd.DataFrame) and not xml_df.empty and len(xml_df.columns) > 0 and str(xml_df.columns[-1]) == expected_last_col:
        df = xml_df.copy()
        original_order = [str(x) for x in list(df.index)]
    else:
        cached_payload = cache.get_json(key, ttl_s=600) if end < real_today else None
        parsed = _df_from_payload(cached_payload) if isinstance(cached_payload, dict) else None
        if parsed is not None:
            df, original_order = parsed
        else:
            df, original_order = _build_points_df(api, start, end, phase="Regular Season")
            cache.set_json(key, _df_to_payload(df, original_order))
    try:
        write_table_xml(
            season=SEASON,
            lump="points_history",
            league=league_u,
            start=start,
            end=end,
            df=df,
            phase="Regular Season",
        )
    except Exception:
        pass

    def _render_regular() -> dict[str, Callable[[], None]]:
        return render_heatmap_with_graph(
            parent,
            df,
            tab_key="points",
            tab_title="Points",
            team_colors=team_colors,
            logo_bank=logo_bank,
            original_order=original_order,
            team_col_width=team_col_width,
            cell_width=cell_width,
            get_selected_team_code=get_selected_team_code,
            set_selected_team_code=set_selected_team_code,
            cell_height=22,
            graph_pad_y=12,
            hscroll_units=1,
            start_date=start,
            value_kind="number",
            stats_league=league_u,
        )

    ctrl_ref = _render_regular()

    def redraw() -> None:
        nonlocal df, original_order, ctrl_ref
        cached_payload = cache.get_json(key, ttl_s=600) if end < real_today else None
        parsed = _df_from_payload(cached_payload) if isinstance(cached_payload, dict) else None
        if parsed is not None:
            df, original_order = parsed
        else:
            df, original_order = _build_points_df(api, start, end, phase="Regular Season")
            cache.set_json(key, _df_to_payload(df, original_order))
        try:
            write_table_xml(
                season=SEASON,
                lump="points_history",
                league=league_u,
                start=start,
                end=end,
                df=df,
                phase="Regular Season",
            )
        except Exception:
            pass
        ctrl_ref = _render_regular()

    def reset() -> None:
        redraw()

    return {"redraw": redraw, "reset": reset}
