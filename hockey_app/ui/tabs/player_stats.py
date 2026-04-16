from __future__ import annotations

import datetime as dt
import json
import re
import sys
from collections import deque
from collections.abc import Iterable
from html import unescape
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Callable, Optional
import unicodedata
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
try:
    from PIL import Image, ImageTk  # type: ignore
    _PIL_OK = True
except Exception:
    Image = None  # type: ignore[assignment]
    ImageTk = None  # type: ignore[assignment]
    _PIL_OK = False

from hockey_app.config import END_DATE, SEASON, START_DATE, TIMEZONE
from hockey_app.data.cache import DiskCache
from hockey_app.data.nhl_api import NHLApi
from hockey_app.data.paths import nhl_dir, pwhl_dir
from hockey_app.data.pwhl_api import PWHLApi
from hockey_app.data.xml_cache import read_player_stats_xml, write_player_stats_xml


NHL_BOX_BASE = "https://api-web.nhle.com/v1/gamecenter/{gid}/boxscore"
NHL_SKATER_LEADERS = "https://api-web.nhle.com/v1/skater-stats-leaders/{season}/{game_type}?limit={limit}"
NHL_GOALIE_LEADERS = "https://api-web.nhle.com/v1/goalie-stats-leaders/{season}/{game_type}?limit={limit}"
NHL_MUGSHOT = "https://assets.nhle.com/mugs/nhl/{season}/{team}/{pid}.png"
PWHL_FEED = "https://lscluster.hockeytech.com/feed/index.php"
PWHL_CLIENT_CODE = "pwhl"
PWHL_KEY = "446521baf8c38984"
PWHL_HEADSHOT_HEADERS = {
    "User-Agent": "hockey_app/1.0 (+https://lscluster.hockeytech.com)",
    "Accept": "application/json,text/plain,*/*",
}
PWHL_LOGOS_DIR = Path(__file__).resolve().parents[2] / "assets" / "pwhl_logos"
_WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
PWHL_SKATER_STATS_FILE = _WORKSPACE_ROOT / "pwhl skater stats api page.txt"
PWHL_GOALIE_STATS_FILE = _WORKSPACE_ROOT / "pwhl goalie stats api page.txt"
_PWHL_JSONP_RE = re.compile(r"^[^(]*\((.*)\)\s*;?\s*$", re.DOTALL)
REQ_TIMEOUT = 15

SKATER_ALL_STATS = ["Goals", "Assists", "Points"]
GOALIE_ALL_STATS = ["Wins", "Save %", "Shutouts"]
SKATER_CHOICES = ["All"] + SKATER_ALL_STATS + ["Hits", "Blocks", "+/-", "PIM"]
GOALIE_CHOICES = ["All"] + GOALIE_ALL_STATS + ["Saves / GS", "GAA"]
APP_TZ = ZoneInfo(str(TIMEZONE))
TOP_N_LIST = 25
MIN_PLAYER_ROWS_CACHE = 4
_PWHL_LOGO_CACHE: dict[tuple[str, int], Any] = {}


def _season_compact_id(season: str) -> str:
    # Convert "YYYY-YYYY" style season text into compact NHL API format.
    parts = str(season).split("-")
    if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
        return f"{parts[0]}{parts[1]}"
    digits = "".join(ch for ch in str(season) if ch.isdigit())
    return digits[:8] if len(digits) >= 8 else digits


def _safe_int(v: Any) -> int:
    try:
        return int(float(v))
    except Exception:
        return 0


def _safe_float(v: Any) -> float:
    try:
        return float(v)
    except Exception:
        return 0.0


def _has_any_positive_stat(rows: dict[str, dict[str, Any]], stats: tuple[str, ...]) -> bool:
    for vals in rows.values():
        if not isinstance(vals, dict):
            continue
        for stat in stats:
            if _safe_float(vals.get(stat)) > 0.0:
                return True
    return False


def _player_payload_is_usable(payload: Any, *, league: str) -> bool:
    if not isinstance(payload, dict):
        return False
    payload_league = str(payload.get("league") or league).upper()
    if payload_league and payload_league != str(league).upper():
        return False
    skaters = payload.get("skaters")
    goalies = payload.get("goalies")
    if not isinstance(skaters, dict) or not isinstance(goalies, dict):
        return False
    if payload_league == "PWHL":
        # Invalidate older proxy-only payloads (e.g., "BOS Skaters"), so tabs
        # refresh to real player rows from the PWHL players feed.
        if skaters and all(str(n).upper().endswith(" SKATERS") for n in skaters):
            return False
        if goalies and all(str(n).upper().endswith(" GOALIE") for n in goalies):
            return False
    if (len(skaters) + len(goalies)) < MIN_PLAYER_ROWS_CACHE:
        return False
    return _has_any_positive_stat(skaters, ("Goals", "Assists", "Points")) or _has_any_positive_stat(
        goalies,
        ("Wins", "Save %", "Shutouts"),
    )


def _payload_iso_date_or_today(payload: dict[str, Any], today: dt.date) -> dt.date:
    raw = str(payload.get("date") or "").strip()
    if raw:
        try:
            return dt.date.fromisoformat(raw.split("T", 1)[0])
        except Exception:
            pass
    return today


def _leader_player_name(row: dict[str, Any]) -> str:
    first = _player_name(row.get("firstName"))
    last = _player_name(row.get("lastName"))
    full = " ".join(x for x in (first, last) if x).strip()
    if full:
        return full
    return (
        _player_name(row.get("fullName"))
        or _player_name(row.get("name"))
        or _player_name(row.get("playerName"))
    )


def _leader_team_code(row: dict[str, Any]) -> str:
    v = row.get("teamAbbrev") or row.get("teamCode") or row.get("team")
    if isinstance(v, str):
        return v.upper()
    if isinstance(v, list) and v:
        x = v[0]
        if isinstance(x, str):
            return x.upper()
    return ""


def _leader_player_id(row: dict[str, Any]) -> int:
    return _safe_int(row.get("playerId") or row.get("id"))


def _norm_name(s: str) -> str:
    txt = unicodedata.normalize("NFKD", str(s or ""))
    txt = "".join(ch for ch in txt if not unicodedata.combining(ch))
    return "".join(ch for ch in txt.lower() if ch.isalnum())


def _leader_value(row: dict[str, Any], stat_key: str) -> float:
    # NHL leader feeds commonly expose `value`, but keep fallbacks for schema drift.
    for k in (stat_key, "value", "statValue", "leaderValue", "total"):
        if k in row:
            return _safe_float(row.get(k))
    stats = row.get("stats")
    if isinstance(stats, dict):
        for k in (stat_key, "value", "statValue", "leaderValue", "total"):
            if k in stats:
                return _safe_float(stats.get(k))
    return 0.0


def _fetch_nhl_leaders_json(cache: DiskCache, key: str, url: str, *, allow_network: bool) -> Optional[dict[str, Any]]:
    hit = cache.get_json(key, ttl_s=None)
    if isinstance(hit, dict):
        return hit
    if not allow_network:
        return None
    try:
        r = requests.get(url, timeout=REQ_TIMEOUT)
        r.raise_for_status()
        raw = r.json()
        if isinstance(raw, dict):
            cache.set_json(key, raw)
            return raw
    except Exception:
        return None
    return None


