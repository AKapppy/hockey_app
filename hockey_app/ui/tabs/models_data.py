from __future__ import annotations

import datetime as dt
from typing import Any

import pandas as pd

from hockey_app.config import END_DATE, SEASON, SEASON_PROBE_DATE, START_DATE, TEAM_NAMES, canon_team_code
from hockey_app.data.cache import DiskCache
from hockey_app.data.nhl_api import NHLApi
from hockey_app.data.pwhl_api import PWHLApi
from hockey_app.data.paths import nhl_dir, pwhl_dir
from hockey_app.data.xml_cache import read_table_xml, write_table_xml
from hockey_app.ui.tabs.points import _build_points_df, _build_points_df_pwhl

PWHL_TEAM_NAMES: dict[str, str] = {
    "BOS": "Boston Fleet",
    "MIN": "Minnesota Frost",
    "MTL": "Montreal Victoire",
    "NY": "New York Sirens",
    "OTT": "Ottawa Charge",
    "TOR": "Toronto Sceptres",
    "VAN": "Vancouver Goldeneyes",
    "SEA": "Seattle Torrent",
}


def load_points_history(league: str = "NHL") -> tuple[pd.DataFrame, dt.date, dt.date]:
    league_u = str(league or "NHL").upper()
    real_today = dt.date.today()
    today = END_DATE
    cache = DiskCache(nhl_dir(SEASON))
    if league_u == "PWHL":
        pwhl_cache = DiskCache(pwhl_dir(SEASON))
        pwhl_api = PWHLApi(pwhl_cache)
        try:
            p0, p1 = pwhl_api.get_season_boundaries(SEASON_PROBE_DATE, allow_network=True)
            d0 = p0 or START_DATE
            d1 = min(today, p1) if isinstance(p1, dt.date) else today
        except Exception:
            d0, d1 = START_DATE, today
        if d1 < d0:
            d1 = d0
        key = f"stats/points_df_pwhl_models/{SEASON}/{d0.isoformat()}_{d1.isoformat()}"
    else:
        api = NHLApi(cache)
        try:
            bounds = api.get_season_boundaries(SEASON_PROBE_DATE)
            d0 = bounds.regular_start or START_DATE
            d1 = min(today, bounds.last_scheduled_game or today)
        except Exception:
            d0, d1 = START_DATE, today
        if d1 < d0:
            d1 = d0
        key = f"stats/points_df_nhl/{SEASON}/{d0.isoformat()}_{d1.isoformat()}"

    expected_last_col = f"{d1.month}/{d1.day}"
    # Avoid same-day stale reads: values can change without a new column label.
    df = read_table_xml(season=SEASON, lump="points_history", league=league_u) if d1 < real_today else None
    if df is not None and (df.empty or len(df.columns) == 0 or str(df.columns[-1]) != expected_last_col):
        df = None
    if df is None and d1 < real_today:
        payload = cache.get_json(key, ttl_s=600)
        if isinstance(payload, dict):
            try:
                df = pd.DataFrame(
                    payload.get("data") or [],
                    index=[str(x) for x in (payload.get("index") or [])],
                    columns=[str(c) for c in (payload.get("columns") or [])],
                    dtype="float64",
                )
            except Exception:
                df = None
    if df is not None and (df.empty or len(df.columns) == 0 or str(df.columns[-1]) != expected_last_col):
        df = None
    if df is None or df.empty or len(df.columns) == 0:
        if league_u == "PWHL":
            pwhl_cache = DiskCache(pwhl_dir(SEASON))
            pwhl_api = PWHLApi(pwhl_cache)
            df, _ = _build_points_df_pwhl(pwhl_api, d0, d1)
        else:
            api = NHLApi(cache)
            df, _ = _build_points_df(api, d0, d1)
        if not df.empty and len(df.columns) > 0:
            try:
                cache.set_json(
                    key,
                    {
                        "index": [str(x) for x in df.index],
                        "columns": [str(c) for c in df.columns],
                        "data": [[None if pd.isna(v) else float(v) for v in row] for row in df.to_numpy()],
                    },
                )
            except Exception:
                # Cache writes can fail on locked or read-only app-support paths.
                # Continue with in-memory data so model tabs remain usable.
                pass

    # Keep stable team order.
    idx = [canon_team_code(str(i)) for i in df.index]
    df.index = idx
    df = df[~df.index.duplicated(keep="first")]
    if league_u == "PWHL":
        pwhl_order = ["BOS", "MIN", "MTL", "NY", "OTT", "TOR", "VAN", "SEA"]
        keep = [c for c in pwhl_order if c in set(df.index)]
    else:
        keep = [c for c in sorted(set(TEAM_NAMES.keys())) if c in set(df.index)]
    if keep:
        df = df.loc[keep]
    try:
        write_table_xml(
            season=SEASON,
            lump="points_history",
            league=league_u,
            start=d0,
            end=d1,
            df=df,
        )
    except Exception:
        pass
    return df, d0, d1


