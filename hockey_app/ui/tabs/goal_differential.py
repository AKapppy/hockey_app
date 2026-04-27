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
from hockey_app.data.xml_cache import read_table_xml, write_table_xml


NHL_PHASE_CHOICES = ["Preseason", "Regular Season", "Postseason"]


def _normalize_nhl_phase_name(value: str) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"preseason", "pre-season", "pre"}:
        return "Preseason"
    if raw in {"postseason", "post-season", "playoffs", "playoff", "post"}:
        return "Postseason"
    return "Regular Season"


def _phase_cache_token(value: str) -> str:
    return _normalize_nhl_phase_name(value).lower().replace(" ", "_")


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


def _build_goal_diff_df(api: NHLApi, start: dt.date, end: dt.date) -> tuple[pd.DataFrame, list[str]]:
    teams = [canon_team_code(c) for c in TEAM_NAMES.keys()]
    teams = sorted(set(teams), key=lambda c: (TEAM_NAMES.get(c, c), c))
    gf: Dict[str, int] = {t: 0 for t in teams}
    ga: Dict[str, int] = {t: 0 for t in teams}

    by_col: dict[str, list[float]] = {}
    seen_games: set[int] = set()

    def _load_day_games(d: dt.date) -> list[dict[str, Any]]:
        iso = d.isoformat()
        for key in (f"nhl/score/final/{iso}", f"nhl/score/live/{iso}"):
            try:
                hit = api.cache.get_json(key, ttl_s=None)  # type: ignore[attr-defined]
            except Exception:
                hit = None
            if isinstance(hit, dict):
                return list((hit.get("games") or []))
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
            if not _is_final(g):
                continue

            away = g.get("awayTeam") or {}
            home = g.get("homeTeam") or {}
            ac = _team_code(away)
            hc = _team_code(home)
            if ac not in gf or hc not in gf:
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

            gf[ac] += ascore
            ga[ac] += hscore
            gf[hc] += hscore
            ga[hc] += ascore

            if gid:
                seen_games.add(gid)

        by_col[col] = [float(gf[t] - ga[t]) for t in teams]

    df = pd.DataFrame(by_col, index=teams, dtype="float64")
    return df, teams


PWHL_TEAMS: list[str] = ["BOS", "MIN", "MTL", "NY", "OTT", "TOR", "VAN", "SEA"]


def _build_goal_diff_df_pwhl(api: PWHLApi, start: dt.date, end: dt.date) -> tuple[pd.DataFrame, list[str]]:
    teams = list(PWHL_TEAMS)
    gf: Dict[str, int] = {t: 0 for t in teams}
    ga: Dict[str, int] = {t: 0 for t in teams}

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
            if ac not in gf or hc not in gf:
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

            gf[ac] += ascore
            ga[ac] += hscore
            gf[hc] += hscore
            ga[hc] += ascore

            if gid:
                seen_games.add(gid)

        by_col[col] = [float(gf[t] - ga[t]) for t in teams]

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


def _phase_visible_goal_diff_df(df: pd.DataFrame, *, phase_name: str) -> tuple[pd.DataFrame, list[str]]:
    if _normalize_nhl_phase_name(phase_name) != "Postseason" or not isinstance(df, pd.DataFrame) or df.empty:
        return df, [str(x) for x in list(df.index)]
    numeric = df.apply(pd.to_numeric, errors="coerce").fillna(0.0)
    keep_mask = numeric.abs().sum(axis=1) > 1e-9
    filtered = df.loc[keep_mask].copy()
    if not filtered.empty:
        return filtered, [str(x) for x in list(filtered.index)]
    return df, [str(x) for x in list(df.index)]