def _aggregate_nhl_player_stats_from_leaders(
    *,
    cache: DiskCache,
    season: str,
    allow_network: bool,
    limit: int = TOP_N_LIST,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    season_id = _season_compact_id(season)
    game_type = 2  # regular season

    skater_url = NHL_SKATER_LEADERS.format(season=season_id, game_type=game_type, limit=max(1, int(limit)))
    goalie_url = NHL_GOALIE_LEADERS.format(season=season_id, game_type=game_type, limit=max(1, int(limit)))
    skater_key = f"nhl/leaders/skaters/{season_id}/{game_type}/{limit}"
    goalie_key = f"nhl/leaders/goalies/{season_id}/{game_type}/{limit}"

    sk_payload = _fetch_nhl_leaders_json(cache, skater_key, skater_url, allow_network=allow_network)
    gl_payload = _fetch_nhl_leaders_json(cache, goalie_key, goalie_url, allow_network=allow_network)
    if not isinstance(sk_payload, dict) and not isinstance(gl_payload, dict):
        return {}, {}

    skaters: dict[str, dict[str, Any]] = {}
    goalies: dict[str, dict[str, Any]] = {}

    sk_map = {
        "goals": "Goals",
        "assists": "Assists",
        "points": "Points",
        "shots": "Shots",
        "hits": "Hits",
        "blockedShots": "Blocks",
        "plusMinus": "+/-",
        "penaltyMinutes": "PIM",
    }
    gl_map = {
        "wins": "Wins",
        "losses": "Losses",
        "otLosses": "OTL",
        "shutouts": "Shutouts",
        "savePct": "Save %",
        "savePctg": "Save %",
        "saves": "Saves",
        "gamesStarted": "Games Started",
        "starts": "Games Started",
        "gamesPlayed": "Games Started",
        "goalsAgainstAverage": "GAA",
        "gaa": "GAA",
    }

    def _merge(payload: dict[str, Any], mapping: dict[str, str], out: dict[str, dict[str, Any]]) -> None:
        for raw_key, stat_name in mapping.items():
            rows = payload.get(raw_key)
            if not isinstance(rows, list):
                continue
            for entry in rows:
                if not isinstance(entry, dict):
                    continue
                name = _leader_player_name(entry)
                if not name:
                    continue
                row = out.setdefault(
                    name,
                    {
                        "_pid": _leader_player_id(entry),
                        "team": _leader_team_code(entry),
                        "Goals": 0.0,
                        "Assists": 0.0,
                        "Points": 0.0,
                        "Shots": 0.0,
                        "Hits": 0.0,
                        "Blocks": 0.0,
                        "+/-": 0.0,
                        "PIM": 0.0,
                        "Wins": 0.0,
                        "Losses": 0.0,
                        "OTL": 0.0,
                        "Shutouts": 0.0,
                        "Save %": 0.0,
                        "Saves": 0.0,
                        "Games Started": 0.0,
                        "Saves / GS": 0.0,
                        "GAA": 0.0,
                    },
                )
                if not _safe_int(row.get("_pid")):
                    row["_pid"] = _leader_player_id(entry)
                if not row.get("team"):
                    row["team"] = _leader_team_code(entry)
                val = _leader_value(entry, raw_key)
                if stat_name == "Save %" and val > 1.0:
                    val = val / 100.0
                row[stat_name] = val

    if isinstance(sk_payload, dict):
        _merge(sk_payload, sk_map, skaters)
    if isinstance(gl_payload, dict):
        _merge(gl_payload, gl_map, goalies)

    # Keep only relevant stat families per side.
    skaters = {
        n: {
            "_pid": _safe_int(r.get("_pid")),
            "team": r.get("team", ""),
            "Goals": _safe_float(r.get("Goals")),
            "Assists": _safe_float(r.get("Assists")),
            "Points": _safe_float(r.get("Points")),
            "Shots": _safe_float(r.get("Shots")),
            "Hits": _safe_float(r.get("Hits")),
            "Blocks": _safe_float(r.get("Blocks")),
            "+/-": _safe_float(r.get("+/-")),
            "PIM": _safe_float(r.get("PIM")),
        }
        for n, r in skaters.items()
    }
    goalies = {
        n: {
            "_pid": _safe_int(r.get("_pid")),
            "team": r.get("team", ""),
            "Wins": _safe_float(r.get("Wins")),
            "Losses": _safe_float(r.get("Losses")),
            "OTL": _safe_float(r.get("OTL")),
            "Shutouts": _safe_float(r.get("Shutouts")),
            "Save %": _safe_float(r.get("Save %")),
            "Saves": _safe_float(r.get("Saves")),
            "Games Started": _safe_float(r.get("Games Started")),
            "Saves / GS": _safe_float(r.get("Saves / GS")),
            "GAA": _safe_float(r.get("GAA")),
        }
        for n, r in goalies.items()
    }
    for row in goalies.values():
        gs = max(0.0, _safe_float(row.get("Games Started")))
        sv = _safe_float(row.get("Saves"))
        row["Saves / GS"] = (sv / gs) if gs > 0.0 else 0.0
    return skaters, goalies


def _backfill_missing_nhl_stats_from_aggregate(
    *,
    target_skaters: dict[str, dict[str, Any]],
    target_goalies: dict[str, dict[str, Any]],
    fallback_skaters: dict[str, dict[str, Any]],
    fallback_goalies: dict[str, dict[str, Any]],
) -> None:
    # Leaders feeds are reliable for headline categories but can be sparse for
    # secondary categories like Hits/Blocks/Saves; patch those from aggregate.
    skater_stats_to_backfill = ("Hits", "Blocks", "PIM")
    goalie_stats_to_backfill = ("Saves", "Games Started", "Saves / GS")

    fb_sk_by_pid: dict[int, dict[str, Any]] = {}
    fb_sk_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for n, r in fallback_skaters.items():
        if not isinstance(r, dict):
            continue
        pid = _safe_int(r.get("_pid"))
        if pid:
            fb_sk_by_pid[pid] = r
        fb_sk_by_key[(str(r.get("team") or "").upper(), _norm_name(str(n)))] = r

    fb_gl_by_pid: dict[int, dict[str, Any]] = {}
    fb_gl_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for n, r in fallback_goalies.items():
        if not isinstance(r, dict):
            continue
        pid = _safe_int(r.get("_pid"))
        if pid:
            fb_gl_by_pid[pid] = r
        fb_gl_by_key[(str(r.get("team") or "").upper(), _norm_name(str(n)))] = r

    for name, vals in target_skaters.items():
        pid = _safe_int(vals.get("_pid"))
        fb = fb_sk_by_pid.get(pid) if pid else None
        if fb is None:
            fb = fb_sk_by_key.get((str(vals.get("team") or "").upper(), _norm_name(name)))
        if not isinstance(fb, dict):
            continue
        for stat in skater_stats_to_backfill:
            cur = _safe_float(vals.get(stat))
            fbv = _safe_float(fb.get(stat))
            if cur <= 0.0 and fbv > 0.0:
                vals[stat] = fbv

    for name, vals in target_goalies.items():
        pid = _safe_int(vals.get("_pid"))
        fb = fb_gl_by_pid.get(pid) if pid else None
        if fb is None:
            fb = fb_gl_by_key.get((str(vals.get("team") or "").upper(), _norm_name(name)))
        if not isinstance(fb, dict):
            continue
        for stat in goalie_stats_to_backfill:
            cur = _safe_float(vals.get(stat))
            fbv = _safe_float(fb.get(stat))
            if cur <= 0.0 and fbv > 0.0:
                vals[stat] = fbv


def _toi_to_seconds(v: Any) -> int:
    if isinstance(v, (int, float)):
        try:
            return int(v)
        except Exception:
            return 0
    if not isinstance(v, str):
        return 0
    s = v.strip()
    if not s:
        return 0
    parts = s.split(":")
    try:
        if len(parts) == 2:
            mm, ss = int(parts[0]), int(parts[1])
            return mm * 60 + ss
        if len(parts) == 3:
            hh, mm, ss = int(parts[0]), int(parts[1]), int(parts[2])
            return hh * 3600 + mm * 60 + ss
    except Exception:
        return 0
    return 0


def _player_name(v: Any) -> str:
    if isinstance(v, dict):
        for k in ("default", "fullName", "name", "displayName"):
            x = v.get(k)
            if isinstance(x, str) and x.strip():
                return x.strip()
        return ""
    if isinstance(v, str):
        return v.strip()
    return ""


def _game_is_final(g: dict[str, Any]) -> bool:
    st = str(g.get("gameState") or g.get("gameStatus") or "").upper()
    return st in {"FINAL", "OFF"} or st.startswith("FINAL")


def _iter_nhl_games(api: NHLApi, d: dt.date) -> list[dict[str, Any]]:
    iso = d.isoformat()
    for key in (f"nhl/score/final/{iso}", f"nhl/score/live/{iso}"):
        hit = api.cache.get_json(key, ttl_s=None)  # type: ignore[attr-defined]
        if isinstance(hit, dict):
            return [x for x in (hit.get("games") or []) if isinstance(x, dict)]
    return []


def _iter_pwhl_games(api: PWHLApi, d: dt.date) -> list[dict[str, Any]]:
    try:
        rows = api.get_games_for_date(d, allow_network=False)
    except Exception:
        return []
    return [x for x in rows if isinstance(x, dict)]


def _norm_pwhl_code(code: str) -> str:
    c = str(code or "").strip().upper()
    return {"MON": "MTL", "NYC": "NY"}.get(c, c)


def _pwhl_load_json_payload_from_text(text: str) -> Any:
    s = str(text or "").strip()
    if not s:
        return None
    try:
        return json.loads(s)
    except Exception:
        pass
    if s.startswith("(") and s.endswith(")"):
        inner = s[1:-1].strip()
        if inner:
            try:
                return json.loads(inner)
            except Exception:
                pass
    m = _PWHL_JSONP_RE.match(s)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    return None


def _pwhl_read_payload_file(path: Path) -> tuple[Any, str | None]:
    if not path.exists():
        return None, None
    try:
        raw = path.read_text(encoding="utf-8")
    except Exception:
        return None, None
    text = str(raw or "").strip()
    if not text:
        return None, None
    lines = text.splitlines()
    if lines and not lines[0].lstrip().startswith(("{", "[", "(", "http://", "https://")):
        text = "\n".join(lines[1:]).strip()
    if not text:
        return None, None
    if text.lower().startswith(("http://", "https://")):
        return None, text.splitlines()[0].strip()
    return _pwhl_load_json_payload_from_text(text), None


def _pwhl_extract_player_rows(raw: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen_obj: set[int] = set()
    row_markers = {
        "player_id",
        "playerId",
        "name",
        "team_code",
        "position",
        "goals",
        "assists",
        "points",
        "wins",
        "losses",
        "save_percentage",
        "save_pct",
    }

    def _visit(obj: Any, depth: int = 0) -> None:
        if depth > 9:
            return
        if isinstance(obj, list):
            for it in obj:
                _visit(it, depth + 1)
            return
        if not isinstance(obj, dict):
            return
        oid = id(obj)
        if oid in seen_obj:
            return
        seen_obj.add(oid)

        out_row: dict[str, Any] | None = None
        row = obj.get("row")
        if isinstance(row, dict):
            out_row = dict(row)
            prop = obj.get("prop")
            if isinstance(prop, dict):
                for k, v in prop.items():
                    if k not in out_row:
                        out_row[k] = v
        elif row_markers & set(obj.keys()):
            out_row = dict(obj)

        if isinstance(out_row, dict):
            rows.append(out_row)

        for v in obj.values():
            if isinstance(v, (dict, list)):
                _visit(v, depth + 1)

    _visit(raw)

    deduped: list[dict[str, Any]] = []
    seen_key: set[tuple[str, str, str, str]] = set()
    for row in rows:
        key = (
            str(row.get("player_id") or row.get("playerId") or ""),
            str(row.get("name") or "").strip(),
            str(row.get("team_code") or row.get("team") or "").strip().upper(),
            str(row.get("rank") or ""),
        )
        if key in seen_key:
            continue
        seen_key.add(key)
        deduped.append(row)
    return deduped


def _pwhl_pick_row_value(row: dict[str, Any], *keys: str) -> Any:
    for k in keys:
        if k not in row:
            continue
        v = row.get(k)
        if v is None:
            continue
        s = str(v).strip()
        if not s or s == "-":
            continue
        return v
    return None


def _pwhl_unique_name(store: dict[str, dict[str, Any]], name: str, team: str) -> str:
    if name not in store:
        return name
    existing_team = str(store[name].get("team") or "").upper()
    if existing_team == str(team or "").upper():
        return name
    suffix = str(team or "ALT").upper()
    candidate = f"{name} ({suffix})"
    if candidate not in store:
        return candidate
    i = 2
    while f"{name} ({suffix} {i})" in store:
        i += 1
    return f"{name} ({suffix} {i})"


def _pwhl_guess_season_id(*, pwhl: PWHLApi, dref: dt.date, allow_network: bool) -> str:
    try:
        sid = str(
            pwhl._pick_season_id(  # type: ignore[attr-defined]
                dref,
                allow_network=allow_network,
                force_network=False,
            )
            or ""
        ).strip()
        if sid:
            return sid
    except Exception:
        pass
    for path in (PWHL_SKATER_STATS_FILE, PWHL_GOALIE_STATS_FILE):
        _payload, url = _pwhl_read_payload_file(path)
        if not url:
            continue
        m = re.search(r"[?&]season=([^&]+)", url)
        if m:
            return str(m.group(1)).strip()
    # Fall back to known endpoint season id from local notes/context.
    return "5"


def _pwhl_fetch_players_payload(
    *,
    pwhl: PWHLApi,
    season_id: str,
    position: str,
    allow_network: bool,
    local_file: Path,
) -> Any:
    cache_key = f"pwhl/players/{season_id}/{position}"
    hit = pwhl.cache.get_json(cache_key, ttl_s=None)  # type: ignore[attr-defined]
    if isinstance(hit, (dict, list)):
        return hit

    local_payload, local_url = _pwhl_read_payload_file(local_file)
    if isinstance(local_payload, (dict, list)):
        try:
            pwhl.cache.set_json(cache_key, local_payload)  # type: ignore[attr-defined]
        except Exception:
            pass
        return local_payload

    if not allow_network:
        return None

    try:
        if local_url:
            r = requests.get(local_url, headers=pwhl.headers, timeout=pwhl.timeout_s)
        else:
            r = requests.get(
                pwhl.base_url,
                params={
                    "feed": "statviewfeed",
                    "view": "players",
                    "season": season_id,
                    "team": "all",
                    "position": position,
                    "rookies": "0",
                    "statsType": "standard",
                    "rosterstatus": "undefined",
                    "site_id": "0",
                    "league_id": "1",
                    "lang": "en",
                    "division": "-1",
                    "conference": "-1",
                    "key": pwhl.key_modulekit,
                    "client_code": "pwhl",
                    "limit": "500",
                    "sort": "points",
                },
                headers=pwhl.headers,
                timeout=pwhl.timeout_s,
            )
        r.raise_for_status()
        payload = _pwhl_load_json_payload_from_text(r.text)
        if isinstance(payload, (dict, list)):
            try:
                pwhl.cache.set_json(cache_key, payload)  # type: ignore[attr-defined]
            except Exception:
                pass
            return payload
    except Exception:
        return None
    return None


def _pwhl_logo_paths(code: str) -> list[Path]:
    c = _norm_pwhl_code(code)
    names = [c, c.lower()]
    aliases: dict[str, tuple[str, ...]] = {
        "BOS": ("boston", "fleet", "boston_fleet"),
        "MIN": ("minnesota", "frost", "minnesota_frost"),
        "MTL": ("montreal", "victoire", "montreal_victoire", "mon"),
        "NY": ("new_york", "sirens", "new_york_sirens", "ny_sirens"),
        "OTT": ("ottawa", "charge", "ottawa_charge"),
        "TOR": ("toronto", "sceptres", "toronto_sceptres"),
        "VAN": ("vancouver", "goldeneyes", "vancouver_goldeneyes"),
        "SEA": ("seattle", "torrent", "seattle_torrent"),
    }
    names.extend(aliases.get(c, ()))
    return [PWHL_LOGOS_DIR / f"{n}.png" for n in names]


def _pwhl_logo_get(code: str, *, height: int, master: tk.Misc) -> Any:
    c = _norm_pwhl_code(code)
    h = int(max(1, height))
    key = (c, h)
    if key in _PWHL_LOGO_CACHE:
        return _PWHL_LOGO_CACHE[key]
    for p in _pwhl_logo_paths(c):
        if not p.exists():
            continue
        try:
            img = tk.PhotoImage(master=master, file=str(p))
            h0 = int(max(1, img.height()))
            if h0 > h:
                factor = max(1, int(round(h0 / float(h))))
                img = img.subsample(factor, factor)
            _PWHL_LOGO_CACHE[key] = img
            return img
        except Exception:
            continue
    return None


def _logo_for_team(code: str, logo_bank: Any, *, league: str, height: int = 72, master: tk.Misc):
    if str(league or "").upper() == "PWHL":
        return _pwhl_logo_get(code, height=height, master=master)
    try:
        return logo_bank.get(str(code).upper(), height=height, dim=False)
    except Exception:
        return None


def _make_silhouette(master: tk.Misc, width: int) -> tk.PhotoImage:
    s = max(12, int(width))
    img = tk.PhotoImage(master=master, width=s, height=s)
    # Transparent background with a simple hockey-player silhouette so fallback
    # avatars do not appear as opaque rectangles.
    c1 = "#9b9b9b"
    c2 = "#7f7f7f"
    cx = s // 2
    head_r = max(2, s // 9)
    shoulder_w = max(6, int(s * 0.36))
    torso_h = max(6, int(s * 0.28))
    hips_w = max(5, int(s * 0.24))
    leg_h = max(6, int(s * 0.22))
    stick_w = max(1, s // 22)

    # head
    img.put(c1, to=(cx - head_r, max(1, s // 9), cx + head_r, max(2, s // 9 + head_r * 2)))
    # shoulders + torso
    top = max(2, int(s * 0.28))
    img.put(c1, to=(cx - shoulder_w // 2, top, cx + shoulder_w // 2, top + torso_h // 2))
    img.put(c1, to=(cx - hips_w // 2, top + torso_h // 2, cx + hips_w // 2, top + torso_h))
    # legs
    leg_top = top + torso_h
    img.put(c1, to=(cx - hips_w // 2, leg_top, cx - hips_w // 2 + max(2, hips_w // 3), leg_top + leg_h))
    img.put(c1, to=(cx + hips_w // 2 - max(2, hips_w // 3), leg_top, cx + hips_w // 2, leg_top + leg_h))
    # hockey stick
    sx = cx + shoulder_w // 2 - 1
    sy = top + 1
    img.put(c2, to=(sx, sy, sx + stick_w, min(s - 1, sy + int(s * 0.46))))
    blade_y = min(s - 2, sy + int(s * 0.46))
    img.put(c2, to=(sx - max(3, s // 10), blade_y, sx + stick_w + max(5, s // 8), blade_y + max(1, s // 24)))
    return img


def _normalize_photo_box(img: tk.PhotoImage, width: int, max_height: int) -> tk.PhotoImage:
    target_w = max(12, int(width))
    target_h = max(12, int(max_height))
    w = max(1, int(img.width()))
    h = max(1, int(img.height()))
    if w <= target_w and h <= target_h:
        return img
    # Tk photo scaling uses integer factors; keep both width and height bounded.
    factor_w = max(1, int(round(w / float(target_w))))
    factor_h = max(1, int(round(h / float(target_h))))
    factor = max(factor_w, factor_h)
    return img.subsample(factor, factor)


def _strip_edge_background_rgba(image: Any) -> Any:
    """
    Remove edge-connected, near-uniform background pixels.
    This keeps interior whites (jerseys/eyes/etc.) while clearing studio backdrops.
    """
    if not _PIL_OK:
        return image
    try:
        work = image.convert("RGBA")  # type: ignore[union-attr]
    except Exception:
        return image

    w, h = work.size  # type: ignore[union-attr]
    if w < 8 or h < 8:
        return work

    px = work.load()  # type: ignore[union-attr]
    border: list[tuple[int, int, int]] = []
    # Use corner-driven sampling/seeding to avoid side-edge jersey bleed.
    sample_w = max(2, min(w // 2, int(round(w * 0.24))))
    sample_h = max(2, min(h // 2, int(round(h * 0.18))))
    for y in range(sample_h):
        for x in range(sample_w):
            r, g, b, a = px[x, y]
            if int(a) > 8:
                border.append((int(r), int(g), int(b)))
        for x in range(max(0, w - sample_w), w):
            r, g, b, a = px[x, y]
            if int(a) > 8:
                border.append((int(r), int(g), int(b)))
    if len(border) < 12:
        return work

    rs = sorted(v[0] for v in border)
    gs = sorted(v[1] for v in border)
    bs = sorted(v[2] for v in border)
    mid = len(border) // 2
    bg_r = int(rs[mid])
    bg_g = int(gs[mid])
    bg_b = int(bs[mid])
    bg_luma = (bg_r + bg_g + bg_b) // 3
    bg_chroma = max(bg_r, bg_g, bg_b) - min(bg_r, bg_g, bg_b)

    border_dists = sorted(abs(r - bg_r) + abs(g - bg_g) + abs(b - bg_b) for r, g, b in border)
    p80 = border_dists[min(len(border_dists) - 1, int(len(border_dists) * 0.8))]
    tol = max(32, min(140, int(p80) + 20))
    if bg_luma >= 220:
        tol = min(150, tol + 10)

    # Avoid letting flood-fill cross into facial/jersey details near center.
    center_x0 = int(w * 0.20)
    center_x1 = int(w * 0.80)
    center_y0 = int(h * 0.14)
    center_y1 = int(h * 0.88)

    def _is_bg_pixel(x: int, y: int) -> bool:
        r, g, b, a = px[x, y]
        if int(a) <= 8:
            return True
        dr = abs(int(r) - bg_r)
        dg = abs(int(g) - bg_g)
        db = abs(int(b) - bg_b)
        dist = dr + dg + db
        chroma = max(int(r), int(g), int(b)) - min(int(r), int(g), int(b))

        # For neutral studio backgrounds, keep saturated/skin-like colors.
        if bg_chroma <= 18 and chroma > 58:
            return False
        # For colored backgrounds, require similar colorfulness.
        if bg_chroma > 18 and abs(chroma - bg_chroma) > 72 and dist > (tol // 2):
            return False
        # Stronger gate through the central portrait region.
        if center_x0 <= x <= center_x1 and center_y0 <= y <= center_y1 and dist > max(20, tol - 26):
            return False

        if dist <= tol and max(dr, dg, db) <= max(18, int(tol * 0.68)):
            return True
        lum = (int(r) + int(g) + int(b)) // 3
        if bg_luma >= 220 and lum >= 242 and dist <= (tol + 20) and chroma <= 44:
            return True
        return False

    seen = bytearray(w * h)
    q: deque[tuple[int, int]] = deque()

    def _push(x: int, y: int) -> None:
        i = y * w + x
        if seen[i]:
            return
        if not _is_bg_pixel(x, y):
            return
        seen[i] = 1
        q.append((x, y))

    seed_w = max(2, min(w // 2, int(round(w * 0.20))))
    seed_h = max(2, min(h // 2, int(round(h * 0.16))))
    for y in range(seed_h):
        for x in range(seed_w):
            _push(x, y)
        for x in range(max(0, w - seed_w), w):
            _push(x, y)

    while q:
        x, y = q.popleft()
        if x > 0:
            _push(x - 1, y)
        if x + 1 < w:
            _push(x + 1, y)
        if y > 0:
            _push(x, y - 1)
        if y + 1 < h:
            _push(x, y + 1)

    bg_count = int(sum(seen))
    area = w * h
    # Guardrail: do not wipe photos if detection overreaches.
    if bg_count <= 0 or bg_count > int(area * 0.88):
        return work

    data = list(work.getdata())  # type: ignore[union-attr]
    for i, is_bg in enumerate(seen):
        if not is_bg:
            continue
        r, g, b, a = data[i]
        if int(a) > 0:
            data[i] = (int(r), int(g), int(b), 0)
    work.putdata(data)  # type: ignore[union-attr]
    return work


def _pil_photo_box_from_path(
    path: Path,
    *,
    master: tk.Misc,
    width: int,
    max_height: int,
    remove_bg: bool = False,
) -> Any:
    if not _PIL_OK:
        return None
    try:
        with Image.open(path) as im:  # type: ignore[union-attr]
            work = im.convert("RGBA")
            if remove_bg:
                work = _strip_edge_background_rgba(work)
            work.thumbnail((max(12, int(width)), max(12, int(max_height))), Image.Resampling.LANCZOS)  # type: ignore[union-attr]
            return ImageTk.PhotoImage(work, master=master)  # type: ignore[union-attr]
    except Exception:
        return None


def _photo_box_from_path(
    path: Path,
    *,
    master: tk.Misc,
    width: int,
    max_height: int,
    remove_bg: bool = False,
) -> Any:
    if remove_bg and _PIL_OK:
        pil_shot = _pil_photo_box_from_path(
            path,
            master=master,
            width=width,
            max_height=max_height,
            remove_bg=True,
        )
        if pil_shot is not None:
            return pil_shot
    try:
        raw = tk.PhotoImage(master=master, file=str(path))
        return _normalize_photo_box(raw, width, max_height)
    except Exception:
        return _pil_photo_box_from_path(
            path,
            master=master,
            width=width,
            max_height=max_height,
            remove_bg=remove_bg,
        )


def _pwhl_fetch_player_category_payload(
    *,
    pid: int,
    category: str,
    cache_dir: Path,
    allow_network: bool,
    failed: set[tuple[str, int]],
) -> Any:
    profile_path = cache_dir / f"pwhl_{int(pid)}_{category}.json"
    profile_txt_path = cache_dir / f"pwhl_{int(pid)}_{category}.txt"
    if profile_path.exists():
        try:
            return json.loads(profile_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    if profile_txt_path.exists():
        try:
            txt = profile_txt_path.read_text(encoding="utf-8").strip()
            if txt:
                return txt
        except Exception:
            pass

    if not allow_network or ("PWHL_NET", -1) in failed:
        return None

    # HockeyTech endpoints can vary by tenant and category naming; try a few
    # common parameter variants before giving up for this player/category.
    candidates: list[dict[str, str]] = [
        {
            "feed": "modulekit",
            "view": "player",
            "category": category,
            "player_id": str(int(pid)),
            "key": PWHL_KEY,
            "client_code": PWHL_CLIENT_CODE,
        },
        {
            "feed": "modulekit",
            "view": "player",
            "category": category,
            "player": str(int(pid)),
            "key": PWHL_KEY,
            "client_code": PWHL_CLIENT_CODE,
        },
        {
            "feed": "statviewfeed",
            "view": "player",
            "category": category,
            "player_id": str(int(pid)),
            "key": PWHL_KEY,
            "client_code": PWHL_CLIENT_CODE,
            "site_id": "2",
            "league_id": "1",
            "lang": "en",
        },
        {
            "feed": "statviewfeed",
            "view": "playerprofile",
            "player_id": str(int(pid)),
            "key": PWHL_KEY,
            "client_code": PWHL_CLIENT_CODE,
            "site_id": "2",
            "league_id": "1",
            "lang": "en",
        },
    ]
    for params in candidates:
        try:
            r = requests.get(
                PWHL_FEED,
                params=params,
                headers=PWHL_HEADSHOT_HEADERS,
                timeout=REQ_TIMEOUT,
            )
            if int(r.status_code) >= 400:
                continue
            body = str(r.text or "").strip()
            if not body:
                continue
            payload = _pwhl_load_json_payload_from_text(body)
            cache_dir.mkdir(parents=True, exist_ok=True)
            if isinstance(payload, (dict, list)):
                profile_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                return payload
            profile_txt_path.write_text(body, encoding="utf-8")
            return body
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            # Network appears unavailable; avoid repeated long timeouts.
            failed.add(("PWHL_NET", -1))
            break
        except requests.exceptions.RequestException:
            continue
    return None


def _pwhl_extract_photo_url(payload: Any) -> str | None:
    if payload is None:
        return None
    seen_obj: set[int] = set()
    best: tuple[int, str] | None = None
    hint_keys = ("photo", "image", "headshot", "portrait", "mug", "hero", "thumb")
    image_exts = (".png", ".jpg", ".jpeg", ".webp")

    def _score_url(url: str, key_hint: str) -> int:
        u = str(url).lower()
        score = 0
        if any(ext in u for ext in image_exts):
            score += 4
        if "hockeytech" in u or "lscluster" in u:
            score += 2
        if "player" in u:
            score += 1
        if any(h in key_hint for h in hint_keys):
            score += 5
        return score

    def _norm_url(s: str) -> str:
        txt = str(s or "").strip()
        if not txt:
            return ""
        if txt.startswith("//"):
            return f"https:{txt}"
        if txt.startswith("/"):
            return urljoin("https://lscluster.hockeytech.com/", txt)
        return txt

    def _visit(obj: Any, depth: int = 0, key_hint: str = "") -> None:
        nonlocal best
        if depth > 10:
            return
        if isinstance(obj, dict):
            oid = id(obj)
            if oid in seen_obj:
                return
            seen_obj.add(oid)
            for k, v in obj.items():
                k_l = str(k or "").strip().lower()
                if isinstance(v, str):
                    u = _norm_url(v)
                    if u.startswith("http://") or u.startswith("https://"):
                        sc = _score_url(u, k_l)
                        if sc > 0 and (best is None or sc > best[0]):
                            best = (sc, u)
                elif isinstance(v, (dict, list)):
                    _visit(v, depth + 1, k_l)
            return
        if isinstance(obj, list):
            for it in obj:
                _visit(it, depth + 1, key_hint)

    if isinstance(payload, str):
        txt = payload.replace("\\/", "/")
        for m in re.finditer(r"https?://[^\s\"'<>]+", txt):
            u = _norm_url(m.group(0))
            sc = _score_url(u, "text")
            if sc > 0 and (best is None or sc > best[0]):
                best = (sc, u)
        for m in re.finditer(r"//[^\s\"'<>]+", txt):
            u = _norm_url(m.group(0))
            sc = _score_url(u, "text")
            if sc > 0 and (best is None or sc > best[0]):
                best = (sc, u)
    else:
        _visit(payload, 0, "")
    return best[1] if best else None


def _pwhl_photo_url_for_player(
    *,
    pid: int,
    cache_dir: Path,
    allow_network: bool,
    failed: set[tuple[str, int]],
) -> str | None:
    url_cache = cache_dir / f"pwhl_{int(pid)}_photo_url.txt"
    if url_cache.exists():
        try:
            txt = url_cache.read_text(encoding="utf-8").strip()
            if txt:
                return txt
        except Exception:
            pass
    for category in ("profile", "media", "bio"):
        payload = _pwhl_fetch_player_category_payload(
            pid=pid,
            category=category,
            cache_dir=cache_dir,
            allow_network=allow_network,
            failed=failed,
        )
        photo_url = _pwhl_extract_photo_url(payload)
        if photo_url:
            try:
                cache_dir.mkdir(parents=True, exist_ok=True)
                url_cache.write_text(photo_url, encoding="utf-8")
            except Exception:
                pass
            return photo_url
    return None


def _pwhl_direct_photo_url_candidates(pid: int) -> list[str]:
    p = int(pid)
    base = f"https://lscluster.hockeytech.com/download.php?client_code={PWHL_CLIENT_CODE}&file_path="
    return [
        f"{base}photos/players/{p}.jpg",
        f"{base}photos/players/{p}.png",
        f"{base}images/players/{p}.jpg",
        f"{base}images/players/{p}.png",
        f"{base}players/{p}.jpg",
        f"{base}players/{p}.png",
    ]


def _headshot_for_player(
    *,
    league: str,
    pid: int,
    team_code: str,
    season_id: str,
    cache_dir: Path,
    memo: dict[tuple[str, int, int], Any],
    failed: set[tuple[str, int]],
    master: tk.Misc,
    width: int,
    max_height: int,
    allow_network: bool,
) -> Any:
    key = (str(league).upper(), int(pid), int(width))
    if key in memo:
        return memo[key]

    league_u = str(league).upper()
    if int(pid) <= 0:
        sil = _make_silhouette(master, width)
        memo[key] = sil
        return sil

    if league_u not in {"NHL", "PWHL"}:
        sil = _make_silhouette(master, width)
        memo[key] = sil
        return sil

    if league_u == "NHL":
        img_path = cache_dir / f"nhl_{season_id}_{int(pid)}.png"
    else:
        img_path = cache_dir / f"pwhl_{int(pid)}.png"
    if img_path.exists():
        shot = _photo_box_from_path(
            img_path,
            master=master,
            width=width,
            max_height=max_height,
            remove_bg=(league_u == "PWHL"),
        )
        if shot is not None:
            memo[key] = shot
            return shot

    fail_key = (league_u, int(pid))
    if allow_network and fail_key not in failed:
        if league_u == "NHL":
            team = str(team_code or "").upper() or "NHL"
            url = NHL_MUGSHOT.format(season=season_id, team=team, pid=int(pid))
        else:
            url = _pwhl_photo_url_for_player(
                pid=int(pid),
                cache_dir=cache_dir,
                allow_network=allow_network,
                failed=failed,
            )
            if not url:
                for cand in _pwhl_direct_photo_url_candidates(int(pid)):
                    try:
                        r = requests.get(cand, headers=PWHL_HEADSHOT_HEADERS, timeout=REQ_TIMEOUT)
                        if int(r.status_code) >= 400 or not r.content:
                            continue
                        cache_dir.mkdir(parents=True, exist_ok=True)
                        img_path.write_bytes(r.content)
                        url_cache = cache_dir / f"pwhl_{int(pid)}_photo_url.txt"
                        try:
                            url_cache.write_text(cand, encoding="utf-8")
                        except Exception:
                            pass
                        shot = _photo_box_from_path(
                            img_path,
                            master=master,
                            width=width,
                            max_height=max_height,
                            remove_bg=(league_u == "PWHL"),
                        )
                        if shot is not None:
                            memo[key] = shot
                            return shot
                    except Exception:
                        continue
                failed.add(fail_key)
                url = ""
        try:
            if url:
                r = requests.get(
                    url,
                    headers=(PWHL_HEADSHOT_HEADERS if league_u == "PWHL" else None),
                    timeout=REQ_TIMEOUT,
                )
                r.raise_for_status()
                cache_dir.mkdir(parents=True, exist_ok=True)
                img_path.write_bytes(r.content)
                shot = _photo_box_from_path(
                    img_path,
                    master=master,
                    width=width,
                    max_height=max_height,
                    remove_bg=(league_u == "PWHL"),
                )
                if shot is not None:
                    memo[key] = shot
                    return shot
        except Exception:
            failed.add(fail_key)

    sil = _make_silhouette(master, width)
    memo[key] = sil
    return sil


def _draw_headshot_stack(
    parent: tk.Misc,
    *,
    headshot: Any,
    logo: Any,
    head_w: int,
    head_h: int,
    logo_w: int,
    logo_h: int,
    bg: str,
) -> tk.Canvas:
    cw = max(head_w + max(12, logo_w // 3), head_w)
    ch = max(head_h + max(6, logo_h // 8), head_h)
    head_x = max(0, (cw - head_w) // 2)
    head_y = max(4, int(head_h * 0.04))
    logo_x = max(0, head_x - int(logo_w * 0.35))
    logo_y = max(0, head_y + int(head_h * 0.02) - int(logo_h * 0.25))
    c = tk.Canvas(parent, width=cw, height=ch, bg=bg, highlightthickness=0, bd=0)
    if logo is not None:
        c.create_image(logo_x, logo_y, image=logo, anchor="nw")
    if headshot is not None:
        c.create_image(head_x, head_y, image=headshot, anchor="nw")
    return c


def _headshot_max_height_for_team(team_code: str, default_height: int = 160) -> int:
    code = str(team_code or "").upper()
    if code == "TBL":
        return 148
    return max(120, int(default_height))


def _boxscore_from_cache_or_api(cache: DiskCache, gid: int, *, allow_network: bool) -> Optional[dict[str, Any]]:
    key = f"nhl/boxscore/{gid}"
    hit = cache.get_json(key, ttl_s=None)
    if isinstance(hit, dict):
        return hit
    if not allow_network:
        return None
    try:
        r = requests.get(NHL_BOX_BASE.format(gid=gid), timeout=REQ_TIMEOUT)
        r.raise_for_status()
        raw = r.json()
        if isinstance(raw, dict):
            cache.set_json(key, raw)
            return raw
    except Exception:
        return None
    return None


def _iter_team_player_lists(team_blob: dict[str, Any], keys: Iterable[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for k in keys:
        v = team_blob.get(k)
        if isinstance(v, list):
            out.extend([x for x in v if isinstance(x, dict)])
    return out


def _aggregate_nhl_player_stats(
    *,
    nhl: NHLApi,
    cache: DiskCache,
    allow_network: bool,
    dmin: dt.date,
    dmax: dt.date,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    skaters: dict[str, dict[str, Any]] = {}
    goalies: dict[str, dict[str, Any]] = {}

    d = dmin
    while d <= dmax:
        games = _iter_nhl_games(nhl, d)
        for g in games:
            if not _game_is_final(g):
                continue
            gid = _safe_int(g.get("id"))
            away = g.get("awayTeam") or {}
            home = g.get("homeTeam") or {}
            away_code = str(away.get("abbrev") or away.get("abbreviation") or away.get("teamAbbrev") or "").upper()
            home_code = str(home.get("abbrev") or home.get("abbreviation") or home.get("teamAbbrev") or "").upper()

            box = _boxscore_from_cache_or_api(cache, gid, allow_network=allow_network)
            if not isinstance(box, dict):
                # fallback from cached goals list only
                goals = g.get("goals") or []
                if isinstance(goals, list):
                    for ev in goals:
                        if not isinstance(ev, dict):
                            continue
                        scorer = _player_name(
                            ev.get("scorerName")
                            or ev.get("name")
                            or ev.get("playerName")
                            or ev.get("goalScorer")
                        )
                        tcode = str(ev.get("teamAbbrev") or "").upper()
                        if scorer:
                            row = skaters.setdefault(
                                scorer,
                                {
                                    "team": tcode,
                                    "Goals": 0.0,
                                    "Assists": 0.0,
                                    "Points": 0.0,
                                    "Shots": 0.0,
                                    "Hits": 0.0,
                                    "Blocks": 0.0,
                                    "+/-": 0.0,
                                    "PIM": 0.0,
                                },
                            )
                            row["Goals"] += 1.0
                            row["Points"] += 1.0
                continue

            pbs = box.get("playerByGameStats") or {}
            box_away = box.get("awayTeam") or {}
            box_home = box.get("homeTeam") or {}
            away_score = _safe_int(box_away.get("score") if isinstance(box_away, dict) else None)
            home_score = _safe_int(box_home.get("score") if isinstance(box_home, dict) else None)
            if away_score == 0 and home_score == 0:
                away_score = _safe_int(away.get("score"))
                home_score = _safe_int(home.get("score"))
            final_type = str(
                (box.get("gameOutcome") or {}).get("lastPeriodType")
                or (g.get("gameOutcome") or {}).get("lastPeriodType")
                or g.get("statusText")
                or ""
            ).upper()
            is_otso = any(tok in final_type for tok in ("OT", "SO", "OVERTIME", "SHOOTOUT"))
            team_map = {
                "awayTeam": away_code,
                "homeTeam": home_code,
            }
            for side in ("awayTeam", "homeTeam"):
                team_blob = pbs.get(side) or {}
                tcode = team_map.get(side, "")

                s_list = _iter_team_player_lists(team_blob, ("forwards", "defense", "defensemen", "skaters"))
                for p in s_list:
                    nm = _player_name(p.get("name") or p.get("playerName") or p.get("firstName"))
                    if not nm:
                        continue
                    row = skaters.setdefault(
                        nm,
                        {
                            "_pid": _safe_int(p.get("playerId") or p.get("id")),
                            "team": tcode,
                            "Goals": 0.0,
                            "Assists": 0.0,
                            "Points": 0.0,
                            "Shots": 0.0,
                            "Hits": 0.0,
                            "Blocks": 0.0,
                            "+/-": 0.0,
                            "PIM": 0.0,
                        },
                    )
                    if not _safe_int(row.get("_pid")):
                        row["_pid"] = _safe_int(p.get("playerId") or p.get("id"))
                    row["Goals"] += _safe_float(p.get("goals"))
                    row["Assists"] += _safe_float(p.get("assists"))
                    pts = p.get("points")
                    row["Points"] += _safe_float(pts if pts is not None else (_safe_float(p.get("goals")) + _safe_float(p.get("assists"))))
                    row["Shots"] += _safe_float(p.get("shots") or p.get("shotsOnGoal"))
                    row["Hits"] += _safe_float(p.get("hits") or p.get("bodyChecks"))
                    row["Blocks"] += _safe_float(p.get("blockedShots") or p.get("blocks") or p.get("blocked"))
                    row["+/-"] += _safe_float(p.get("plusMinus") or p.get("plusminus"))
                    row["PIM"] += _safe_float(p.get("pim") or p.get("penaltyMinutes"))

                g_list = _iter_team_player_lists(team_blob, ("goalies",))
                primary_goalie_idx = -1
                if g_list:
                    primary_goalie_idx = max(
                        range(len(g_list)),
                        key=lambda i: _toi_to_seconds(g_list[i].get("toi") or g_list[i].get("timeOnIce")),
                    )
                for i, p in enumerate(g_list):
                    nm = _player_name(p.get("name") or p.get("playerName") or p.get("firstName"))
                    if not nm:
                        continue
                    row = goalies.setdefault(
                        nm,
                        {
                            "_pid": _safe_int(p.get("playerId") or p.get("id")),
                            "team": tcode,
                            "Wins": 0.0,
                            "Losses": 0.0,
                            "OTL": 0.0,
                            "Shutouts": 0.0,
                            "Save %": 0.0,
                            "Saves": 0.0,
                            "Games Started": 0.0,
                            "Saves / GS": 0.0,
                            "GAA": 0.0,
                            "_gp": 0.0,
                        },
                    )
                    if not _safe_int(row.get("_pid")):
                        row["_pid"] = _safe_int(p.get("playerId") or p.get("id"))
                    row["Wins"] += _safe_float(p.get("wins") or p.get("W") or p.get("win"))
                    row["Losses"] += _safe_float(p.get("losses") or p.get("L") or p.get("loss"))
                    row["OTL"] += _safe_float(p.get("otLosses") or p.get("otl") or p.get("OTL"))
                    row["Shutouts"] += _safe_float(p.get("shutouts") or p.get("SO"))
                    sp = p.get("savePctg") if p.get("savePctg") is not None else (p.get("savePct") if p.get("savePct") is not None else p.get("svPct"))
                    row["Save %"] += _safe_float(sp)
                    row["Saves"] += _safe_float(p.get("saves") or p.get("saveTotal") or p.get("SV"))
                    if i == primary_goalie_idx:
                        row["Games Started"] += 1.0
                    row["GAA"] += _safe_float(p.get("gaa") or p.get("GAA"))
                    row["_gp"] += 1.0

                # Fallback for feeds where goalie decisions are omitted (all zeroes).
                if g_list:
                    team_won = (away_score > home_score) if side == "awayTeam" else (home_score > away_score)
                    for i, p in enumerate(g_list):
                        nm = _player_name(p.get("name") or p.get("playerName") or p.get("firstName"))
                        if not nm:
                            continue
                        row = goalies.get(nm)
                        if not row:
                            continue
                        has_decision = (
                            float(row.get("Wins") or 0.0) > 0.0
                            or float(row.get("Losses") or 0.0) > 0.0
                            or float(row.get("OTL") or 0.0) > 0.0
                        )
                        if has_decision or i != primary_goalie_idx:
                            continue
                        if team_won:
                            row["Wins"] += 1.0
                        elif is_otso:
                            row["OTL"] += 1.0
                        else:
                            row["Losses"] += 1.0
        d += dt.timedelta(days=1)

    for nm, row in goalies.items():
        gp = max(1.0, float(row.get("_gp") or 1.0))
        row["Save %"] = float(row.get("Save %") or 0.0) / gp
        row["GAA"] = float(row.get("GAA") or 0.0) / gp
        gs = max(0.0, float(row.get("Games Started") or 0.0))
        row["Saves / GS"] = (float(row.get("Saves") or 0.0) / gs) if gs > 0.0 else 0.0
        row.pop("_gp", None)
    return skaters, goalies


def _aggregate_pwhl_player_stats(
    *,
    pwhl: PWHLApi,
    dmin: dt.date,
    dmax: dt.date,
    allow_network: bool,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    _ = dmin
    skaters: dict[str, dict[str, Any]] = {}
    goalies: dict[str, dict[str, Any]] = {}

    season_id = _pwhl_guess_season_id(pwhl=pwhl, dref=dmax, allow_network=allow_network)
    sk_payload = _pwhl_fetch_players_payload(
        pwhl=pwhl,
        season_id=season_id,
        position="skaters",
        allow_network=allow_network,
        local_file=PWHL_SKATER_STATS_FILE,
    )
    gl_payload = _pwhl_fetch_players_payload(
        pwhl=pwhl,
        season_id=season_id,
        position="goalies",
        allow_network=allow_network,
        local_file=PWHL_GOALIE_STATS_FILE,
    )

    for row in _pwhl_extract_player_rows(sk_payload):
        raw_name = unescape(_player_name(_pwhl_pick_row_value(row, "name", "player_name", "full_name", "playerName")))
        name = raw_name.strip()
        if not name or name in {"&nbsp;", "\xa0"}:
            continue
        team = _norm_pwhl_code(str(_pwhl_pick_row_value(row, "team_code", "team", "team_abbrev", "teamCode") or ""))
        pid = _safe_int(_pwhl_pick_row_value(row, "player_id", "playerId", "id"))
        store_name = _pwhl_unique_name(skaters, name, team)
        skaters[store_name] = {
            "_pid": pid,
            "team": team,
            "Goals": _safe_float(_pwhl_pick_row_value(row, "goals", "g")),
            "Assists": _safe_float(_pwhl_pick_row_value(row, "assists", "a")),
            "Points": _safe_float(_pwhl_pick_row_value(row, "points", "pts")),
            "Shots": _safe_float(_pwhl_pick_row_value(row, "shots", "shot", "shots_on_goal")),
            "Hits": _safe_float(_pwhl_pick_row_value(row, "hits")),
            "Blocks": _safe_float(_pwhl_pick_row_value(row, "shots_blocked_by_player", "blocked_shots", "blocks")),
            "+/-": _safe_float(_pwhl_pick_row_value(row, "plus_minus", "plusMinus")),
            "PIM": _safe_float(_pwhl_pick_row_value(row, "penalty_minutes", "pim")),
        }

    for row in _pwhl_extract_player_rows(gl_payload):
        raw_name = unescape(_player_name(_pwhl_pick_row_value(row, "name", "player_name", "full_name", "playerName")))
        name = raw_name.strip()
        if not name or name in {"&nbsp;", "\xa0"}:
            continue
        team = _norm_pwhl_code(str(_pwhl_pick_row_value(row, "team_code", "team", "team_abbrev", "teamCode") or ""))
        pid = _safe_int(_pwhl_pick_row_value(row, "player_id", "playerId", "id"))
        save_pct = _safe_float(_pwhl_pick_row_value(row, "save_percentage", "save_pct", "savePct", "sv_pct", "savePctg"))
        if save_pct > 1.0:
            save_pct /= 100.0
        saves = _safe_float(_pwhl_pick_row_value(row, "saves", "save_total", "saveTotal", "sv"))
        gs = _safe_float(_pwhl_pick_row_value(row, "games_started", "gamesStarted", "games_played", "gp", "starts"))
        store_name = _pwhl_unique_name(goalies, name, team)
        goalies[store_name] = {
            "_pid": pid,
            "team": team,
            "Wins": _safe_float(_pwhl_pick_row_value(row, "wins", "w", "win")),
            "Losses": _safe_float(_pwhl_pick_row_value(row, "losses", "l", "loss")),
            "OTL": _safe_float(_pwhl_pick_row_value(row, "ot_losses", "otlosses", "otl", "overtime_losses")),
            "Shutouts": _safe_float(_pwhl_pick_row_value(row, "shutouts", "so")),
            "Save %": max(0.0, min(1.0, save_pct)),
            "Saves": saves,
            "Games Started": gs,
            "Saves / GS": (saves / gs) if gs > 0.0 else 0.0,
            "GAA": _safe_float(_pwhl_pick_row_value(row, "goals_against_avg", "goals_against_average", "gaa")),
        }
    return skaters, goalies


def _should_refresh_player_cache(league_u: str, nhl: NHLApi, pwhl: PWHLApi, today: dt.date) -> bool:
    now = dt.datetime.now(APP_TZ)
    if league_u == "NHL":
        games = _iter_nhl_games(nhl, today)
    else:
        games = _iter_pwhl_games(pwhl, today)
    for g in games:
        if _game_is_final(g):
            continue
        st = str(g.get("gameState") or g.get("gameStatus") or "").upper()
        if st in {"LIVE", "CRIT"}:
            return True
        s = g.get("startTimeUTC") or g.get("startTime")
        if isinstance(s, str) and s:
            ss = s[:-1] + "+00:00" if s.endswith("Z") else s
            try:
                dtu = dt.datetime.fromisoformat(ss)
                if dtu.tzinfo is None:
                    dtu = dtu.replace(tzinfo=dt.timezone.utc)
                if dtu.astimezone(APP_TZ) <= now:
                    return True
            except Exception:
                pass
    return False


def populate_player_stats_tab(
    parent: tk.Frame,
    *,
    league: str,
    logo_bank: Any,
    get_selected_team_code: Callable[[], str | None],
    set_selected_team_code: Callable[[str | None], None] | None = None,
) -> dict[str, Callable[[], None]]:
    _ = get_selected_team_code, set_selected_team_code
    for c in parent.winfo_children():
        c.destroy()

    bg = "#262626"
    card_bg = "#4a4a4a"
    fg = "#f0f0f0"
    muted = "#d8d8d8"
    parent.configure(bg=bg)

    cache = DiskCache(nhl_dir(SEASON))
    nhl = NHLApi(cache)
    pwhl = PWHLApi(DiskCache(pwhl_dir(SEASON)))
    league_u = str(league or "NHL").upper()
    today = END_DATE
    season_id = _season_compact_id(SEASON)
    headshot_root = pwhl_dir(SEASON) if league_u == "PWHL" else nhl_dir(SEASON)
    headshot_dir = headshot_root / "headshots"
    # Versioned cache key so stale payloads from earlier stat extraction logic do not persist.
    key = f"player_stats/{league_u}/latest_v10"

    top = tk.Frame(parent, bg=bg)
    top.pack(fill="x", padx=12, pady=(8, 6))
    date_lbl = tk.Label(top, text="", bg=bg, fg=fg, font=("TkDefaultFont", 22))
    date_lbl.pack(side="top", pady=(0, 4))

    body = tk.Frame(parent, bg=bg)
    body.pack(fill="both", expand=True, padx=12, pady=(4, 12))
    body.grid_columnconfigure(0, weight=1)
    body.grid_columnconfigure(1, weight=1)
    body.grid_rowconfigure(0, weight=1)

    left = tk.Frame(body, bg=card_bg, bd=0, highlightthickness=0)
    right = tk.Frame(body, bg=card_bg, bd=0, highlightthickness=0)
    left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
    right.grid(row=0, column=1, sticky="nsew", padx=(10, 0))

    skater_stat = tk.StringVar(value="All")
    goalie_stat = tk.StringVar(value="All")

    def _panel_header(panel: tk.Frame, title: str, var: tk.StringVar, opts: list[str]) -> None:
        head = tk.Frame(panel, bg=card_bg)
        head.pack(fill="x", padx=12, pady=(10, 4))
        choose = ttk.Combobox(head, textvariable=var, values=opts, state="readonly", width=16)
        choose.grid(row=0, column=0, sticky="w")
        lbl = tk.Label(head, text=title, bg=card_bg, fg=fg, font=("TkDefaultFont", 22))
        lbl.grid(row=0, column=1, sticky="ew")
        spacer = tk.Frame(head, bg=card_bg)
        spacer.grid(row=0, column=2, sticky="e")
        head.update_idletasks()
        head.grid_columnconfigure(1, weight=1)
        head.grid_columnconfigure(2, minsize=max(1, int(choose.winfo_reqwidth())))

    _panel_header(left, "Skaters", skater_stat, SKATER_CHOICES)
    _panel_header(right, "Goalies", goalie_stat, GOALIE_CHOICES)

    def _make_scroll_rows(parent_panel: tk.Frame) -> tuple[tk.Canvas, tk.Frame]:
        wrap = tk.Frame(parent_panel, bg=card_bg)
        wrap.pack(fill="both", expand=True, padx=16, pady=(8, 18))
        canvas = tk.Canvas(wrap, bg=card_bg, highlightthickness=0, bd=0)
        vbar = ttk.Scrollbar(wrap, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=card_bg)
        win = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=vbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        vbar.pack(side="right", fill="y")

        def _on_inner_configure(_e=None):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _on_canvas_configure(e):
            canvas.itemconfigure(win, width=max(1, e.width))

        inner.bind("<Configure>", _on_inner_configure)
        canvas.bind("<Configure>", _on_canvas_configure)
        return canvas, inner

    skater_canvas, skater_rows = _make_scroll_rows(left)
    goalie_canvas, goalie_rows = _make_scroll_rows(right)

    live_imgs: list[Any] = []
    payload_state: dict[str, Any] = {"data": None}
    headshot_memo: dict[tuple[str, int, int], Any] = {}
    headshot_failed: set[tuple[str, int]] = set()

    def _clear_rows(frame: tk.Frame) -> None:
        for c in frame.winfo_children():
            c.destroy()

    def _draw_card_tile(frame: tk.Frame, *, vals: dict[str, Any], team_code: str, name: str, value: str) -> None:
        row = tk.Frame(frame, bg=card_bg)
        pid = _safe_int(vals.get("_pid"))
        himg = _headshot_for_player(
            league=league_u,
            pid=pid,
            team_code=team_code,
            season_id=season_id,
            cache_dir=headshot_dir,
            memo=headshot_memo,
            failed=headshot_failed,
            master=frame,
            width=144,
            max_height=_headshot_max_height_for_team(team_code, 160),
            allow_network=(league_u in {"NHL", "PWHL"}),
        )
        logo = _logo_for_team(team_code, logo_bank, league=league_u, height=64, master=frame)
        if himg is not None:
            live_imgs.append(himg)
        if logo is not None:
            live_imgs.append(logo)
        if himg is not None:
            badge = _draw_headshot_stack(
                row,
                headshot=himg,
                logo=logo,
                head_w=int(himg.width()),
                head_h=int(himg.height()),
                logo_w=int(logo.width()) if logo is not None else 0,
                logo_h=int(logo.height()) if logo is not None else 0,
                bg=card_bg,
            )
            badge.pack(pady=(0, 4))
        tk.Label(row, text=name, bg=card_bg, fg=fg, font=("TkDefaultFont", 14)).pack()
        tk.Label(row, text=value, bg=card_bg, fg=fg, font=("TkDefaultFont", 22)).pack()
        row.pack(fill="both", expand=True)

    def _draw_table_row(frame: tk.Frame, *, vals: dict[str, Any], team_code: str, name: str, value: str) -> None:
        row = tk.Frame(frame, bg=card_bg)
        row.pack(fill="x", pady=4)
        pid = _safe_int(vals.get("_pid"))
        himg = _headshot_for_player(
            league=league_u,
            pid=pid,
            team_code=team_code,
            season_id=season_id,
            cache_dir=headshot_dir,
            memo=headshot_memo,
            failed=headshot_failed,
            master=frame,
            width=116,
            max_height=_headshot_max_height_for_team(team_code, 126),
            allow_network=(league_u in {"NHL", "PWHL"}),
        )
        logo = _logo_for_team(team_code, logo_bank, league=league_u, height=52, master=frame)
        if himg is not None:
            live_imgs.append(himg)
        if logo is not None:
            live_imgs.append(logo)
        if himg is not None:
            badge = _draw_headshot_stack(
                row,
                headshot=himg,
                logo=logo,
                head_w=int(himg.width()),
                head_h=int(himg.height()),
                logo_w=int(logo.width()) if logo is not None else 0,
                logo_h=int(logo.height()) if logo is not None else 0,
                bg=card_bg,
            )
            badge.pack(side="left", padx=(0, 8))
        tk.Label(row, text=name, bg=card_bg, fg=fg, font=("TkDefaultFont", 16), anchor="w").pack(side="left", fill="x", expand=True, padx=(8, 0))
        tk.Label(row, text=value, bg=card_bg, fg=fg, font=("TkDefaultFont", 16, "bold"), anchor="e").pack(side="right")

    def _fmt_val(stat: str, v: float) -> str:
        if stat in {"Save %"}:
            return f"{v:.3f}"
        if stat in {"Saves / GS"}:
            return f"{v:.2f}"
        if stat in {"GAA"}:
            return f"{v:.2f}"
        return str(int(round(v)))

    def _load_or_refresh() -> dict[str, Any]:
        should_refresh = _should_refresh_player_cache(league_u, nhl, pwhl, today)
        hit_raw = cache.get_json(key, ttl_s=None)
        hit = hit_raw if _player_payload_is_usable(hit_raw, league=league_u) else None
        if isinstance(hit, dict) and not should_refresh:
            try:
                write_player_stats_xml(
                    season=SEASON,
                    league=league_u,
                    payload=hit,
                )
            except Exception:
                pass
            return hit
        xml_raw = read_player_stats_xml(season=SEASON, league=league_u)
        xml_hit = xml_raw if _player_payload_is_usable(xml_raw, league=league_u) else None
        if isinstance(xml_hit, dict) and not should_refresh:
            try:
                cache.set_json(key, xml_hit)
            except Exception:
                pass
            return xml_hit
        allow_network = should_refresh or not isinstance(hit, dict) or not isinstance(xml_hit, dict)
        if league_u == "NHL":
            # Prefer NHL leaders endpoints for cleaner current-season leaderboard data.
            sk, gl = _aggregate_nhl_player_stats_from_leaders(
                cache=cache,
                season=SEASON,
                allow_network=allow_network,
                limit=TOP_N_LIST,
            )
            # Backfill secondary stat categories that leaders feeds may omit.
            fb_sk, fb_gl = _aggregate_nhl_player_stats(
                nhl=nhl,
                cache=cache,
                allow_network=allow_network,
                dmin=START_DATE,
                dmax=today,
            )
            _backfill_missing_nhl_stats_from_aggregate(
                target_skaters=sk,
                target_goalies=gl,
                fallback_skaters=fb_sk,
                fallback_goalies=fb_gl,
            )
            # Fallback to game-by-game aggregate if leaders payload is unavailable.
            if not sk and not gl:
                sk, gl = fb_sk, fb_gl
        else:
            sk, gl = _aggregate_pwhl_player_stats(
                pwhl=pwhl,
                dmin=START_DATE,
                dmax=today,
                allow_network=allow_network,
            )
        out = {
            "date": today.isoformat(),
            "league": league_u,
            "skaters": sk,
            "goalies": gl,
            "updated": dt.datetime.now(APP_TZ).strftime("%-m/%-d %H:%M:%S"),
        }
        if _player_payload_is_usable(out, league=league_u):
            cache.set_json(key, out)
            try:
                write_player_stats_xml(
                    season=SEASON,
                    league=league_u,
                    payload=out,
                )
            except Exception:
                pass
            return out
        if isinstance(hit, dict):
            return hit
        if isinstance(xml_hit, dict):
            return xml_hit
        return out

    def _render_side(frame: tk.Frame, data: dict[str, dict[str, Any]], chosen: str, *, defaults: list[str]) -> None:
        if chosen == "All":
            for stat in defaults:
                tk.Label(frame, text=stat, bg=card_bg, fg=muted, font=("TkDefaultFont", 16)).pack(anchor="w", pady=(0, 6))
                items = sorted(
                    data.items(),
                    key=lambda kv: _safe_float(kv[1].get(stat)),
                    reverse=True,
                )[:3]
                if not items:
                    tk.Label(frame, text="No data", bg=card_bg, fg=muted).pack(anchor="w")
                tiles = tk.Frame(frame, bg=card_bg)
                tiles.pack(fill="x", pady=(0, 16))
                for col in range(3):
                    tiles.grid_columnconfigure(col, weight=1)
                for col, (name, vals) in enumerate(items):
                    cell = tk.Frame(tiles, bg=card_bg)
                    cell.grid(row=0, column=col, sticky="nsew", padx=6)
                    _draw_card_tile(
                        cell,
                        vals=vals,
                        team_code=str(vals.get("team") or ""),
                        name=name,
                        value=_fmt_val(stat, _safe_float(vals.get(stat))),
                    )
        else:
            tk.Label(frame, text=chosen, bg=card_bg, fg=muted, font=("TkDefaultFont", 16)).pack(anchor="w", pady=(0, 6))
            items = sorted(
                data.items(),
                key=lambda kv: _safe_float(kv[1].get(chosen)),
                reverse=True,
            )[:TOP_N_LIST]
            if not items:
                tk.Label(frame, text="No data", bg=card_bg, fg=muted).pack(anchor="w")
            for name, vals in items:
                _draw_table_row(
                    frame,
                    vals=vals,
                    team_code=str(vals.get("team") or ""),
                    name=name,
                    value=_fmt_val(chosen, _safe_float(vals.get(chosen))),
                )

    error_state = {"shown": False}

    def _render_error(msg: str) -> None:
        _clear_rows(skater_rows)
        _clear_rows(goalie_rows)
        tk.Label(
            skater_rows,
            text="Player stats failed to load.",
            bg=card_bg,
            fg=muted,
            font=("TkDefaultFont", 14),
        ).pack(anchor="w", pady=(4, 6))
        tk.Label(
            skater_rows,
            text=msg,
            bg=card_bg,
            fg=muted,
            font=("TkDefaultFont", 11),
            wraplength=360,
            justify="left",
        ).pack(anchor="w")
        if not error_state["shown"]:
            error_state["shown"] = True
            messagebox.showerror("Player Stats Error", msg)

    def _render() -> None:
        try:
            _clear_rows(skater_rows)
            _clear_rows(goalie_rows)
            live_imgs.clear()
            payload = payload_state.get("data")
            if not isinstance(payload, dict):
                payload = _load_or_refresh()
                payload_state["data"] = payload
            dlabel = _payload_iso_date_or_today(payload, today)
            date_lbl.configure(text=f"{dlabel.day} {dlabel.strftime('%B %Y')}")
            skaters = payload.get("skaters") if isinstance(payload.get("skaters"), dict) else {}
            goalies = payload.get("goalies") if isinstance(payload.get("goalies"), dict) else {}
            _render_side(skater_rows, skaters, skater_stat.get(), defaults=SKATER_CHOICES[1:])
            _render_side(goalie_rows, goalies, goalie_stat.get(), defaults=GOALIE_CHOICES[1:])
        except Exception as exc:
            msg = f"{type(exc).__name__}: {exc}"
            print(f"Player stats render failed: {msg}", file=sys.stderr)
            _render_error(msg)

    skater_stat.trace_add("write", lambda *_: _render())
    goalie_stat.trace_add("write", lambda *_: _render())
    _render()

    def _install_wheel_scrolling(target_canvas: tk.Canvas) -> None:
        def _step(delta: int) -> str:
            target_canvas.yview_scroll(delta, "units")
            return "break"

        def _on_mousewheel(event):
            raw = int(getattr(event, "delta", 0))
            if raw == 0:
                return "break"
            steps = -max(1, abs(raw) // 120)
            if raw > 0:
                steps = -1 * max(1, abs(raw) // 120)
            else:
                steps = max(1, abs(raw) // 120)
            return _step(steps)

        def _on_up(_event):
            return _step(-1)

        def _on_down(_event):
            return _step(1)

        def _bind_all(_e=None):
            target_canvas.bind_all("<MouseWheel>", _on_mousewheel, add="+")
            target_canvas.bind_all("<Button-4>", _on_up, add="+")
            target_canvas.bind_all("<Button-5>", _on_down, add="+")

        def _unbind_all(_e=None):
            try:
                target_canvas.unbind_all("<MouseWheel>")
                target_canvas.unbind_all("<Button-4>")
                target_canvas.unbind_all("<Button-5>")
            except Exception:
                pass

        target_canvas.bind("<Enter>", _bind_all, add="+")
        target_canvas.bind("<Leave>", _unbind_all, add="+")

    _install_wheel_scrolling(skater_canvas)
    _install_wheel_scrolling(goalie_canvas)

    def redraw() -> None:
        payload_state["data"] = None
        _render()

    def reset() -> None:
        skater_stat.set("All")
        goalie_stat.set("All")
        payload_state["data"] = None
        _render()

    return {"redraw": redraw, "reset": reset}