def points_snapshot(df: pd.DataFrame, day: dt.date) -> dict[str, float]:
    if df.empty or len(df.columns) == 0:
        return {}
    col = f"{day.month}/{day.day}"
    if col not in df.columns:
        col = str(df.columns[-1])
    s = pd.to_numeric(df[col], errors="coerce")
    return {str(i): float(s.loc[i]) for i in s.index if not pd.isna(s.loc[i])}


def regular_season_reference_day(day: dt.date, *, league: str = "NHL") -> dt.date:
    league_u = str(league or "NHL").upper()
    if league_u != "NHL":
        return day
    cache = DiskCache(nhl_dir(SEASON))
    api = NHLApi(cache)
    try:
        bounds = api.get_season_boundaries(day)
    except Exception:
        return day
    regular_end = bounds.regular_end
    if isinstance(regular_end, dt.date) and day > regular_end:
        return regular_end
    return day


def standings_tiebreak_snapshot(day: dt.date) -> dict[str, dict[str, Any]]:
    """
    Per-team standings metadata used for official tiebreak-aware ordering.
    """
    cache = DiskCache(nhl_dir(SEASON))
    api = NHLApi(cache)
    key = f"nhl/standings/{day.isoformat()}"
    payload = cache.get_json(key, ttl_s=(120 if day >= dt.date.today() else None))
    if not isinstance(payload, dict):
        try:
            payload = api.standings(day, force_network=False)
        except Exception:
            payload = {}
    rows = payload.get("standings") if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        return {}

    def _to_int(v: Any, default: int = 0) -> int:
        try:
            return int(v)
        except Exception:
            try:
                return int(float(v))
            except Exception:
                return int(default)

    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        team_obj = row.get("teamAbbrev")
        if isinstance(team_obj, dict):
            code_raw = str(team_obj.get("default") or "").strip().upper()
        else:
            code_raw = str(team_obj or "").strip().upper()
        code = canon_team_code(code_raw)
        if not code:
            continue
        out[code] = {
            "conference": str(row.get("conferenceAbbrev") or "").strip(),
            "division": str(row.get("divisionAbbrev") or "").strip(),
            "conferenceSequence": _to_int(row.get("conferenceSequence"), 999),
            "divisionSequence": _to_int(row.get("divisionSequence"), 999),
            "wildcardSequence": _to_int(row.get("wildcardSequence"), 999),
            "leagueSequence": _to_int(row.get("leagueSequence"), 999),
            "points": float(row.get("points") or 0.0),
            "row": _to_int(row.get("regulationPlusOtWins"), 0),
            "rw": _to_int(row.get("regulationWins"), 0),
        }
    return out