def populate_goal_differential_tab(
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
        key = f"stats/goal_diff_df_pwhl_v2/{SEASON}/{start.isoformat()}_{end.isoformat()}"
        expected_last_col = f"{end.month}/{end.day}"
        xml_df = read_table_xml(season=SEASON, lump="goal_differential", league=league_u)
        if isinstance(xml_df, pd.DataFrame) and not xml_df.empty and len(xml_df.columns) > 0 and str(xml_df.columns[-1]) == expected_last_col:
            df = xml_df.copy()
            original_order = [str(x) for x in list(df.index)]
        else:
            cached_payload = cache.get_json(key, ttl_s=600) if end < real_today else None
            parsed = _df_from_payload(cached_payload) if isinstance(cached_payload, dict) else None
            if parsed is not None:
                df, original_order = parsed
            else:
                df, original_order = _build_goal_diff_df_pwhl(pwhl_api, start, end)
                cache.set_json(key, _df_to_payload(df, original_order))
        return render_heatmap_with_graph(
            parent,
            df,
            tab_key="goal_differential",
            tab_title="Goal Differential",
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
            allow_negative_values=True,
            stats_league=league_u if league_u in {"NHL", "PWHL"} else "NHL",
        )

    api = NHLApi(cache)
    try:
        bounds = api.get_season_boundaries(SEASON_PROBE_DATE)
    except Exception:
        bounds = None

    bg = "#262626"
    parent.configure(bg=bg)
    top = tk.Frame(parent, bg=bg)
    top.pack(fill="x", padx=12, pady=(8, 4))
    phase_var = tk.StringVar(value="Regular Season")
    phase_bar = tk.Frame(top, bg=bg)
    phase_bar.pack(side="left", anchor="w")
    phase_btns: dict[str, tk.Label] = {}
    for i, phase_name in enumerate(NHL_PHASE_CHOICES):
        btn = tk.Label(
            phase_bar,
            text=phase_name,
            padx=10,
            pady=5,
            cursor="hand2",
            bg="#2f2f2f",
            fg="#f0f0f0",
        )
        btn.pack(side="left", padx=(0 if i == 0 else 8, 0))
        phase_btns[phase_name] = btn
    body = tk.Frame(parent, bg=bg)
    body.pack(fill="both", expand=True)
    ctrl_ref: dict[str, dict[str, Callable[[], None]]] = {}

    def _load_phase_df(phase_name: str) -> tuple[pd.DataFrame, list[str], dt.date, dt.date]:
        start, end = _nhl_phase_bounds(bounds, phase_name, season_start=START_DATE, season_end=today)
        key = f"stats/goal_diff_df_nhl_v2/{SEASON}/{_phase_cache_token(phase_name)}/{start.isoformat()}_{end.isoformat()}"
        expected_last_col = f"{end.month}/{end.day}"
        xml_df = read_table_xml(
            season=SEASON,
            lump="goal_differential",
            league=league_u,
            phase=phase_name,
        ) if end < real_today else None
        if isinstance(xml_df, pd.DataFrame) and not xml_df.empty and len(xml_df.columns) > 0 and str(xml_df.columns[-1]) == expected_last_col:
            df_local = xml_df.copy()
            original_local = [str(x) for x in list(df_local.index)]
        else:
            cached_payload = cache.get_json(key, ttl_s=600) if end < real_today else None
            parsed = _df_from_payload(cached_payload) if isinstance(cached_payload, dict) else None
            if parsed is not None:
                df_local, original_local = parsed
            else:
                df_local, original_local = _build_goal_diff_df(api, start, end)
                cache.set_json(key, _df_to_payload(df_local, original_local))
        try:
            write_table_xml(
                season=SEASON,
                lump="goal_differential",
                league=league_u,
                start=start,
                end=end,
                df=df_local,
                phase=phase_name,
            )
        except Exception:
            pass
        return df_local, original_local, start, end

    def _render_phase() -> None:
        phase_name = _normalize_nhl_phase_name(phase_var.get())
        for choice, btn in phase_btns.items():
            btn.configure(bg="#3a3a3a" if choice == phase_name else "#2f2f2f", fg="#f0f0f0")
        df_local, original_local, start, _end = _load_phase_df(phase_name)
        df_local, original_local = _phase_visible_goal_diff_df(df_local, phase_name=phase_name)
        ctrl_ref["inner"] = render_heatmap_with_graph(
            body,
            df_local,
            tab_key="goal_differential",
            tab_title="Goal Differential",
            team_colors=team_colors,
            logo_bank=logo_bank,
            original_order=original_local,
            team_col_width=team_col_width,
            cell_width=cell_width,
            get_selected_team_code=get_selected_team_code,
            set_selected_team_code=set_selected_team_code,
            cell_height=22,
            graph_pad_y=12,
            hscroll_units=1,
            start_date=start,
            value_kind="number",
            allow_negative_values=True,
            stats_league=league_u,
        )

    def _set_phase(phase_name: str) -> None:
        phase_name = _normalize_nhl_phase_name(phase_name)
        if phase_var.get() != phase_name:
            phase_var.set(phase_name)
            return
        _render_phase()

    for phase_name, btn in phase_btns.items():
        btn.bind("<Button-1>", lambda _e, ph=phase_name: _set_phase(ph), add="+")

    phase_var.trace_add("write", lambda *_: _render_phase())
    _render_phase()

    def redraw() -> None:
        _render_phase()

    def reset() -> None:
        if phase_var.get() != "Regular Season":
            phase_var.set("Regular Season")
        else:
            _render_phase()

    return {"redraw": redraw, "reset": reset}
