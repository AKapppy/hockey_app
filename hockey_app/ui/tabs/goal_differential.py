from __future__ import annotations

import datetime as dt
from typing import Any, Callable, Dict

import pandas as pd

from hockey_app.config import END_DATE, SEASON, SEASON_PROBE_DATE, START_DATE, TEAM_NAMES, canon_team_code
from hockey_app.data.cache import DiskCache
from hockey_app.data.nhl_api import NHLApi
from hockey_app.data.pwhl_api import PWHLApi
from hockey_app.data.paths import nhl_dir, pwhl_dir
from hockey_app.data.xml_cache import read_table_xml, write_table_xml


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
    else:
        api = NHLApi(cache)
        try:
            bounds = api.get_season_boundaries(SEASON_PROBE_DATE)
        except Exception:
            bounds = None

        start = START_DATE
        if bounds is not None and bounds.regular_start is not None:
            start = bounds.regular_start
        end = today
        if bounds is not None and bounds.last_scheduled_game is not None:
            end = min(end, bounds.last_scheduled_game)
        if end < start:
            end = start

        key = f"stats/goal_diff_df_nhl/{SEASON}/{start.isoformat()}_{end.isoformat()}"
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
                df, original_order = _build_goal_diff_df(api, start, end)
                cache.set_json(key, _df_to_payload(df, original_order))

    try:
        write_table_xml(
            season=SEASON,
            lump="goal_differential",
            league=league_u,
            start=start,
            end=end,
            df=df,
        )
    except Exception:
        pass

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