def games_played_snapshot(day: dt.date, *, league: str = "NHL") -> dict[str, int]:
    """
    Accurate GP snapshot from cached/fetched daily scorecards up to `day`.
    Counts both teams for every completed game.
    """
    league_u = str(league or "NHL").upper()
    if league_u == "PWHL":
        pwhl_cache = DiskCache(pwhl_dir(SEASON))
        pwhl_api = PWHLApi(pwhl_cache)
        teams = sorted(PWHL_TEAM_NAMES.keys())
        gp: dict[str, int] = {t: 0 for t in teams}

        def _norm_code(v: Any) -> str:
            code = str(v or "").strip().upper()
            return {"MON": "MTL", "NYC": "NY"}.get(code, code)

        def _is_final(g: dict[str, Any]) -> bool:
            s = str(g.get("gameState") or g.get("gameStatus") or "").upper()
            return s in {"FINAL", "OFF"} or s.startswith("FINAL")

        start = START_DATE
        try:
            s0, _s1 = pwhl_api.get_season_boundaries(day, allow_network=True)
            if isinstance(s0, dt.date):
                start = s0
        except Exception:
            pass
        if day < start:
            day = start

        seen_games: set[int] = set()
        cur = start
        while cur <= day:
            try:
                games = pwhl_api.get_games_for_date(cur, allow_network=True)
            except Exception:
                games = []
            for g in games:
                if not isinstance(g, dict) or not _is_final(g):
                    continue
                gid = int(g.get("id") or g.get("gameId") or 0)
                if gid and gid in seen_games:
                    continue
                away = g.get("awayTeam") if isinstance(g.get("awayTeam"), dict) else {}
                home = g.get("homeTeam") if isinstance(g.get("homeTeam"), dict) else {}
                ac = _norm_code(away.get("abbrev") or away.get("abbreviation") or away.get("teamAbbrev"))
                hc = _norm_code(home.get("abbrev") or home.get("abbreviation") or home.get("teamAbbrev"))
                if ac in gp:
                    gp[ac] += 1
                if hc in gp:
                    gp[hc] += 1
                if gid:
                    seen_games.add(gid)
            cur += dt.timedelta(days=1)
        return gp

    cache = DiskCache(nhl_dir(SEASON))
    api = NHLApi(cache)
    today = dt.date.today()

    start = START_DATE
    try:
        bounds = api.get_season_boundaries(day)
        if bounds.regular_start is not None:
            start = bounds.regular_start
    except Exception:
        pass
    if day < start:
        day = start

    teams = [canon_team_code(c) for c in TEAM_NAMES.keys()]
    gp: dict[str, int] = {t: 0 for t in sorted(set(teams))}

    def _is_final(g: dict[str, Any]) -> bool:
        s = str(g.get("gameState") or g.get("gameStatus") or "").upper()
        return s in {"FINAL", "OFF"} or s.startswith("FINAL")

    def _team_code(team_obj: dict[str, Any]) -> str:
        raw = team_obj.get("abbrev") or team_obj.get("abbreviation") or team_obj.get("teamAbbrev") or ""
        return canon_team_code(str(raw).upper())

    def _load_day_games(d: dt.date) -> list[dict[str, Any]]:
        iso = d.isoformat()
        final_hit = cache.get_json(f"nhl/score/final/{iso}", ttl_s=None)
        if isinstance(final_hit, dict):
            return list(final_hit.get("games") or [])

        live_hit = cache.get_json(f"nhl/score/live/{iso}", ttl_s=None)
        if isinstance(live_hit, dict):
            live_games = list(live_hit.get("games") or [])
            # If a past-day live cache is stale, force one refresh.
            if d < today and live_games and any(not _is_final(g) for g in live_games):
                try:
                    fresh = api.score(d, force_network=True) or {}
                    return list(fresh.get("games") or [])
                except Exception:
                    pass
            return live_games
        try:
            return list((api.score(d) or {}).get("games") or [])
        except Exception:
            return []

    seen_games: set[int] = set()
    cur = start
    while cur <= day:
        for g in _load_day_games(cur):
            gid = int(g.get("id") or g.get("gameId") or 0)
            if gid and gid in seen_games:
                continue
            if not _is_final(g):
                continue
            away = g.get("awayTeam") or {}
            home = g.get("homeTeam") or {}
            ac = _team_code(away)
            hc = _team_code(home)
            if ac in gp:
                gp[ac] += 1
            if hc in gp:
                gp[hc] += 1
            if gid:
                seen_games.add(gid)
        cur += dt.timedelta(days=1)
    return gp


def games_played_from_points(points: float, p_per_game: float = 1.15) -> int:
    # Homebrew approximation: infer GP from points pace if direct GP table unavailable.
    # Bounded by NHL season length.
    if p_per_game <= 0:
        p_per_game = 1.15
    gp = int(round(float(points) / p_per_game))
    return max(0, min(82, gp))
