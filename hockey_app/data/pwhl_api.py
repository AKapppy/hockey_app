from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
import unicodedata
from typing import Any, Optional

import requests

from .. import config as cfg
from .cache import DiskCache


_JSONP_RE = re.compile(r"^[^(]*\((.*)\)\s*;?\s*$", re.DOTALL)


class PWHLApi:
    """
    Cached best-effort client for public PWHL data feeds (HockeyTech/LeagueStat).
    Returns normalized game dicts compatible with the Games tab renderer.
    """

    def __init__(self, cache: DiskCache) -> None:
        self.cache = cache
        self.base_url = "https://lscluster.hockeytech.com/feed/index.php"
        self.headers: dict[str, str] = getattr(
            cfg,
            "HEADERS",
            {"User-Agent": "hockey_app/1.0 (+https://lscluster.hockeytech.com)"},
        )
        self.timeout_s: int = int(getattr(cfg, "REQUEST_TIMEOUT_S", 20))
        self.key_modulekit = "446521baf8c38984"
        self.key_statview = "694cfeed58c932ee"
        self.debug_enabled = str(os.environ.get("HOCKEY_DEBUG_PWHL", "")).strip().lower() in {"1", "true", "yes", "on"}
        self.debug_date = str(os.environ.get("HOCKEY_DEBUG_PWHL_DATE", "")).strip()

    def _dbg(self, msg: str, *, d: Optional[dt.date] = None) -> None:
        if not self.debug_enabled:
            return
        if self.debug_date and d is not None and self.debug_date != d.isoformat():
            return
        print(f"[PWHL DEBUG] {msg}", file=sys.stderr)

    def _loads_any(self, text: str) -> Any:
        s = text.strip()
        try:
            return json.loads(s)
        except Exception:
            pass
        m = _JSONP_RE.match(s)
        if m:
            return json.loads(m.group(1))
        return {}

    def _extract_schedule_rows(self, raw: Any) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        seen_ids: set[int] = set()

        row_markers = {
            "date",
            "game_date",
            "date_played",
            "date_with_day",
            "game_datetime",
            "start_datetime",
            "start_time_utc",
            "start_time",
            "away_team_name",
            "home_team_name",
            "visiting_team_city",
            "home_team_city",
            "game_id",
            "game_number",
        }

        def _normalize_obj(obj: dict[str, Any]) -> dict[str, Any]:
            # HockeyTech schedule rows commonly come as:
            # {"row": {...fields...}, "prop": {...metadata...}}
            # Flatten row values so downstream parsing sees stable keys.
            row = obj.get("row")
            if isinstance(row, dict):
                flat = dict(row)
                prop = obj.get("prop")
                if isinstance(prop, dict):
                    for k, v in prop.items():
                        if k not in flat:
                            flat[k] = v
                return flat
            return obj

        def _visit(obj: Any, depth: int = 0) -> None:
            if depth > 7:
                return
            if isinstance(obj, list):
                for it in obj:
                    _visit(it, depth + 1)
                return
            if not isinstance(obj, dict):
                return

            oid = id(obj)
            if oid in seen_ids:
                return
            seen_ids.add(oid)

            obj_n = _normalize_obj(obj)
            keys = set(obj_n.keys())
            if keys & row_markers:
                out.append(obj_n)

            for k in ("sections", "data", "rows", "items", "games", "schedule", "SiteKit"):
                if k in obj:
                    _visit(obj.get(k), depth + 1)

            # Some feeds store rows in dict-valued maps keyed by ID.
            for v in obj.values():
                if isinstance(v, dict):
                    _visit(v, depth + 1)
                elif isinstance(v, list):
                    _visit(v, depth + 1)

        _visit(raw)
        return out

    def _get_json_with_meta(
        self,
        key: str,
        params: dict[str, str],
        ttl_s: Optional[int],
        *,
        allow_network: bool,
        force_network: bool = False,
    ) -> tuple[dict[str, Any], Optional[float], str]:
        # When network is disallowed, treat cache as authoritative regardless of TTL.
        read_ttl = (-1 if (allow_network and force_network) else (ttl_s if allow_network else None))
        cached, ts = self.cache.get_json_with_meta(key, ttl_s=read_ttl)
        if isinstance(cached, dict):
            return cached, ts, "cache"
        if not allow_network:
            return {}, ts, "empty"

        r = requests.get(self.base_url, params=params, headers=self.headers, timeout=self.timeout_s)
        r.raise_for_status()
        data = self._loads_any(r.text)
        if isinstance(data, list):
            # Some HockeyTech views return a top-level array.
            data = {"data": data}
        if isinstance(data, dict):
            self.cache.set_json(key, data)
            cached2, ts2 = self.cache.get_json_with_meta(key, ttl_s=None)
            if isinstance(cached2, dict):
                return cached2, ts2, "network"
            return data, ts2, "network"
        self._dbg(f"non-dict payload type={type(data).__name__} head={r.text[:160]!r}")
        return {}, ts, "empty"

    def _get_json(
        self,
        key: str,
        params: dict[str, str],
        ttl_s: Optional[int],
        *,
        allow_network: bool,
        force_network: bool = False,
    ) -> dict[str, Any]:
        data, _ts, _src = self._get_json_with_meta(
            key,
            params,
            ttl_s,
            allow_network=allow_network,
            force_network=force_network,
        )
        return data

    def _season_year_end(self, d: dt.date) -> int:
        # PWHL season spans years similar to NHL.
        return d.year + 1 if d.month >= 7 else d.year

    def _parse_row_date(self, v: Any) -> Optional[dt.date]:
        s = str(v or "").strip()
        if not s:
            return None
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d"):
            try:
                return dt.datetime.strptime(s, fmt).date()
            except Exception:
                continue
        try:
            return dt.date.fromisoformat(s[:10])
        except Exception:
            return None

    def _season_candidates(self, *, allow_network: bool, force_network: bool = False) -> list[dict[str, Any]]:
        key = "pwhl/seasons"
        params = {
            "feed": "modulekit",
            "view": "seasons",
            "client_code": "pwhl",
            "key": self.key_modulekit,
        }
        raw = self._get_json(
            key,
            params,
            ttl_s=7 * 24 * 3600,
            allow_network=allow_network,
            force_network=force_network,
        )
        out: list[dict[str, Any]] = []
        sitekit = raw.get("SiteKit") if isinstance(raw, dict) else None
        data_rows = (
            raw.get("data")
            or raw.get("seasons")
            or (sitekit.get("Seasons") if isinstance(sitekit, dict) else [])
            or []
        )
        if isinstance(data_rows, list):
            for row in data_rows:
                if not isinstance(row, dict):
                    continue
                sid = str(row.get("season_id") or row.get("id") or "").strip()
                lab = str(
                    row.get("name")
                    or row.get("season_name")
                    or row.get("season_yr")
                    or row.get("shortname")
                    or ""
                ).strip()
                start_d = self._parse_row_date(row.get("start_date") or row.get("startDate"))
                end_d = self._parse_row_date(row.get("end_date") or row.get("endDate"))
                if sid:
                    out.append({"id": sid, "label": lab, "start": start_d, "end": end_d})
        return out

    def _select_season(self, candidates: list[dict[str, Any]], d: dt.date) -> Optional[dict[str, Any]]:
        if not candidates:
            return None

        # Prefer an explicit date-range match when available.
        range_hits: list[dict[str, Any]] = []
        for c in candidates:
            sd = c.get("start")
            ed = c.get("end")
            if isinstance(sd, dt.date) and isinstance(ed, dt.date) and sd <= d <= ed:
                range_hits.append(c)
        if range_hits:
            # Choose the narrowest containing span (most specific season bucket).
            range_hits.sort(
                key=lambda c: (
                    ((c["end"] - c["start"]).days if isinstance(c.get("start"), dt.date) and isinstance(c.get("end"), dt.date) else 10**9),
                    -int(c["id"]) if str(c.get("id", "")).isdigit() else 0,
                )
            )
            return range_hits[0]

        want = str(self._season_year_end(d))
        want_prev = str(self._season_year_end(d) - 1)
        for c in candidates:
            lab = str(c.get("label") or "")
            # Handle season labels that include one or both year values.
            if (want in lab) or (want_prev in lab and want[-2:] in lab):
                return c

        # Last resort: highest numeric id (newest season entry).
        numeric = [c for c in candidates if str(c.get("id", "")).isdigit()]
        if numeric:
            numeric.sort(key=lambda c: int(str(c["id"])), reverse=True)
            return numeric[0]
        return candidates[0]

    def _pick_season_id(self, d: dt.date, *, allow_network: bool, force_network: bool = False) -> Optional[str]:
        candidates = self._season_candidates(allow_network=allow_network, force_network=force_network)
        if not candidates:
            return None
        self._dbg(f"season candidates={[(c['id'], c['label'], c.get('start'), c.get('end')) for c in candidates]}", d=d)
        chosen = self._select_season(candidates, d)
        if not chosen:
            return None
        pick = str(chosen.get("id") or "").strip()
        if pick:
            self._dbg(f"season picked: {pick}", d=d)
            return pick
        return None

    def get_season_boundaries(
        self,
        probe_date: Optional[dt.date] = None,
        *,
        allow_network: bool,
        force_network: bool = False,
    ) -> tuple[Optional[dt.date], Optional[dt.date]]:
        d = probe_date or dt.date.today()
        candidates = self._season_candidates(allow_network=allow_network, force_network=force_network)
        if not candidates:
            return None, None
        chosen = self._select_season(candidates, d)
        if chosen is not None:
            return chosen.get("start"), chosen.get("end")
        starts: list[dt.date] = []
        ends: list[dt.date] = []
        for c in candidates:
            s = c.get("start")
            e = c.get("end")
            if isinstance(s, dt.date):
                starts.append(s)
            if isinstance(e, dt.date):
                ends.append(e)
        return (min(starts) if starts else None, max(ends) if ends else None)

    def _parse_date(self, s: str) -> Optional[dt.date]:
        t = str(s or "").strip()
        if not t:
            return None
        # strip lightweight HTML and normalize spaces
        t = re.sub(r"<[^>]+>", " ", t)
        t = re.sub(r"\s+", " ", t).strip()

        # fast path for ISO date embedded in larger strings
        m = re.search(r"(\d{4}-\d{2}-\d{2})", t)
        if m:
            try:
                return dt.date.fromisoformat(m.group(1))
            except Exception:
                pass

        for fmt in (
            "%Y-%m-%d",
            "%m/%d/%Y",
            "%Y/%m/%d",
            "%a %b %d %Y",
            "%A %B %d %Y",
            "%b %d, %Y",
            "%B %d, %Y",
            "%a, %b %d, %Y",
            "%m/%d/%y",
        ):
            try:
                return dt.datetime.strptime(t, fmt).date()
            except Exception:
                continue
        try:
            return dt.datetime.fromisoformat(t.replace("Z", "+00:00")).date()
        except Exception:
            return None

    def _parse_month_day(self, s: str) -> Optional[tuple[int, int]]:
        t = str(s or "").strip()
        if not t:
            return None
        t = re.sub(r"<[^>]+>", " ", t)
        t = re.sub(r"\s+", " ", t).strip()
        # Locale-independent parse for values like:
        # "Wed, Jan 28", "January 28", "Jan 28 7:00 PM ET"
        month_map = {
            "jan": 1,
            "january": 1,
            "feb": 2,
            "february": 2,
            "mar": 3,
            "march": 3,
            "apr": 4,
            "april": 4,
            "may": 5,
            "jun": 6,
            "june": 6,
            "jul": 7,
            "july": 7,
            "aug": 8,
            "august": 8,
            "sep": 9,
            "sept": 9,
            "september": 9,
            "oct": 10,
            "october": 10,
            "nov": 11,
            "november": 11,
            "dec": 12,
            "december": 12,
        }
        m = re.search(
            r"\b("
            r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|"
            r"jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|"
            r"oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
            r")\b\.?\s+(\d{1,2})\b",
            t,
            flags=re.IGNORECASE,
        )
        if m:
            mon_txt = str(m.group(1)).lower().rstrip(".")
            day = int(m.group(2))
            mon = month_map.get(mon_txt)
            if mon is not None and 1 <= day <= 31:
                return mon, day

        for fmt in ("%a, %b %d", "%A, %B %d", "%b %d", "%B %d"):
            try:
                x = dt.datetime.strptime(t, fmt)
                return int(x.month), int(x.day)
            except Exception:
                continue
        return None

    def _code_from_name(self, name: str) -> str:
        n_raw = str(name or "")
        n = n_raw.upper()
        n_ascii = unicodedata.normalize("NFKD", n_raw).encode("ascii", "ignore").decode("ascii").upper()
        lookup = {
            "BOSTON": "BOS",
            "FLEET": "BOS",
            "MINNESOTA": "MIN",
            "FROST": "MIN",
            "MONTREAL": "MTL",
            "MONTRÉAL": "MTL",
            "VICTOIRE": "MTL",
            "NEW YORK": "NY",
            "SIRENS": "NY",
            "OTTAWA": "OTT",
            "CHARGE": "OTT",
            "TORONTO": "TOR",
            "SCEPTRES": "TOR",
            "VANCOUVER": "VAN",
            "SEATTLE": "SEA",
        }
        for k, v in lookup.items():
            if (k in n) or (k in n_ascii):
                return v
        fallback = (n_ascii[:3] if len(n_ascii) >= 3 else "TBD").upper()
        if fallback == "MON":
            return "MTL"
        return fallback

    def _to_int(self, v: Any, default: int = 0) -> int:
        try:
            s = str(v).strip()
            if not s or s == "-":
                return default
            return int(float(s))
        except Exception:
            return default

    def _infer_game_state(self, status_txt: str) -> str:
        s = str(status_txt or "").upper().strip()
        if "FINAL" in s:
            return "FINAL"
        if any(x in s for x in ("LIVE", "IN PROGRESS", "INTERMISSION", "PERIOD")):
            return "LIVE"

        # HockeyTech often reports live rows as "14:04 3RD" instead of using
        # explicit words like "LIVE" or "IN PROGRESS".
        has_clock = bool(re.search(r"\b\d{1,2}:\d{2}\b", s))
        has_period = bool(re.search(r"\b(?:[1-9](?:ST|ND|RD|TH)|P(?:ERIOD)?\s*[1-9]|OT|SO)\b", s))
        has_ampm = bool(re.search(r"\b\d{1,2}:\d{2}\s*[AP]M\b", s))
        if (has_clock and has_period and not has_ampm) or s.startswith("END "):
            return "LIVE"
        return "FUT"

    def get_games_for_date_with_meta(
        self,
        d: dt.date,
        *,
        allow_network: bool,
        force_network: bool = False,
    ) -> tuple[list[dict[str, Any]], Optional[float]]:
        self._dbg(f"start date={d.isoformat()} allow_network={allow_network}", d=d)
        sid = self._pick_season_id(d, allow_network=allow_network, force_network=force_network)
        if not sid:
            self._dbg("no season id resolved", d=d)
            return [], None
        self._dbg(f"season id={sid}", d=d)

        key = f"pwhl/schedule/{sid}"
        params_primary = {
            "feed": "statviewfeed",
            "view": "schedule",
            "team": "-1",
            "season": sid,
            "month": "-1",
            "location": "homeaway",
            "key": self.key_statview,
            "client_code": "pwhl",
            "site_id": "2",
            "league_id": "1",
            "division_id": "-1",
            "lang": "en",
        }
        ttl = 45 if d == dt.date.today() else (None if d < dt.date.today() else 12 * 3600)
        raw, ts, source = self._get_json_with_meta(
            key,
            params_primary,
            ttl_s=ttl,
            allow_network=allow_network,
            force_network=force_network,
        )
        rows = self._extract_schedule_rows(raw)
        self._dbg(f"schedule source={source} cache_ts={ts} raw rows={len(rows)}", d=d)

        if not rows and allow_network:
            fallbacks: list[tuple[str, dict[str, str]]] = [
                (
                    f"{key}/modulekit",
                    {
                        "feed": "modulekit",
                        "view": "schedule",
                        "season": sid,
                        "key": self.key_modulekit,
                        "client_code": "pwhl",
                    },
                ),
                (
                    f"{key}/scoreboard",
                    {
                        "feed": "statviewfeed",
                        "view": "scoreboard",
                        "season": sid,
                        "key": self.key_statview,
                        "client_code": "pwhl",
                        "site_id": "2",
                        "league_id": "1",
                        "lang": "en",
                    },
                ),
                (
                    f"{key}/gamesbydate",
                    {
                        "feed": "statviewfeed",
                        "view": "gamesbydate",
                        "season": sid,
                        "key": self.key_statview,
                        "client_code": "pwhl",
                        "site_id": "2",
                        "league_id": "1",
                        "lang": "en",
                    },
                ),
            ]
            for fkey, fparams in fallbacks:
                try:
                    fraw, fts, fsrc = self._get_json_with_meta(
                        fkey,
                        fparams,
                        ttl_s=ttl,
                        allow_network=True,
                        force_network=force_network,
                    )
                except Exception as e:
                    self._dbg(f"fallback error key={fkey} err={e}", d=d)
                    continue
                frows = self._extract_schedule_rows(fraw)
                self._dbg(f"fallback key={fkey} source={fsrc} rows={len(frows)}", d=d)
                if frows:
                    raw, ts, source, rows = fraw, fts, fsrc, frows
                    break

        out: list[dict[str, Any]] = []
        seen_game_ids: set[int] = set()
        seen_game_keys: set[tuple[str, str, str]] = set()
        skip_not_dict = 0
        skip_date_parse = 0
        skip_wrong_date = 0
        for r in rows:
            if not isinstance(r, dict):
                skip_not_dict += 1
                continue
            # Skip structural/header rows that are not actual games.
            if (
                not r.get("game_id")
                and not r.get("game_number")
                and not r.get("game_status")
                and r.get("home_goal_count") is None
                and r.get("visiting_goal_count") is None
            ):
                skip_not_dict += 1
                continue
            rd = self._parse_date(
                str(
                    r.get("date")
                    or r.get("game_date")
                    or r.get("date_played")
                    or r.get("game_date_iso")
                    or r.get("date_with_day")
                    or ""
                )
            )
            if rd is None:
                # Many HockeyTech rows include a datetime but not a clean date.
                dt_raw = str(
                    r.get("game_datetime")
                    or r.get("start_datetime")
                    or r.get("start_time_utc")
                    or r.get("start_time")
                    or ""
                ).strip()
                rd = self._parse_date(dt_raw[:10] if len(dt_raw) >= 10 else dt_raw)
            if rd is None:
                md = self._parse_month_day(str(r.get("date_with_day") or ""))
                if md is not None:
                    if md == (d.month, d.day):
                        rd = d
                    else:
                        skip_wrong_date += 1
                        continue
            if rd is None:
                skip_date_parse += 1
                self._dbg(f"skip_date_parse row_keys={list(r.keys())[:20]} date_fields="
                          f"{ {k:r.get(k) for k in ['date','game_date','date_played','date_with_day','game_datetime','start_datetime','start_time_utc','start_time']} }", d=d)
                continue
            if rd != d:
                skip_wrong_date += 1
                continue
            away_name = str(
                r.get("away_team_name")
                or r.get("away_team")
                or r.get("visitor_team_name")
                or r.get("visiting_team_city")
                or r.get("visiting_team_name")
                or "Away"
            )
            home_name = str(
                r.get("home_team_name")
                or r.get("home_team")
                or r.get("home_team_city")
                or "Home"
            )
            away_code = str(
                r.get("away_team_code")
                or r.get("away_team_abbr")
                or r.get("visiting_team_abbr")
                or ""
            ) or self._code_from_name(away_name)
            home_code = str(
                r.get("home_team_code")
                or r.get("home_team_abbr")
                or ""
            ) or self._code_from_name(home_name)
            away_score = self._to_int(
                r.get("away_score") or r.get("visitor_score") or r.get("visiting_goal_count") or 0
            )
            home_score = self._to_int(r.get("home_score") or r.get("home_goal_count") or 0)
            away_shots = self._to_int(
                r.get("away_shots")
                or r.get("visitor_shots")
                or r.get("visiting_shots")
                or r.get("away_sog")
                or r.get("visitor_sog")
                or r.get("visiting_sog")
                or "",
                default=-1,
            )
            home_shots = self._to_int(
                r.get("home_shots")
                or r.get("home_sog")
                or "",
                default=-1,
            )
            away_shots_val = away_shots if away_shots >= 0 else None
            home_shots_val = home_shots if home_shots >= 0 else None

            def _scorers_from(value: Any) -> list[dict[str, Any]]:
                vals: list[dict[str, Any]] = []
                if isinstance(value, list):
                    for it in value:
                        nm = str(it.get("name") if isinstance(it, dict) else it).strip()
                        if nm:
                            vals.append({"name": nm})
                    return vals
                s = str(value or "").strip()
                if not s:
                    return vals
                parts = [p.strip() for p in re.split(r"[|,;/]", s) if p.strip()]
                return [{"name": p} for p in parts]

            away_scorers = _scorers_from(
                r.get("away_goal_scorers")
                or r.get("visitor_goal_scorers")
                or r.get("visiting_goal_scorers")
            )
            home_scorers = _scorers_from(r.get("home_goal_scorers"))
            status_txt = str(r.get("game_status") or r.get("status") or r.get("game_status_string") or "").upper().strip()
            state = self._infer_game_state(status_txt)
            start = str(
                r.get("start_time_utc")
                or r.get("game_datetime")
                or r.get("start_datetime")
                or r.get("start_time")
                or ""
            )

            out.append(
                {
                    "id": int(float(r.get("game_id") or r.get("id") or r.get("game_number") or 0)),
                    "gameState": state,
                    "startTimeUTC": start or None,
                    "awayTeam": {
                        "abbrev": away_code.upper(),
                        "score": away_score,
                        "shotsOnGoal": away_shots_val,
                        "goalScorers": away_scorers,
                    },
                    "homeTeam": {
                        "abbrev": home_code.upper(),
                        "score": home_score,
                        "shotsOnGoal": home_shots_val,
                        "goalScorers": home_scorers,
                    },
                    "league": "PWHL",
                    "statusText": status_txt,
                }
            )
            # De-dupe rows that appear both as wrapper and nested row.
            last = out[-1]
            gid = int(last.get("id") or 0)
            if gid > 0:
                if gid in seen_game_ids:
                    out.pop()
                    continue
                seen_game_ids.add(gid)
            else:
                key = (
                    str(last.get("awayTeam", {}).get("abbrev") or ""),
                    str(last.get("homeTeam", {}).get("abbrev") or ""),
                    str(last.get("statusText") or ""),
                )
                if key in seen_game_keys:
                    out.pop()
                    continue
                seen_game_keys.add(key)
        self._dbg(
            f"normalized={len(out)} skipped_not_dict={skip_not_dict} "
            f"skipped_date_parse={skip_date_parse} skipped_wrong_date={skip_wrong_date}",
            d=d,
        )
        if out:
            sample = out[: min(3, len(out))]
            self._dbg(f"sample={sample}", d=d)
        return out, ts

    def get_games_for_date(
        self,
        d: dt.date,
        *,
        allow_network: bool,
        force_network: bool = False,
    ) -> list[dict[str, Any]]:
        games, _ts = self.get_games_for_date_with_meta(
            d, allow_network=allow_network, force_network=force_network
        )
        return games
