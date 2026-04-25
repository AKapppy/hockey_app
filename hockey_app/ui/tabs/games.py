from __future__ import annotations

import csv
import datetime as dt
import html
import io
import json
import math
import re
import threading
import time
import tkinter as tk
import xml.etree.ElementTree as ET
import requests
from dataclasses import dataclass
from pathlib import Path
from collections import defaultdict
from tkinter import ttk
from tkinter import font as tkfont
from typing import Any, Optional, Protocol, TYPE_CHECKING, cast
from zoneinfo import ZoneInfo

from ...data.nhl_api import NHLApi
from ...data.paths import cache_dir
from ...data.xml_cache import read_games_day_xml, write_games_day_xml

try:
    from PIL import Image, ImageTk  # type: ignore
    _PIL_OK = True
except Exception:
    Image = None  # type: ignore[assignment]
    ImageTk = None  # type: ignore[assignment]
    _PIL_OK = False

# Optional: type-only import to keep Pylance happy without runtime hard dependency.
if TYPE_CHECKING:
    from hockey_app.ui.components.logo_bank import LogoBank
else:
    class LogoBank(Protocol):
        def get(self, code: str, *, height: int, dim: bool = False, dim_amt: float = 0.55) -> Any: ...


# ---- look & feel ----
BG = "#2c2c2c"
CARD_BG = "#444444"
FG = "#f0f0f0"
MUTED = "#d7d7d7"
STEP_BTN_BG = "#3a3a3a"
STEP_BTN_HOVER = "#444444"
STEP_BTN_FG = "#f0f0f0"

# Auto-refresh is enabled for today when games are not finalized.
CARD_RATIO = 2.35  # width / height
CARD_GAP_X = 22
CARD_GAP_Y = 22
FLAGS_DIR = Path(__file__).resolve().parents[2] / "assets" / "iihf_logos"
PWHL_LOGOS_DIR = Path(__file__).resolve().parents[2] / "assets" / "pwhl_logos"

# Visual balancing for marks with unusually wide/tall negative space.
LOGO_VISUAL_SCALE: dict[str, float] = {
    "PHI": 0.90,
    "NSH": 1.12,
    "WSH": 1.10,
}

_FLAG_IMG_CACHE: dict[tuple[str, int], Any] = {}
_FLAG_AR_CACHE: dict[str, float] = {}
_PWHL_IMG_CACHE: dict[tuple[str, int], Any] = {}
_PWHL_AR_CACHE: dict[str, float] = {}
COUNTRY_CODE_ALIASES: dict[str, str] = {
    "CH": "SUI",
    "FR": "FRA",
    "CZ": "CZE",
    "UK": "GBR",
}
COUNTRY_FILE_ALIASES: dict[str, tuple[str, ...]] = {
    "SUI": ("CH",),
    "FRA": ("FR",),
    "CZE": ("CZ",),
    "SVK": ("SK",),
    "SWE": ("SE",),
    "GER": ("DE",),
    "DEN": ("DK",),
    "LAT": ("LV",),
    "FIN": ("FI",),
    "ITA": ("IT",),
    "USA": ("US",),
    "CAN": ("CA",),
}
NHL_TEAM_CODES: set[str] = {
    "ANA", "BOS", "BUF", "CAR", "CBJ", "CGY", "CHI", "COL",
    "DAL", "DET", "EDM", "FLA", "LAK", "MIN", "MTL", "NJD",
    "NSH", "NYI", "NYR", "OTT", "PHI", "PIT", "SEA", "SJS",
    "STL", "TBL", "TOR", "UTA", "VAN", "VGK", "WSH", "WPG",
}
PWHL_CODE_ALIASES: dict[str, str] = {
    "MON": "MTL",
    "NYC": "NY",
}
MONEYPUCK_PREDICTIONS_URL = "https://moneypuck.com/moneypuck/predictions/"
MONEYPUCK_GAMEDATA_URL = "https://moneypuck.com/moneypuck/gameData"
MONEYPUCK_PRED_TIMEOUT_S = 6
MONEYPUCK_GAMEDATA_TIMEOUT_S = 3
MONEYPUCK_RETRY_S = 20.0
MONEYPUCK_GAMEDATA_LIVE_TTL_S = 20
NHL_STANDINGS_RETRY_S = 30.0
NHL_STANDINGS_LIVE_TTL_S = 120
MONEYPUCK_HEADERS: dict[str, str] = {
    # MoneyPuck gameData CSV can be Cloudflare-protected for non-browser clients.
    # A browser-like header profile keeps direct CSV access stable.
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7_2) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/133.0.0.0 Safari/537.36"
    ),
    "Accept": "text/csv,*/*;q=0.9",
    "Referer": "https://moneypuck.com/",
}
MONEYPUCK_NHL_TEAM_ALIASES: dict[str, tuple[str, ...]] = {
    "ANA": ("ANA", "ANAHEIM", "ANAHEIM DUCKS", "DUCKS"),
    "BOS": ("BOS", "BOSTON", "BOSTON BRUINS", "BRUINS"),
    "BUF": ("BUF", "BUFFALO", "BUFFALO SABRES", "SABRES"),
    "CAR": ("CAR", "CAROLINA", "CAROLINA HURRICANES", "HURRICANES", "CANES"),
    "CBJ": ("CBJ", "COLUMBUS", "COLUMBUS BLUE JACKETS", "BLUE JACKETS"),
    "CGY": ("CGY", "CALGARY", "CALGARY FLAMES", "FLAMES"),
    "CHI": ("CHI", "CHICAGO", "CHICAGO BLACKHAWKS", "BLACKHAWKS", "HAWKS"),
    "COL": ("COL", "COLORADO", "COLORADO AVALANCHE", "AVALANCHE", "AVS"),
    "DAL": ("DAL", "DALLAS", "DALLAS STARS", "STARS"),
    "DET": ("DET", "DETROIT", "DETROIT RED WINGS", "RED WINGS"),
    "EDM": ("EDM", "EDMONTON", "EDMONTON OILERS", "OILERS"),
    "FLA": ("FLA", "FLORIDA", "FLORIDA PANTHERS", "PANTHERS"),
    "LAK": ("LAK", "LOS ANGELES", "LOS ANGELES KINGS", "KINGS"),
    "MIN": ("MIN", "MINNESOTA", "MINNESOTA WILD", "WILD"),
    "MTL": ("MTL", "MONTREAL", "MONTREAL CANADIENS", "CANADIENS", "HABS"),
    "NJD": ("NJD", "NEW JERSEY", "NEW JERSEY DEVILS", "DEVILS"),
    "NSH": ("NSH", "NASHVILLE", "NASHVILLE PREDATORS", "PREDATORS", "PREDS"),
    "NYI": ("NYI", "NEW YORK ISLANDERS", "ISLANDERS", "NY ISLANDERS"),
    "NYR": ("NYR", "NEW YORK RANGERS", "RANGERS", "NY RANGERS"),
    "OTT": ("OTT", "OTTAWA", "OTTAWA SENATORS", "SENATORS"),
    "PHI": ("PHI", "PHILADELPHIA", "PHILADELPHIA FLYERS", "FLYERS"),
    "PIT": ("PIT", "PITTSBURGH", "PITTSBURGH PENGUINS", "PENGUINS", "PENS"),
    "SEA": ("SEA", "SEATTLE", "SEATTLE KRAKEN", "KRAKEN"),
    "SJS": ("SJS", "SAN JOSE", "SAN JOSE SHARKS", "SHARKS"),
    "STL": ("STL", "ST LOUIS", "ST LOUIS BLUES", "BLUES"),
    "TBL": ("TBL", "TAMPA BAY", "TAMPA BAY LIGHTNING", "LIGHTNING"),
    "TOR": ("TOR", "TORONTO", "TORONTO MAPLE LEAFS", "MAPLE LEAFS"),
    "UTA": ("UTA", "UTAH", "UTAH HOCKEY CLUB", "UTAH MAMMOTH"),
    "VAN": ("VAN", "VANCOUVER", "VANCOUVER CANUCKS", "CANUCKS"),
    "VGK": ("VGK", "VEGAS", "VEGAS GOLDEN KNIGHTS", "GOLDEN KNIGHTS"),
    "WSH": ("WSH", "WASHINGTON", "WASHINGTON CAPITALS", "CAPITALS", "CAPS"),
    "WPG": ("WPG", "WINNIPEG", "WINNIPEG JETS", "JETS"),
}


def _moneypuck_norm_text(text: str) -> str:
    return re.sub(r"[^A-Z0-9]+", " ", str(text or "").upper()).strip()


def _moneypuck_strip_html(fragment: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", str(fragment or ""))
    text = re.sub(r"(?is)<br\s*/?>", " ", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


MONEYPUCK_ALIAS_TO_CODE: dict[str, str] = {}
for _code, _aliases in MONEYPUCK_NHL_TEAM_ALIASES.items():
    for _alias in _aliases:
        _norm = _moneypuck_norm_text(_alias)
        if _norm:
            MONEYPUCK_ALIAS_TO_CODE.setdefault(_norm, _code)


def _moneypuck_team_codes_in_text(text: str) -> list[str]:
    norm = _moneypuck_norm_text(text)
    if not norm:
        return []
    wrapped = f" {norm} "
    found: dict[str, int] = {}
    for alias, code in MONEYPUCK_ALIAS_TO_CODE.items():
        needle = f" {alias} "
        pos = wrapped.find(needle)
        if pos < 0:
            continue
        cur = found.get(code)
        if cur is None or pos < cur:
            found[code] = pos
    return [code for code, _ in sorted(found.items(), key=lambda kv: kv[1])]


def _moneypuck_parse_row_date(text: str, *, selected_date: dt.date) -> Optional[dt.date]:
    match = re.search(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b", str(text or ""))
    if not match:
        return None
    month = int(match.group(1))
    day = int(match.group(2))
    year_token = match.group(3)
    if year_token is not None:
        year = int(year_token)
        if year < 100:
            year += 2000
    else:
        year = selected_date.year
        if selected_date.month <= 6 and month >= 9:
            year -= 1
    try:
        return dt.date(year, month, day)
    except Exception:
        return None


def _parse_moneypuck_prediction_rows(
    html_text: str,
    *,
    selected_date: dt.date,
) -> list[tuple[Optional[dt.date], str, float, str, float]]:
    out: list[tuple[Optional[dt.date], str, float, str, float]] = []
    rows = re.findall(r"(?is)<tr[^>]*>.*?</tr>", str(html_text or ""))
    for row_html in rows:
        cells = re.findall(r"(?is)<t[dh][^>]*>(.*?)</t[dh]>", row_html)
        if not cells:
            cells = [row_html]
        team_pos: dict[str, int] = {}
        pct_pos: list[tuple[int, float]] = []
        text_bits: list[str] = []
        for idx, raw_cell in enumerate(cells):
            cell = _moneypuck_strip_html(raw_cell)
            if not cell:
                continue
            text_bits.append(cell)
            for code in _moneypuck_team_codes_in_text(cell):
                team_pos.setdefault(code, idx)
            for m in re.finditer(r"(\d{1,3}(?:\.\d+)?)\s*%", cell):
                try:
                    pct = float(m.group(1))
                except Exception:
                    continue
                if 0.0 <= pct <= 100.0:
                    pct_pos.append((idx, pct))
        if len(team_pos) < 2 or len(pct_pos) < 2:
            continue
        ordered = sorted(team_pos.items(), key=lambda kv: kv[1])[:2]
        picked_codes = [ordered[0][0], ordered[1][0]]
        remaining = list(pct_pos)
        team_to_pct: dict[str, float] = {}
        for code in picked_codes:
            idx = team_pos[code]
            nearest = min(remaining, key=lambda item: (abs(item[0] - idx), item[0]))
            team_to_pct[code] = nearest[1]
            remaining.remove(nearest)
        if len(team_to_pct) < 2:
            continue
        row_date = _moneypuck_parse_row_date(" ".join(text_bits), selected_date=selected_date)
        out.append(
            (
                row_date,
                picked_codes[0],
                team_to_pct[picked_codes[0]],
                picked_codes[1],
                team_to_pct[picked_codes[1]],
            )
        )
    return out


def _download_moneypuck_predictions_html(selected_date: dt.date) -> str:
    urls = [
        f"{MONEYPUCK_PREDICTIONS_URL}?date={selected_date.isoformat()}",
        f"{MONEYPUCK_PREDICTIONS_URL}?date={selected_date.strftime('%Y%m%d')}",
        MONEYPUCK_PREDICTIONS_URL,
    ]
    for url in urls:
        try:
            resp = requests.get(url, headers=MONEYPUCK_HEADERS, timeout=MONEYPUCK_PRED_TIMEOUT_S)
            if int(resp.status_code) >= 400:
                continue
            text = str(resp.text or "")
            if text:
                return text
        except Exception:
            continue
    return ""


def _parse_moneypuck_season_text(season_text: str) -> Optional[tuple[int, int]]:
    txt = str(season_text or "").strip()
    m = re.fullmatch(r"(\d{4})-(\d{4})", txt)
    if m:
        return int(m.group(1)), int(m.group(2))
    m2 = re.fullmatch(r"(\d{4})-(\d{2})", txt)
    if m2:
        y0 = int(m2.group(1))
        y1 = (y0 // 100) * 100 + int(m2.group(2))
        if y1 < y0:
            y1 += 100
        return y0, y1
    return None


def _moneypuck_season_candidates_for_game(
    *,
    season_text: str,
    selected_date: dt.date,
    game_id: int,
) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()

    def _add(y0: int, y1: int) -> None:
        key = f"{int(y0):04d}{int(y1):04d}"
        if key not in seen:
            seen.add(key)
            out.append(key)

    parsed = _parse_moneypuck_season_text(season_text)
    if parsed is not None:
        _add(parsed[0], parsed[1])

    gid_txt = str(int(game_id)) if int(game_id) > 0 else ""
    if len(gid_txt) >= 4 and gid_txt[:4].isdigit():
        y0 = int(gid_txt[:4])
        _add(y0, y0 + 1)

    y0_date = selected_date.year if selected_date.month >= 7 else (selected_date.year - 1)
    _add(y0_date, y0_date + 1)
    _add(y0_date - 1, y0_date)
    _add(y0_date + 1, y0_date + 2)

    return out


def _moneypuck_gamedata_csv_url(season_compact: str, game_id: int) -> str:
    return f"{MONEYPUCK_GAMEDATA_URL}/{str(season_compact).strip()}/{int(game_id)}.csv"


def _parse_latest_game_data_win_probs(csv_text: str) -> Optional[tuple[float, float]]:
    if not csv_text:
        return None
    try:
        reader = csv.DictReader(io.StringIO(csv_text))
    except Exception:
        return None

    def _to_prob(raw: Any) -> Optional[float]:
        s = str(raw or "").strip()
        if not s:
            return None
        try:
            v = float(s)
        except Exception:
            return None
        if v < 0.0:
            return None
        if v > 1.0:
            if v <= 100.0:
                v /= 100.0
            else:
                return None
        return max(0.0, min(1.0, v))

    latest_pair: Optional[tuple[float, float]] = None
    for row in reader:
        if not isinstance(row, dict):
            continue
        a = _to_prob(row.get("liveAwayTeamWinOverallScore"))
        h = _to_prob(row.get("liveHomeTeamWinOverallScore"))
        if a is None or h is None:
            h_alt = _to_prob(row.get("homeWinProbability"))
            if h_alt is not None:
                h = h_alt
                a_alt = _to_prob(row.get("awayWinProbability"))
                a = a_alt if a_alt is not None else max(0.0, min(1.0, 1.0 - h_alt))
        if a is None or h is None:
            continue
        total = float(a) + float(h)
        if total <= 0.0:
            continue
        if 0.90 <= total <= 1.10:
            pair = (float(a), float(h))
        else:
            pair = (
                max(0.0, min(1.0, float(a) / total)),
                max(0.0, min(1.0, float(h) / total)),
            )
        latest_pair = pair
    return latest_pair


def _moneypuck_elapsed_to_period_clock(raw_elapsed: Any) -> tuple[int, str]:
    txt = str(raw_elapsed or "").strip()
    if not txt:
        return 0, ""
    try:
        sec = int(float(txt))
    except Exception:
        return 0, ""
    if sec < 0:
        return 0, ""
    period = int(sec // 1200) + 1
    elapsed_in_period = int(sec % 1200)
    remaining = max(0, 1200 - elapsed_in_period)
    return period, f"{remaining // 60}:{remaining % 60:02d}"


def _moneypuck_period_label(period: int) -> str:
    p = int(period)
    if p <= 0:
        return ""
    if p == 4:
        return "OT"
    if p >= 5:
        return "SO"
    return _period_suffix(p)


def _moneypuck_event_team_code(row: dict[str, Any], *, away_code: str, home_code: str) -> str:
    side = str(row.get("team") or "").strip().upper()
    if side in {"AWAY", "VISITOR"}:
        return away_code
    if side == "HOME":
        return home_code
    desc_u = str(row.get("eventDescriptionRaw") or "").upper().strip()
    if desc_u.startswith(f"{away_code} "):
        return away_code
    if desc_u.startswith(f"{home_code} "):
        return home_code
    return ""


def _moneypuck_scorer_name_from_desc(desc: str) -> str:
    text = str(desc or "").strip()
    if not text:
        return ""
    m = re.search(
        r"#\d+\s+([A-Za-z][A-Za-z .'\-]{1,56}?)(?=\(|,|\bAssists?\b|\bUnassisted\b|\bWrist\b|\bBackhand\b|\bSnap\b|\bSlap\b|$)",
        text,
    )
    if m:
        raw = re.sub(r"\s+", " ", m.group(1).strip(" ,.-"))
        return raw.title() if raw.isupper() else raw
    return ""


def _penalty_minutes_from_text(text: str) -> int:
    raw = str(text or "").strip()
    if not raw:
        return 0
    m = re.search(r"\b(\d{1,2})\s*(?:min|minute|minutes)\b", raw, flags=re.IGNORECASE)
    if m is not None:
        try:
            return max(0, int(m.group(1)))
        except Exception:
            return 0
    return 0


def _parse_moneypuck_popup_fallback(
    csv_text: str,
    *,
    away_code: str,
    home_code: str,
) -> tuple[list[str], list[str], list[dict[str, Any]]]:
    if not csv_text:
        return [], [], []
    try:
        reader = csv.DictReader(io.StringIO(csv_text))
    except Exception:
        return [], [], []

    away_lines: list[str] = []
    home_lines: list[str] = []
    penalties: list[dict[str, Any]] = []

    for row in reader:
        if not isinstance(row, dict):
            continue
        event = str(row.get("event") or "").strip().upper()
        desc = str(row.get("eventDescriptionRaw") or "").strip()
        if not event and not desc:
            continue
        team_code = _moneypuck_event_team_code(row, away_code=away_code, home_code=home_code)
        period_num, clock_txt = _moneypuck_elapsed_to_period_clock(row.get("time"))
        period_txt = _moneypuck_period_label(period_num)
        full_clock = f"{period_txt} - {clock_txt}" if period_txt and clock_txt else (clock_txt or period_txt)

        if event == "GOAL":
            scorer = _moneypuck_scorer_name_from_desc(desc)
            if scorer:
                line = f"{scorer} ({full_clock})" if full_clock else scorer
                if team_code == away_code:
                    away_lines.append(line)
                elif team_code == home_code:
                    home_lines.append(line)

        if event == "PENL":
            mins = _penalty_minutes_from_text(desc)
            penalties.append(
                {
                    "period": period_num if period_num > 0 else 0,
                    "time": clock_txt or "[NF]",
                    "team": team_code or "[NF]",
                    "minutes": int(mins) if mins > 0 else 0,
                    "desc": desc or "[NF]",
                }
            )

    def _dedupe(values: list[str]) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for value in values:
            vv = str(value).strip()
            if not vv or vv in seen:
                continue
            seen.add(vv)
            out.append(vv)
        return out

    return _dedupe(away_lines), _dedupe(home_lines), penalties


def _odds_value_to_implied_prob(raw: Any) -> Optional[float]:
    s = str(raw or "").strip().upper()
    if not s:
        return None
    if s.endswith("%"):
        try:
            pct = float(s[:-1].strip())
            if 0.0 <= pct <= 100.0:
                return pct / 100.0
        except Exception:
            return None
    if re.fullmatch(r"[+-]\d+", s):
        try:
            n = int(s)
        except Exception:
            return None
        if n > 0:
            return 100.0 / (float(n) + 100.0)
        if n < 0:
            a = float(abs(n))
            return a / (a + 100.0)
        return None
    try:
        dec = float(s)
    except Exception:
        return None
    if dec <= 0.0:
        return None
    if dec <= 1.0:
        return max(0.0, min(1.0, dec))
    if dec >= 100.0:
        return None
    return 1.0 / dec


def _implied_probs_from_game_odds(game: dict[str, Any]) -> Optional[tuple[float, float]]:
    away = game.get("awayTeam") if isinstance(game.get("awayTeam"), dict) else {}
    home = game.get("homeTeam") if isinstance(game.get("homeTeam"), dict) else {}
    away_rows = away.get("odds") if isinstance(away.get("odds"), list) else []
    home_rows = home.get("odds") if isinstance(home.get("odds"), list) else []

    def _provider_prob_map(rows: list[Any]) -> tuple[dict[int, float], list[float]]:
        by_provider: dict[int, float] = {}
        loose: list[float] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            p = _odds_value_to_implied_prob(row.get("value"))
            if p is None:
                p = _odds_value_to_implied_prob(row.get("odds"))
            if p is None:
                p = _odds_value_to_implied_prob(row.get("line"))
            if p is None:
                p = _odds_value_to_implied_prob(row.get("moneyline"))
            if p is None:
                continue
            pid_raw = row.get("providerId")
            try:
                pid = int(float(pid_raw))
            except Exception:
                pid = -1
            if pid >= 0 and pid not in by_provider:
                by_provider[pid] = p
            else:
                loose.append(p)
        return by_provider, loose

    away_map, away_loose = _provider_prob_map(away_rows)
    home_map, home_loose = _provider_prob_map(home_rows)

    def _normalize(a: float, h: float) -> Optional[tuple[float, float]]:
        total = float(a) + float(h)
        if total <= 0:
            return None
        aa = max(0.0, float(a) / total)
        hh = max(0.0, float(h) / total)
        return aa, hh

    preferred_provider_ids = (9, 7, 3, 8, 6, 10, 2)
    for pid in preferred_provider_ids:
        if pid in away_map and pid in home_map:
            out = _normalize(away_map[pid], home_map[pid])
            if out is not None:
                return out
    common = sorted(set(away_map.keys()) & set(home_map.keys()))
    for pid in common:
        out = _normalize(away_map[pid], home_map[pid])
        if out is not None:
            return out
    if away_loose and home_loose:
        out = _normalize(away_loose[0], home_loose[0])
        if out is not None:
            return out
    return None


def _implied_probs_from_records(game: dict[str, Any]) -> Optional[tuple[float, float]]:
    away = game.get("awayTeam") if isinstance(game.get("awayTeam"), dict) else {}
    home = game.get("homeTeam") if isinstance(game.get("homeTeam"), dict) else {}

    def _points_pct(record_text: Any) -> Optional[float]:
        s = str(record_text or "").strip()
        m = re.fullmatch(r"(\d+)-(\d+)-(\d+)", s)
        if not m:
            return None
        wins = int(m.group(1))
        losses = int(m.group(2))
        otl = int(m.group(3))
        gp = wins + losses + otl
        if gp <= 0:
            return None
        pts = (2 * wins) + otl
        return float(pts) / float(2 * gp)

    away_ppct = _points_pct(away.get("record"))
    home_ppct = _points_pct(home.get("record"))
    if away_ppct is None or home_ppct is None:
        return None
    home_prob = 0.5 + ((home_ppct - away_ppct) * 0.90) + 0.04
    home_prob = max(0.01, min(0.99, float(home_prob)))
    away_prob = 1.0 - home_prob
    return away_prob, home_prob

def _fmt_big_date(d: dt.date) -> str:
    try:
        return d.strftime("%-d %B %Y")  # mac/linux
    except Exception:
        return d.strftime("%d %B %Y").lstrip("0")  # windows


def _fmt_updated_ts(ts: Optional[dt.datetime] = None) -> str:
    t = ts or dt.datetime.now()
    try:
        return t.strftime("%-m/%-d %H:%M:%S")
    except Exception:
        # Windows fallback
        return t.strftime("%m/%d %H:%M:%S").lstrip("0").replace("/0", "/")


def _fmt_updated_from_unix(ts: Optional[float]) -> str:
    if isinstance(ts, (int, float)) and ts > 0:
        return _fmt_updated_ts(dt.datetime.fromtimestamp(float(ts)))
    return _fmt_updated_ts()


def _fmt_short_date(d: dt.date) -> str:
    try:
        return d.strftime("%-m/%-d/%Y")
    except Exception:
        return d.strftime("%m/%d/%Y").replace("/0", "/")


def _period_suffix(n: int) -> str:
    return "1ST" if n == 1 else "2ND" if n == 2 else "3RD" if n == 3 else f"{n}TH"


def _format_live_status_from_text(status_text: str) -> Optional[str]:
    u = str(status_text or "").upper().strip()
    if not u:
        return None

    def _period_from_text(s: str) -> Optional[str]:
        if "OT" in s:
            return "OT"
        if "SO" in s:
            return "SO"
        m = re.search(r"\b([1-9])(?:ST|ND|RD|TH)\b", s)
        if m:
            return _period_suffix(int(m.group(1)))
        m = re.search(r"\bP(?:ERIOD)?\s*([1-9])\b", s)
        if m:
            return _period_suffix(int(m.group(1)))
        m = re.search(r"\b([1-9])\b", s)
        if m:
            return _period_suffix(int(m.group(1)))
        return None

    if "INTERMISSION" in u or u.startswith("END "):
        p = _period_from_text(u)
        return f"{p} INTERMISSION" if p else "INTERMISSION"

    def _is_zero_clock(t: str) -> bool:
        m = re.match(r"^\s*0*(\d):(\d{2})\s*$", str(t or ""))
        if not m:
            return False
        return int(m.group(1)) == 0 and int(m.group(2)) == 0

    tm = re.search(r"\b(\d{1,2}:\d{2})\b", u)
    if tm:
        p = _period_from_text(u)
        tval = tm.group(1)
        if _is_zero_clock(tval):
            return f"{p} INTERMISSION" if p else "INTERMISSION"
        return f"{p} - {tval}" if p else tval

    return None


def _game_state(g: dict[str, Any]) -> str:
    return str(g.get("gameState") or g.get("gameStatus") or "").upper().strip()


def _scores(g: dict[str, Any]) -> tuple[int, int, str, str]:
    away = g.get("awayTeam") or {}
    home = g.get("homeTeam") or {}
    away_code = str(away.get("abbrev") or away.get("abbreviation") or away.get("teamAbbrev") or "AWY")
    home_code = str(home.get("abbrev") or home.get("abbreviation") or home.get("teamAbbrev") or "HOM")
    away_score = int(away.get("score") or 0)
    home_score = int(home.get("score") or 0)
    return away_score, home_score, away_code, home_code


def _shots(g: dict[str, Any]) -> tuple[Optional[int], Optional[int]]:
    def _team_shots(team: dict[str, Any]) -> Optional[int]:
        for k in ("sog", "shotsOnGoal", "shots", "shots_on_goal", "shotsTotal", "shots_total"):
            if k in team and team.get(k) is not None:
                v = _to_int(team.get(k), default=-1)
                return v if v >= 0 else None
        tstats = team.get("teamStats")
        if isinstance(tstats, dict):
            for k in ("shotsOnGoal", "shots", "sog", "shotsTotal", "shots_total"):
                if k in tstats and tstats.get(k) is not None:
                    v = _to_int(tstats.get(k), default=-1)
                    return v if v >= 0 else None
        return None

    away = g.get("awayTeam") or {}
    home = g.get("homeTeam") or {}
    return _team_shots(away if isinstance(away, dict) else {}), _team_shots(home if isinstance(home, dict) else {})


def _parse_start_local(g: dict[str, Any], tz: ZoneInfo) -> Optional[dt.datetime]:
    s = g.get("startTimeUTC") or g.get("startTime") or None
    if not s:
        return None
    ss = str(s).strip()
    if ss.endswith("Z"):
        ss = ss[:-1] + "+00:00"
    try:
        dtu = dt.datetime.fromisoformat(ss)
    except Exception:
        return None
    if dtu.tzinfo is None:
        dtu = dtu.replace(tzinfo=ZoneInfo("UTC"))
    return dtu.astimezone(tz)


def _future_big_text(g: dict[str, Any], tz: ZoneInfo) -> str:
    st = _parse_start_local(g, tz)
    if st:
        try:
            return st.strftime("%-I:%M %p")  # mac
        except Exception:
            return st.strftime("%I:%M %p").lstrip("0")  # windows

    # PWHL feed often stores only a textual time in statusText (e.g. "7:00 PM EST").
    stxt = str(g.get("statusText") or "").strip().upper()
    m = re.search(r"\b(\d{1,2}:\d{2}\s*[AP]M)\b", stxt)
    if m:
        return m.group(1).replace("  ", " ")
    return "TBD"


def _final_status(g: dict[str, Any]) -> str:
    stxt = str(g.get("statusText") or "").strip()
    if stxt:
        up = stxt.upper()
        if "FINAL" in up:
            if "SO" in up:
                return "FINAL - SO"
            if "OT" in up:
                return "FINAL - OT"
            return "FINAL"
    pd = g.get("periodDescriptor") or {}
    ptype = str(pd.get("periodType") or "").upper().strip()
    if ptype in {"OT", "SO"}:
        return f"FINAL - {ptype}"
    return "FINAL"


def _live_status(g: dict[str, Any]) -> str:
    clock = g.get("clock") or {}
    in_int = bool(clock.get("inIntermission"))
    time_rem = str(clock.get("timeRemaining") or clock.get("time") or "").strip()

    pd = g.get("periodDescriptor") or {}
    pnum = pd.get("number")
    ptype = str(pd.get("periodType") or "").upper().strip()
    stxt = str(g.get("statusText") or "").strip()
    parsed = _format_live_status_from_text(stxt) if stxt else None

    def _is_zero_clock(t: str) -> bool:
        m = re.match(r"^\s*0*(\d):(\d{2})\s*$", str(t or ""))
        if not m:
            return False
        return int(m.group(1)) == 0 and int(m.group(2)) == 0

    # If upstream status explicitly says intermission, prefer it over clock.
    if parsed and "INTERMISSION" in parsed:
        return parsed

    if ptype in {"OT", "SO"}:
        if in_int:
            return f"{ptype} INTERMISSION"
        if time_rem:
            return f"{ptype} - {time_rem}"
        return ptype

    if isinstance(pnum, int):
        if in_int:
            return f"{_period_suffix(pnum)} INTERMISSION"
        if _is_zero_clock(time_rem):
            return f"{_period_suffix(pnum)} INTERMISSION"
        if time_rem:
            return f"{_period_suffix(pnum)} - {time_rem}"
        return f"{_period_suffix(pnum)} PERIOD"

    if parsed:
        return parsed
    if stxt:
        return stxt.upper()

    return "LIVE"


def _game_codes(g: dict[str, Any]) -> tuple[str, str]:
    away = g.get("awayTeam") or {}
    home = g.get("homeTeam") or {}
    a = str(away.get("abbrev") or away.get("abbreviation") or away.get("teamAbbrev") or "").upper()
    h = str(home.get("abbrev") or home.get("abbreviation") or home.get("teamAbbrev") or "").upper()
    return a, h


def _playoff_round_from_game(g: dict[str, Any]) -> Optional[int]:
    candidates = [
        g.get("playoffRound"),
        g.get("round"),
        (g.get("seriesStatus") or {}).get("round"),
        (g.get("playoffSeries") or {}).get("playoffRound"),
        (g.get("playoffSeries") or {}).get("round"),
    ]
    for v in candidates:
        try:
            if v is None:
                continue
            n = int(v)
            if 1 <= n <= 4:
                return n
        except Exception:
            continue
    return None


def _round_label(round_no: int) -> str:
    if round_no == 1:
        return "Round 1"
    if round_no == 2:
        return "Round 2"
    if round_no == 3:
        return "Conference Finals"
    if round_no == 4:
        return "Cup Final"
    return "Post-Season"


def _stage_label(
    games: list[dict[str, Any]],
    selected_date: dt.date,
    boundaries: Any,
) -> str:
    # Olympics: if scheduled games are all non-NHL country teams.
    if games:
        # Do not classify PWHL-only days as Olympics.
        leagues = [str(g.get("league") or "").upper() for g in games]
        if any(l == "PWHL" for l in leagues):
            return "Regular Season"
        codes = [c for g in games for c in _game_codes(g) if c]
        if codes and all(c not in NHL_TEAM_CODES and c != "TBD" for c in codes):
            return "Olympics"

    # Best-effort game-type detection.
    gt = None
    for g in games:
        gt = g.get("gameType") or g.get("gameTypeId") or g.get("gameTypeCode")
        if gt is not None:
            break
    s = str(gt).upper() if gt is not None else ""
    if s in {"1", "PR", "PRE", "PRESEASON"}:
        return "Preseason"
    if s in {"3", "P", "PO", "PLAYOFFS"}:
        rounds = [_playoff_round_from_game(g) for g in games]
        rounds = [r for r in rounds if r is not None]
        return _round_label(min(rounds)) if rounds else "Post-Season"

    # Date-boundary fallback for phase labeling when metadata is sparse.
    reg_end = getattr(boundaries, "regular_end", None)
    if reg_end is not None and selected_date > reg_end:
        rounds = [_playoff_round_from_game(g) for g in games]
        rounds = [r for r in rounds if r is not None]
        return _round_label(min(rounds)) if rounds else "Post-Season"

    return "Regular Season"


def _nhl_phase_label(games: list[dict[str, Any]], selected_date: dt.date, boundaries: Any) -> str:
    if not games:
        return "Regular Season"
    gt = None
    for g in games:
        gt = g.get("gameType") or g.get("gameTypeId") or g.get("gameTypeCode")
        if gt is not None:
            break
    s = str(gt).upper() if gt is not None else ""
    if s in {"1", "PR", "PRE", "PRESEASON"}:
        return "Pre-Season"
    if s in {"3", "P", "PO", "PLAYOFFS"}:
        rounds = [_playoff_round_from_game(g) for g in games]
        rounds = [r for r in rounds if r is not None]
        return _round_label(min(rounds)) if rounds else "Post-Season"

    reg_end = getattr(boundaries, "regular_end", None)
    if reg_end is not None and selected_date > reg_end:
        rounds = [_playoff_round_from_game(g) for g in games]
        rounds = [r for r in rounds if r is not None]
        return _round_label(min(rounds)) if rounds else "Post-Season"
    return "Regular Season"


def _olympics_division_label(items: list[dict[str, Any]], selected_date: dt.date) -> str:
    vals = []
    for g in items:
        d = _game_division_label(g, selected_date)
        if d in {"Men's", "Women's"}:
            vals.append(d)
    if not vals:
        return "Olympics"
    if all(v == "Women's" for v in vals):
        return "Women's"
    if all(v == "Men's" for v in vals):
        return "Men's"
    return "Mixed"


def _olympic_division_from_text(text: str, *, default: str = "Olympic") -> str:
    tl = str(text or "").lower()
    tl = tl.replace("’", "'")
    # Strong phrase matches are more reliable than generic word hits.
    has_w_phrase = bool(
        re.search(r"\b(women|women's|womens)\s+(ice\s+)?hockey\b", tl)
        or re.search(r"\bolympic(s)?[-\s](women|womens)\b", tl)
        or re.search(r"\b(women|womens)[-\s]olympic(s)?\b", tl)
    )
    has_m_phrase = bool(
        re.search(r"\b(men|men's|mens)\s+(ice\s+)?hockey\b", tl)
        or re.search(r"\bolympic(s)?[-\s](men|mens)\b", tl)
        or re.search(r"\b(men|mens)[-\s]olympic(s)?\b", tl)
    )
    if has_w_phrase and not has_m_phrase:
        return "Women's"
    if has_m_phrase and not has_w_phrase:
        return "Men's"

    women_pat = re.compile(r"\b(women|women's|womens|female|femmes?)\b")
    men_pat = re.compile(r"\b(men|men's|mens|male|hommes?)\b")
    women_hits = list(women_pat.finditer(tl))
    men_hits = list(men_pat.finditer(tl))
    if women_hits and not men_hits:
        return "Women's"
    if men_hits and not women_hits:
        return "Men's"
    if women_hits and men_hits:
        # Mixed text can occur when unrelated blurbs mention both divisions.
        # Keep explicit/default label rather than guessing and risking flips.
        if str(default).strip() in {"Men's", "Women's"}:
            return str(default).strip()
        return default
    return default


def _infer_olympic_division(g: dict[str, Any]) -> str:
    return _olympic_division_from_text(" | ".join(_extract_text_fields(g)), default="")


def _olympic_round_from_text(text: str, *, default: str = "Olympics") -> str:
    tl = str(text or "").lower()
    if "gold medal" in tl or re.search(r"\bgmg\b", tl):
        return "Gold Medal Game"
    if "bronze medal" in tl or re.search(r"\bbmg\b", tl):
        return "Bronze Medal Game"
    if "semi" in tl or re.search(r"\bsf\b", tl):
        return "Semifinals"
    if "quarter" in tl or re.search(r"\bqf\b", tl):
        return "Quarterfinal"
    if "qualif" in tl:
        return "Qualification"
    if "prelim" in tl or "group" in tl or re.search(r"\bqrr\b", tl):
        return "Preliminary"
    return default


def _section_label_text(league: str, items: list[dict[str, Any]], selected_date: dt.date, boundaries: Any) -> str:
    l = str(league or "").upper()
    if l == "NHL":
        phase = _nhl_phase_label(items, selected_date, boundaries)
        return "NHL" if phase == "Regular Season" else f"NHL - {phase}"
    if l.startswith("OLYMPICS"):
        div = _olympics_division_label(items, selected_date)
        return "Olympics" if div == "Olympics" else f"Olympics - {div}"
    return str(league)


def _is_olympic_game(g: dict[str, Any]) -> bool:
    league = str(g.get("league") or "").upper().strip()
    if league == "PWHL":
        return False
    gt = g.get("gameType") or g.get("gameTypeId") or g.get("gameTypeCode")
    s = str(gt).upper() if gt is not None else ""
    if s in {"9", "OLY", "OLYMPICS"}:
        return True
    a, h = _game_codes(g)
    return bool(a and h and a not in NHL_TEAM_CODES and h not in NHL_TEAM_CODES)


def _olympic_round_label_for_date(d: dt.date, *, division: str = "") -> str:
    # Date-only fallback when feed stage metadata is absent.
    # Covers the known 2026 Olympic hockey calendar so cards can still show
    # useful stage labels when upstream payloads provide only generic text.
    div = str(division or "").strip()
    if d.year == 2026 and d.month == 2:
        if div == "Women's":
            if d.day in {5, 6, 7, 8, 9, 10}:
                return "Preliminary"
            if d.day in {12}:
                return "Qualification"
            if d.day in {14}:
                return "Quarterfinal"
            if d.day in {17}:
                return "Semifinals"
            if d.day in {18}:
                return "Bronze Medal Game"
            if d.day in {19}:
                return "Gold Medal Game"
        if div == "Men's":
            if d.day in {11, 12, 13, 14, 15, 16}:
                return "Preliminary"
            if d.day in {17}:
                return "Qualification"
            if d.day in {18}:
                return "Quarterfinal"
            if d.day in {20}:
                return "Semifinals"
            if d.day in {21}:
                return "Bronze Medal Game"
            if d.day in {22}:
                return "Gold Medal Game"
    return "Olympics"


def _extract_text_fields(g: dict[str, Any]) -> list[str]:
    out: list[str] = []
    checks = [
        g.get("displayStage"),
        g.get("statusText"),
        g.get("specialEvent"),
        g.get("gameTitle"),
        g.get("gameSubtitle"),
        g.get("seriesStatusShort"),
        g.get("seriesStatus"),
        g.get("eventName"),
        g.get("tournamentName"),
        g.get("headline"),
        g.get("title"),
        (g.get("venue") or {}).get("default"),
        ((g.get("awayTeam") or {}).get("name") or {}).get("default"),
        ((g.get("homeTeam") or {}).get("name") or {}).get("default"),
    ]
    for v in checks:
        if isinstance(v, str) and v.strip():
            out.append(v.strip())
    return out


def _extract_division_fields(g: dict[str, Any]) -> list[str]:
    # Division parsing should prioritize event/league descriptors and avoid
    # unrelated summary blurbs that can mention both men's and women's games.
    out: list[str] = []
    checks = [
        g.get("displayStage"),
        g.get("specialEvent"),
        g.get("eventName"),
        g.get("tournamentName"),
        g.get("gameTitle"),
        g.get("gameSubtitle"),
    ]
    for v in checks:
        if isinstance(v, str) and v.strip():
            out.append(v.strip())
    return out


def _olympic_division_from_team_codes(g: dict[str, Any]) -> str:
    # Team-based disambiguation when feed text is too generic.
    a, h = _game_codes(g)
    codes = {str(a).upper().strip(), str(h).upper().strip()}
    if "JPN" in codes:
        return "Women's"
    if codes.intersection({"LAT", "SVK", "DEN"}):
        return "Men's"
    return ""


def _olympic_division_fallback_for_date(selected_date: Optional[dt.date]) -> str:
    if not isinstance(selected_date, dt.date):
        return ""
    # Date-only fallback for 2026 when upstream Olympic cards omit division tags.
    if selected_date.year == 2026 and selected_date.month == 2:
        if selected_date.day <= 10:
            return "Women's"
        # During overlap, unresolved cards have consistently been men's.
        if 11 <= selected_date.day <= 22:
            return "Men's"
    return ""


def _game_division_label(g: dict[str, Any], selected_date: Optional[dt.date] = None) -> str:
    explicit = str(g.get("olympicsDivision") or "").strip()
    high_conf = _olympic_division_from_text(" | ".join(_extract_division_fields(g)), default="")
    inferred = high_conf if high_conf in {"Men's", "Women's"} else _infer_olympic_division(g)
    # Only override explicit cached tags when confidence is high.
    if high_conf in {"Men's", "Women's"} and explicit in {"Men's", "Women's"} and high_conf != explicit:
        return high_conf
    if explicit in {"Men's", "Women's"}:
        return explicit
    if inferred in {"Men's", "Women's"}:
        return inferred
    team_guess = _olympic_division_from_team_codes(g)
    if team_guess in {"Men's", "Women's"}:
        return team_guess
    date_guess = _olympic_division_fallback_for_date(selected_date)
    if date_guess in {"Men's", "Women's"}:
        return date_guess
    return ""


def _game_middle_label(g: dict[str, Any], selected_date: dt.date) -> str:
    def _abbr_stage(text: str) -> str:
        t = str(text or "").strip()
        if not t:
            return ""
        reps = {
            "Quarterfinals": "Quarters",
            "Quarterfinal": "Quarters",
            "Semifinals": "Semis",
            "Semifinal": "Semis",
            "Qualification": "Qualifiers",
            "Preliminary": "Prelim.",
            "Bronze Medal Game": "Bronze",
            "Gold Medal Game": "Gold",
        }
        out = t
        for k, v in reps.items():
            out = out.replace(k, v)
        out = re.sub(r"\b(Women's|Women's|Women|Men's|Mens|Men)\b", "", out, flags=re.IGNORECASE)
        out = re.sub(r"\b(Round|Game)\b", "", out, flags=re.IGNORECASE)
        out = re.sub(r"\s+", " ", out).strip(" -")
        return out

    explicit = str(g.get("displayStage") or "").strip()
    if explicit:
        explicit_lbl = _abbr_stage(explicit)
        # If explicit stage is only generic Olympics text, keep searching
        # other metadata fields for concrete round labels.
        if not (_is_olympic_game(g) and explicit_lbl == "Olympics"):
            return explicit_lbl
    if not _is_olympic_game(g):
        return ""
    text_bits: list[str] = []
    for k in (
        "statusText",
        "eventName",
        "tournamentName",
        "gameTitle",
        "gameSubtitle",
        "specialEvent",
        "seriesStatusShort",
        "seriesStatus",
        "headline",
        "title",
    ):
        v = g.get(k)
        if isinstance(v, str) and v.strip():
            text_bits.append(v.strip())
    rnd = _olympic_round_from_text(
        " | ".join(text_bits),
        default=_olympic_round_label_for_date(selected_date, division=_game_division_label(g, selected_date)),
    )
    return _abbr_stage(rnd)


def _to_int(x: Any, default: int = 0) -> int:
    try:
        return int(float(x))
    except Exception:
        return default


def _norm_abbrev(v: Any, fallback: str = "TBD") -> str:
    s = str(v or "").strip().upper()
    if s:
        name_aliases: dict[str, str] = {
            # Olympic country names / variants
            "CANADA": "CAN",
            "UNITED STATES": "USA",
            "UNITED STATES OF AMERICA": "USA",
            "USA": "USA",
            "SWEDEN": "SWE",
            "FINLAND": "FIN",
            "SWITZERLAND": "SUI",
            "CZECHIA": "CZE",
            "CZECH REPUBLIC": "CZE",
            "SLOVAKIA": "SVK",
            "GERMANY": "GER",
            "FRANCE": "FRA",
            "ITALY": "ITA",
            "DENMARK": "DEN",
            "LATVIA": "LAT",
            "JAPAN": "JPN",
            # PWHL full names
            "MONTREAL VICTOIRE": "MON",
            "NEW YORK SIRENS": "NY",
            "BOSTON FLEET": "BOS",
            "MINNESOTA FROST": "MIN",
            "OTTAWA CHARGE": "OTT",
            "TORONTO SCEPTRES": "TOR",
            "VANCOUVER GOLDENEYES": "VAN",
            "SEATTLE TORRENT": "SEA",
        }
        return name_aliases.get(s, s)
    return fallback


def _espn_state(event: dict[str, Any]) -> str:
    comp = (event.get("competitions") or [{}])[0] or {}
    st = (comp.get("status") or event.get("status") or {})
    stype = (st.get("type") or {})
    state = str(stype.get("state") or "").lower()
    if bool(stype.get("completed")) or state in {"post"}:
        return "FINAL"
    if state in {"in", "inprogress", "live"}:
        return "LIVE"
    return "FUT"


def _espn_status_text(event: dict[str, Any]) -> str:
    comp = (event.get("competitions") or [{}])[0] or {}
    st = (comp.get("status") or event.get("status") or {})
    stype = (st.get("type") or {})
    for k in ("shortDetail", "detail", "description"):
        v = stype.get(k) or st.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _parse_mmss(text: Any) -> Optional[tuple[int, int]]:
    s = str(text or "").strip()
    m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*$", s)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def _clock_remaining_from_elapsed_20(display_clock: Any) -> str:
    mmss = _parse_mmss(display_clock)
    if mmss is None:
        return str(display_clock or "").strip()
    elapsed = mmss[0] * 60 + mmss[1]
    rem = max(0, 20 * 60 - elapsed)
    return f"{rem // 60}:{rem % 60:02d}"


def _espn_period_number(event: dict[str, Any]) -> Optional[int]:
    comp = (event.get("competitions") or [{}])[0] or {}
    st = (comp.get("status") or event.get("status") or {})
    try:
        p = int(st.get("period"))
        return p if p > 0 else None
    except Exception:
        return None


def _espn_clock_remaining(event: dict[str, Any], *, olympics_elapsed_clock: bool) -> Optional[str]:
    comp = (event.get("competitions") or [{}])[0] or {}
    st = (comp.get("status") or event.get("status") or {})
    state = str(((st.get("type") or {}).get("state") or "")).lower()
    if state in {"post", "final"}:
        return None
    disp = st.get("displayClock")
    txt = str(disp or "").strip()
    if not txt:
        stxt = _espn_status_text(event)
        m = re.search(r"\b(\d{1,2}:\d{2})\b", str(stxt or "").strip())
        if m:
            txt = m.group(1)
    if not txt:
        return None
    # Keep the card game clock exactly as provided by ESPN.
    # Olympic elapsed->remaining conversion is only applied on scorer lines.
    return txt


def _espn_round_text(event: dict[str, Any], default_league: str) -> str:
    bits: list[str] = []
    comp = (event.get("competitions") or [{}])[0] or {}
    for k in ("description", "shortName", "name", "headline", "title"):
        v = comp.get(k)
        if isinstance(v, str) and v.strip():
            bits.append(v.strip())
    notes = comp.get("notes") or event.get("notes") or []
    if isinstance(notes, list):
        for n in notes:
            if isinstance(n, dict):
                for k in ("headline", "description", "shortText", "text"):
                    v = n.get(k)
                    if isinstance(v, str) and v.strip():
                        bits.append(v.strip())
    for k in ("name", "shortName"):
        v = event.get(k)
        if isinstance(v, str) and v.strip():
            bits.append(v.strip())
    stxt = _espn_status_text(event)
    if stxt:
        bits.append(stxt)
    ctype = comp.get("type") or {}
    if isinstance(ctype, dict):
        for k in ("text", "name", "shortName", "abbreviation", "description", "detail"):
            v = ctype.get(k)
            if isinstance(v, str) and v.strip():
                bits.append(v.strip())
    etype = event.get("type") or {}
    if isinstance(etype, dict):
        for k in ("text", "name", "shortName", "abbreviation", "description", "detail"):
            v = etype.get(k)
            if isinstance(v, str) and v.strip():
                bits.append(v.strip())

    joined = " | ".join(bits).lower()
    default_div = "Women's" if "women" in default_league.lower() else ("Men's" if "men" in default_league.lower() else "")
    div = _olympic_division_from_text(joined, default=default_div)
    rnd = _olympic_round_from_text(joined, default="Olympics")
    if div in {"Men's", "Women's"}:
        return f"{div} {rnd}".strip()
    return str(rnd).strip()


def _espn_league_text(event: dict[str, Any]) -> str:
    vals: list[str] = []
    for k in ("name", "shortName"):
        v = event.get(k)
        if isinstance(v, str) and v.strip():
            vals.append(v.strip())
    leagues = event.get("leagues") or []
    if isinstance(leagues, list):
        for lg in leagues:
            if not isinstance(lg, dict):
                continue
            for k in ("name", "shortName", "abbreviation", "slug"):
                v = lg.get(k)
                if isinstance(v, str) and v.strip():
                    vals.append(v.strip())
    comp = (event.get("competitions") or [{}])[0] or {}
    lg = comp.get("league") or {}
    if isinstance(lg, dict):
        for k in ("name", "shortName", "abbreviation", "slug"):
            v = lg.get(k)
            if isinstance(v, str) and v.strip():
                vals.append(v.strip())
    return " | ".join(vals)


def _convert_espn_events(
    payload: dict[str, Any],
    *,
    league_label: str,
    include_round_text: bool = False,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    events = payload.get("events") or []
    league_u = str(league_label or "").upper()
    olympics_elapsed_clock = league_u.startswith("OLYMPICS")
    for ev in events:
        if not isinstance(ev, dict):
            continue
        comp = (ev.get("competitions") or [{}])[0] or {}
        competitors = comp.get("competitors") or []
        away: dict[str, Any] | None = None
        home: dict[str, Any] | None = None
        for c in competitors:
            if not isinstance(c, dict):
                continue
            side = str(c.get("homeAway") or "").lower()
            team = c.get("team") or {}
            stats_list = c.get("statistics") if isinstance(c.get("statistics"), list) else []
            shots: Optional[int] = None
            for srow in stats_list:
                if not isinstance(srow, dict):
                    continue
                nm = str(srow.get("name") or "").lower()
                ab = str(srow.get("abbreviation") or "").upper()
                if "shootout" in nm:
                    continue
                if nm in {"shotsongoal", "shots on goal", "shots", "shotstotal", "shots total", "total shots"} or (ab in {"S", "ST"} and "shot" in nm):
                    v = _to_int(srow.get("displayValue") or srow.get("value"), default=-1)
                    if v >= 0:
                        shots = v
                        break

            goal_scorers: list[dict[str, Any]] = []
            leaders = c.get("leaders") if isinstance(c.get("leaders"), list) else []
            for ldr in leaders:
                if not isinstance(ldr, dict):
                    continue
                if str(ldr.get("name") or "").lower() != "goals":
                    continue
                for item in ldr.get("leaders") or []:
                    if not isinstance(item, dict):
                        continue
                    ath = item.get("athlete") or {}
                    nm = (
                        str((ath.get("displayName") or ath.get("fullName") or item.get("displayValue") or "")).strip()
                    )
                    if nm:
                        goal_scorers.append({"name": nm})

            row = {
                "abbrev": _norm_abbrev(
                    team.get("abbreviation")
                    or team.get("shortDisplayName")
                    or team.get("displayName")
                    or team.get("name")
                ),
                "score": _to_int(c.get("score"), 0),
                "shotsOnGoal": shots,
                "goalScorers": goal_scorers,
            }
            if side == "away":
                away = row
            elif side == "home":
                home = row
        if away is None and len(competitors) >= 1:
            c = competitors[0] or {}
            team = c.get("team") or {}
            away = {"abbrev": _norm_abbrev(team.get("abbreviation") or team.get("displayName")), "score": _to_int(c.get("score"), 0)}
        if home is None and len(competitors) >= 2:
            c = competitors[1] or {}
            team = c.get("team") or {}
            home = {"abbrev": _norm_abbrev(team.get("abbreviation") or team.get("displayName")), "score": _to_int(c.get("score"), 0)}
        if away is None or home is None:
            continue

        g: dict[str, Any] = {
            "id": _to_int(ev.get("id"), 0),
            "gameState": _espn_state(ev),
            "startTimeUTC": ev.get("date"),
            "awayTeam": away,
            "homeTeam": home,
            "league": league_label,
            "statusText": _espn_status_text(ev),
        }
        comp_desc = str(comp.get("description") or "").strip()
        ev_name = str(ev.get("name") or "").strip()
        ev_short = str(ev.get("shortName") or "").strip()
        if comp_desc or ev_name or ev_short:
            g["eventName"] = comp_desc or ev_name or ev_short
        lg_text = _espn_league_text(ev)
        if lg_text:
            g["tournamentName"] = lg_text
        if league_u.startswith("OLYMPICS"):
            div_text = " | ".join(
                [
                    comp_desc,
                    _espn_league_text(ev),
                    ev_name,
                    ev_short,
                    str(g.get("statusText") or ""),
                ]
            )
            div = _olympic_division_from_text(div_text, default="")
            if div in {"Men's", "Women's"}:
                g["olympicsDivision"] = div
        pnum = _espn_period_number(ev)
        if pnum is not None:
            g["periodDescriptor"] = {"number": pnum}
        cremain = _espn_clock_remaining(ev, olympics_elapsed_clock=olympics_elapsed_clock)
        if cremain:
            g["clock"] = {"timeRemaining": cremain}
        if include_round_text:
            g["displayStage"] = _espn_round_text(ev, league_label)
        out.append(g)
    return out


def _split_all_hockey_espn_events(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    olympic_events: list[dict[str, Any]] = []
    pwhl_events: list[dict[str, Any]] = []
    events = payload.get("events") or []
    if not isinstance(events, list):
        return olympic_events, pwhl_events
    for ev in events:
        if not isinstance(ev, dict):
            continue
        txt = _espn_league_text(ev).lower()
        if "pwhl" in txt or "women" in txt and "professional" in txt and "hockey" in txt:
            pwhl_events.append(ev)
            continue
        # Some Olympic men's rows are tagged as "Men's Ice Hockey" without
        # explicit "Olympic" wording in league text.
        if (
            "ice hockey" in txt
            and ("men" in txt or "women" in txt or "mens" in txt or "womens" in txt)
            and "nhl" not in txt
            and "professional" not in txt
            and "pwhl" not in txt
        ):
            olympic_events.append(ev)
            continue
        if "olympic" in txt:
            olympic_events.append(ev)
            continue
    olympics = _convert_espn_events({"events": olympic_events}, league_label="Olympics", include_round_text=True)
    pwhl = _convert_espn_events({"events": pwhl_events}, league_label="PWHL", include_round_text=False)
    return olympics, pwhl


def _pick_league_codes_from_discovery(
    discovered: list[dict[str, str]],
    *,
    include_words: tuple[str, ...],
    exclude_words: tuple[str, ...] = (),
) -> list[str]:
    out: list[str] = []
    for lg in discovered:
        slug = str(lg.get("slug") or "").strip()
        if not slug:
            continue
        hay = " ".join(
            [
                slug.lower(),
                str(lg.get("name") or "").lower(),
                str(lg.get("abbreviation") or "").lower(),
            ]
        )
        if include_words and not any(w in hay for w in include_words):
            continue
        if exclude_words and any(w in hay for w in exclude_words):
            continue
        out.append(slug)
    # preserve order, de-dupe
    dedup: list[str] = []
    seen = set()
    for s in out:
        if s not in seen:
            seen.add(s)
            dedup.append(s)
    return dedup


def _dedupe_games(games: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for g in games:
        gid = str(g.get("id") or "").strip()
        a, h = _game_codes(g)
        st = str(g.get("startTimeUTC") or "").strip()
        key = gid if gid else f"{a}|{h}|{st}"
        if key in seen:
            continue
        seen.add(key)
        out.append(g)
    return out


def _merge_games_by_id(primary: list[dict[str, Any]], secondary: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Merge same-game rows from two sources, preserving primary ordering while
    filling missing fields from secondary (including nested team fields).
    """
    sec_map: dict[str, dict[str, Any]] = {}
    for g in secondary:
        gid = str(g.get("id") or "").strip()
        if gid:
            sec_map[gid] = g

    def _rows_have_time(rows: Any) -> bool:
        if not isinstance(rows, list):
            return False
        for r in rows:
            if not isinstance(r, dict):
                continue
            if str(r.get("timeRemaining") or r.get("timeInPeriod") or r.get("displayTime") or "").strip():
                return True
            pd = r.get("periodDescriptor")
            if isinstance(pd, dict) and (pd.get("number") is not None or str(pd.get("periodType") or "").strip()):
                return True
        return False

    out: list[dict[str, Any]] = []
    for g in primary:
        gid = str(g.get("id") or "").strip()
        if not gid or gid not in sec_map:
            out.append(g)
            continue
        s = sec_map[gid]
        m = dict(g)
        for k, v in s.items():
            if k in {"awayTeam", "homeTeam"}:
                base_team = m.get(k) if isinstance(m.get(k), dict) else {}
                sec_team = v if isinstance(v, dict) else {}
                team_merged = dict(base_team)
                for tk, tv in sec_team.items():
                    if tk in {"abbrev", "abbreviation", "teamAbbrev"}:
                        cur_code = str(team_merged.get(tk) or "").strip().upper()
                        new_code = str(tv or "").strip().upper()
                        if cur_code == "TBD" and new_code and new_code != "TBD":
                            team_merged[tk] = tv
                            continue
                    if tk == "goalScorers" and isinstance(tv, list):
                        cur = team_merged.get(tk)
                        if not isinstance(cur, list) or not cur:
                            team_merged[tk] = tv
                            continue
                        if _rows_have_time(tv) and not _rows_have_time(cur):
                            team_merged[tk] = tv
                            continue
                    if team_merged.get(tk) in (None, "", [], {}):
                        team_merged[tk] = tv
                m[k] = team_merged
            elif m.get(k) in (None, "", [], {}):
                m[k] = v
        out.append(m)
    return out


def _choose_cols(n: int, w: int, h: int) -> int:
    """
    Pick 1..5 columns to maximize card size while keeping a wide-card feel.
    """
    if n <= 0:
        return 1

    gap = CARD_GAP_X
    target_ratio = CARD_RATIO
    best_cols = 3
    best_score = -1e9

    # Prefer up to 3 cols generally; allow 4/5 for larger slates.
    max_cols = 5 if n >= 12 else (4 if n >= 8 else 3)
    for cols in range(1, max_cols + 1):
        rows = math.ceil(n / cols)
        cell_w = (w - gap * (cols + 1)) / cols
        cell_h = (h - gap * (rows + 1)) / rows
        if cell_w <= 60 or cell_h <= 60:
            continue
        ratio = cell_w / max(1, cell_h)
        size_score = min(cell_w, cell_h)
        ratio_pen = abs(ratio - target_ratio) * 60
        score = size_score - ratio_pen
        if score > best_score:
            best_score = score
            best_cols = cols

    return best_cols


def _league_order_key(name: str) -> tuple[int, str]:
    n = str(name or "").upper()
    if n == "NHL":
        return (0, n)
    if n.startswith("OLYMPICS"):
        return (1, n)
    if n == "PWHL":
        return (2, n)
    return (9, n)


def _group_bucket_for_game(g: dict[str, Any], selected_date: dt.date) -> str:
    league = str(g.get("league") or "NHL")
    if league.upper().startswith("OLYMPICS"):
        div = _game_division_label(g, selected_date)
        if div in {"Men's", "Women's"}:
            return f"Olympics - {div}"
        return "Olympics"
    return league


def _game_sort_key(g: dict[str, Any], tz: ZoneInfo) -> tuple[int, dt.datetime, str, str]:
    # 1) by scheduled start (unknown start goes last), 2) by teams for stable ordering.
    st = _parse_start_local(g, tz)
    has_start = 0 if isinstance(st, dt.datetime) else 1
    if not isinstance(st, dt.datetime):
        st = dt.datetime.max.replace(tzinfo=tz)
    a, h = _game_codes(g)
    return (has_start, st, a, h)


def _group_by_league(
    games: list[dict[str, Any]],
    *,
    selected_date: dt.date,
    tz: ZoneInfo,
) -> list[tuple[str, list[dict[str, Any]]]]:
    by: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for g in games:
        league = _group_bucket_for_game(g, selected_date)
        by[league].append(g)
    out: list[tuple[str, list[dict[str, Any]]]] = []
    for league in sorted(by.keys(), key=_league_order_key):
        items = sorted(by[league], key=lambda gg: _game_sort_key(gg, tz))
        out.append((league, items))
    return out


def _card_layout(n: int, w: int, h: int) -> tuple[int, int, int, int, int, int]:
    """
    Returns (cols, rows, card_w, card_h, start_x, start_y) while preserving
    a consistent wide-card aspect ratio and centering the whole block.
    """
    if n <= 0:
        return 1, 1, 0, 0, 0, 0

    cols = _choose_cols(n, w, h)
    rows = max(1, math.ceil(n / cols))

    avail_w = max(1.0, w - CARD_GAP_X * (cols + 1))
    card_w = avail_w / cols
    card_h = card_w / CARD_RATIO

    total_h = rows * card_h + CARD_GAP_Y * (rows + 1)
    if total_h > h:
        avail_h = max(1.0, h - CARD_GAP_Y * (rows + 1))
        card_h = avail_h / rows
        card_w = card_h * CARD_RATIO

    total_w = cols * card_w + CARD_GAP_X * (cols + 1)
    total_h = rows * card_h + CARD_GAP_Y * (rows + 1)
    start_x = int(max(0.0, (w - total_w) / 2.0))
    start_y = int(max(0.0, (h - total_h) / 2.0))
    return cols, rows, int(card_w), int(card_h), start_x, start_y


def _flag_get(code: str, *, height: int, master: tk.Misc) -> Any:
    base_code = str(code).upper()
    canonical = COUNTRY_CODE_ALIASES.get(base_code, base_code)
    key = (canonical, int(height))
    if key in _FLAG_IMG_CACHE:
        return _FLAG_IMG_CACHE[key]

    candidates = [canonical]
    if base_code not in candidates:
        candidates.append(base_code)
    candidates.extend(COUNTRY_FILE_ALIASES.get(canonical, ()))
    candidates.extend([c.lower() for c in list(candidates)])

    for c in candidates:
        p_png = FLAGS_DIR / f"{c}.png"
        if not p_png.exists():
            continue
        try:
            if _PIL_OK:
                pil = Image.open(str(p_png)).convert("RGBA")  # type: ignore[union-attr]
                w0, h0 = pil.size
                if h0 > 0:
                    scale = float(max(1, int(height))) / float(h0)
                    w = max(1, int(round(w0 * scale)))
                    try:
                        resample = Image.Resampling.LANCZOS  # type: ignore[attr-defined,union-attr]
                    except Exception:
                        resample = Image.LANCZOS  # type: ignore[attr-defined,union-attr]
                    pil = pil.resize((w, max(1, int(height))), resample=resample)
                img = ImageTk.PhotoImage(pil)  # type: ignore[union-attr]
                _FLAG_IMG_CACHE[key] = img
                return img
            img = tk.PhotoImage(master=master, file=str(p_png))
            h0 = int(img.height())
            if h0 > height and h0 > 0:
                factor = max(1, int(math.ceil(h0 / int(max(1, height)))))
                img = img.subsample(factor)
            _FLAG_IMG_CACHE[key] = img
            return img
        except Exception:
            continue

    return None


def _flag_aspect_ratio(code: str, *, master: tk.Misc) -> float | None:
    base_code = str(code).upper()
    canonical = COUNTRY_CODE_ALIASES.get(base_code, base_code)
    if canonical in _FLAG_AR_CACHE:
        return _FLAG_AR_CACHE[canonical]
    candidates = [canonical]
    if base_code not in candidates:
        candidates.append(base_code)
    candidates.extend(COUNTRY_FILE_ALIASES.get(canonical, ()))
    candidates.extend([c.lower() for c in list(candidates)])
    for c in candidates:
        p_png = FLAGS_DIR / f"{c}.png"
        if not p_png.exists():
            continue
        try:
            img = tk.PhotoImage(master=master, file=str(p_png))
            w0 = int(img.width())
            h0 = int(img.height())
            if w0 > 0 and h0 > 0:
                ar = float(w0) / float(h0)
                _FLAG_AR_CACHE[canonical] = ar
                return ar
        except Exception:
            continue
    return None


def _norm_pwhl_code(code: str) -> str:
    c = str(code or "").strip().upper()
    if not c:
        return "TBD"
    return PWHL_CODE_ALIASES.get(c, c)


def _pwhl_logo_paths(code: str) -> list[Path]:
    raw = str(code or "").strip().upper()
    c = _norm_pwhl_code(raw)
    candidates = [
        c,
        raw,
        "MON" if c == "MTL" else c,
        c.lower(),
        raw.lower(),
        "mon" if c == "MTL" else c.lower(),
        f"pwhl_{c}",
        f"pwhl_{raw}",
        f"pwhl_MON" if c == "MTL" else f"pwhl_{c}",
        f"pwhl_{c.lower()}",
        f"pwhl_{raw.lower()}",
        f"pwhl_mon" if c == "MTL" else f"pwhl_{c.lower()}",
        f"{c}_pwhl",
        f"{raw}_pwhl",
        "MON_pwhl" if c == "MTL" else f"{c}_pwhl",
        f"{c.lower()}_pwhl",
        f"{raw.lower()}_pwhl",
        "mon_pwhl" if c == "MTL" else f"{c.lower()}_pwhl",
    ]
    out: list[Path] = []
    team_name_aliases: dict[str, tuple[str, ...]] = {
        "BOS": ("boston", "fleet", "boston_fleet"),
        "MIN": ("minnesota", "frost", "minnesota_frost"),
        "MTL": ("montreal", "victoire", "montreal_victoire", "montreal_victorie"),
        "NY": ("new_york", "sirens", "new_york_sirens", "ny_sirens"),
        "OTT": ("ottawa", "charge", "ottawa_charge"),
        "TOR": ("toronto", "sceptres", "toronto_sceptres"),
        "VAN": ("vancouver", "goldeneyes", "vancouver_goldeneyes"),
        "SEA": ("seattle", "torrent", "seattle_torrent"),
    }
    candidates.extend(team_name_aliases.get(c, ()))
    for name in candidates:
        out.append(PWHL_LOGOS_DIR / f"{name}.png")
    return out


def _pwhl_logo_get(code: str, *, height: int, master: tk.Misc) -> Any:
    raw = str(code or "").strip().upper()
    c = _norm_pwhl_code(raw)
    key = (c, int(height))
    if key in _PWHL_IMG_CACHE:
        return _PWHL_IMG_CACHE[key]

    for p in _pwhl_logo_paths(raw):
        if not p.exists():
            continue
        try:
            if _PIL_OK:
                pil = Image.open(str(p)).convert("RGBA")  # type: ignore[union-attr]
                w0, h0 = pil.size
                if h0 > 0:
                    scale = float(max(1, int(height))) / float(h0)
                    w = max(1, int(round(w0 * scale)))
                    try:
                        resample = Image.Resampling.LANCZOS  # type: ignore[attr-defined,union-attr]
                    except Exception:
                        resample = Image.LANCZOS  # type: ignore[attr-defined,union-attr]
                    pil = pil.resize((w, max(1, int(height))), resample=resample)
                img = ImageTk.PhotoImage(pil)  # type: ignore[union-attr]
                _PWHL_IMG_CACHE[key] = img
                return img
            img = tk.PhotoImage(master=master, file=str(p))
            h0 = int(img.height())
            if h0 > height and h0 > 0:
                factor = max(1, int(math.ceil(h0 / int(max(1, height)))))
                img = img.subsample(factor)
            _PWHL_IMG_CACHE[key] = img
            return img
        except Exception:
            continue
    return None


def _pwhl_logo_aspect_ratio(code: str, *, master: tk.Misc) -> float | None:
    raw = str(code or "").strip().upper()
    c = _norm_pwhl_code(raw)
    if c in _PWHL_AR_CACHE:
        return _PWHL_AR_CACHE[c]
    for p in _pwhl_logo_paths(raw):
        if not p.exists():
            continue
        try:
            img = tk.PhotoImage(master=master, file=str(p))
            w0 = int(img.width())
            h0 = int(img.height())
            if w0 > 0 and h0 > 0:
                ar = float(w0) / float(h0)
                _PWHL_AR_CACHE[c] = ar
                return ar
        except Exception:
            continue
    return None


def _logo_get(logos: Any, code: str, *, height: int, master: tk.Misc, league: str | None = None) -> Any:
    """
    Compatibility: some LogoBank versions accept height=, some accept px=.
    """
    league_u = str(league or "").upper().strip()
    if league_u.startswith("OLYMPICS"):
        return _flag_get(code, height=height, master=master)
    if league_u == "PWHL":
        # Never fall back to NHL logos for PWHL codes.
        return _pwhl_logo_get(code, height=height, master=master)
    if logos is None:
        return _flag_get(code, height=height, master=master)
    try:
        img = logos.get(code, height=height, dim=False)
        if img is not None:
            return img
    except TypeError:
        try:
            img = logos.get(code, px=height)  # older signature
            if img is not None:
                return img
        except Exception:
            pass
    except Exception:
        pass
    return _flag_get(code, height=height, master=master)


def _logo_height_for_width(
    logos: Any,
    code: str,
    target_w: int,
    *,
    min_h: int,
    max_h: int,
    league: str | None = None,
    master: tk.Misc | None = None,
) -> int:
    """
    Converts a shared target logo width into per-team heights using aspect ratio.
    Falls back to a sensible default if aspect ratio isn't available.
    """
    ar = None
    league_u = str(league or "").upper().strip()
    if league_u.startswith("OLYMPICS") and master is not None:
        ar = _flag_aspect_ratio(code, master=master)
    if league_u == "PWHL" and master is not None:
        ar = _pwhl_logo_aspect_ratio(code, master=master)
    if ar is None:
        try:
            ar_fn = getattr(logos, "aspect_ratio", None)
            if callable(ar_fn):
                ar = ar_fn(code)
        except Exception:
            ar = None

    if isinstance(ar, (int, float)) and float(ar) > 0.01:
        h = int(round(float(target_w) / float(ar)))
    else:
        h = int(round(target_w * 0.62))

    return max(min_h, min(max_h, h))


def _make_step_button(parent: tk.Widget, text: str, command) -> tk.Label:
    lbl = tk.Label(
        parent,
        text=text,
        bg=STEP_BTN_BG,
        fg=STEP_BTN_FG,
        font=("TkDefaultFont", 11, "bold"),
        bd=0,
        highlightthickness=0,
        padx=8,
        pady=6,
        width=3,
        cursor="hand2",
    )

    def _enter(_e=None):
        lbl.configure(bg=STEP_BTN_HOVER)

    def _leave(_e=None):
        lbl.configure(bg=STEP_BTN_BG)

    def _click(_e=None):
        command()

    lbl.bind("<Enter>", _enter)
    lbl.bind("<Leave>", _leave)
    lbl.bind("<Button-1>", _click)
    return lbl


@dataclass
class _Card:
    frame: tk.Frame
    panel: tk.Frame
    overlay: tk.Canvas
    img_refs: list[Any]
    score_font: tkfont.Font
    dash_font: tkfont.Font
    at_font: tkfont.Font
    mid_font: tkfont.Font
    status_font: tkfont.Font
    scorer_popup: Optional[tk.Widget] = None
    is_hovered: bool = False
    base_height: int = 0
    base_width: int = 0


def build_games_tab(parent: tk.Widget, ctx: dict[str, Any]) -> ttk.Frame:
    """
    Scoreboard grid tab (matches mockups "in spirit"):
      - Big date header
      - Slider w/ arrows
      - Grid of game cards (auto-resize to fit screen)
      - Live auto-refresh when viewing today
      - Past/final uses NHLApi's pinned cache
    """
    nhl: NHLApi = ctx["nhl"]
    espn = ctx.get("espn")
    pwhl_api = ctx.get("pwhl")
    logos: Optional[LogoBank] = ctx.get("logos")
    season = str(ctx.get("season") or "")
    season_start: dt.date = ctx.get("season_start", dt.date(dt.date.today().year, 10, 1))
    season_end: dt.date = ctx.get("season_end", dt.date.today())
    season_probe_date: dt.date = ctx.get("season_probe_date", season_end)

    tz_name = ctx.get("timezone", "America/New_York")
    tz = ZoneInfo(str(tz_name))

    root = ttk.Frame(parent)
    bgroot = tk.Frame(root, bg=BG, bd=0, highlightthickness=0)
    bgroot.pack(fill="both", expand=True)
    bgroot.grid_rowconfigure(2, weight=1)
    bgroot.grid_columnconfigure(0, weight=1)

    # ----- date range -----
    today = dt.date.today()
    active_today = min(today, season_end)
    if active_today < season_start:
        active_today = season_start
    dmin: Optional[dt.date] = None
    dmax: Optional[dt.date] = None

    # Discover boundaries from cache only (no startup network).
    boundaries = None
    try:
        payloads: list[dict[str, Any]] = []
        for key in (f"nhl/schedule/{season_probe_date.isoformat()}", f"nhl/schedule_calendar/{season_probe_date.isoformat()}"):
            hit = nhl.cache.get_json(key, ttl_s=None)  # type: ignore[attr-defined]
            if isinstance(hit, dict):
                payloads.append(hit)
        if payloads:
            pre = nhl._pick_date(payloads, ("preSeasonStartDate", "preseasonStartDate", "exhibitionStartDate"), prefer="min")  # type: ignore[attr-defined]
            reg_start = nhl._pick_date(payloads, ("regularSeasonStartDate", "regSeasonStartDate", "regularStartDate"), prefer="min")  # type: ignore[attr-defined]
            reg_end = nhl._pick_date(payloads, ("regularSeasonEndDate", "regSeasonEndDate", "regularEndDate"), prefer="max")  # type: ignore[attr-defined]
            po_start = nhl._pick_date(payloads, ("playoffStartDate", "playoffsStartDate", "postSeasonStartDate"), prefer="min")  # type: ignore[attr-defined]
            po_end = nhl._pick_date(payloads, ("playoffEndDate", "playoffsEndDate", "postSeasonEndDate", "stanleyCupFinalEndDate"), prefer="max")  # type: ignore[attr-defined]
            first_game, last_game = nhl._scan_gameweek_bounds(payloads)  # type: ignore[attr-defined]
            from hockey_app.data.nhl_api import SeasonBoundaries
            boundaries = SeasonBoundaries(
                preseason_start=pre,
                regular_start=reg_start,
                regular_end=reg_end,
                playoffs_start=po_start,
                playoffs_end=po_end,
                first_scheduled_game=first_game,
                last_scheduled_game=last_game,
            )
    except Exception:
        boundaries = None
    if boundaries is not None:
        if boundaries.preseason_start is not None:
            dmin = boundaries.preseason_start
        elif boundaries.first_scheduled_game is not None:
            dmin = boundaries.first_scheduled_game

        if boundaries.last_scheduled_game is not None:
            dmax = boundaries.last_scheduled_game
        elif boundaries.playoffs_end is not None:
            dmax = boundaries.playoffs_end

    # Union-in PWHL season span so future games in non-NHL leagues are included.
    if pwhl_api is not None:
        pwhl_start: Optional[dt.date] = None
        pwhl_end: Optional[dt.date] = None
        try:
            pwhl_start, pwhl_end = pwhl_api.get_season_boundaries(season_probe_date, allow_network=False)
        except Exception:
            pwhl_start, pwhl_end = None, None

        if pwhl_start is not None:
            dmin = pwhl_start if dmin is None else min(dmin, pwhl_start)
        if pwhl_end is not None:
            dmax = pwhl_end if dmax is None else max(dmax, pwhl_end)

    # Safe fallback if endpoint shape/network isn't available.
    if dmin is None:
        dmin = season_start
    if dmax is None:
        dmax = season_end

    if dmin > dmax:
        dmin, dmax = dmax, dmin

    total_days = max(1, (dmax - dmin).days)
    day_var = tk.IntVar(value=max(0, min(total_days, (active_today - dmin).days)))

    # ----- header -----
    header = tk.Frame(bgroot, bg=BG, bd=0, highlightthickness=0)
    header.grid(row=0, column=0, sticky="ew", pady=(6, 2))
    header.grid_columnconfigure(0, weight=1)

    date_font = tkfont.Font(family="Helvetica", size=48, weight="normal")
    stage_font = tkfont.Font(family="Helvetica", size=16, weight="normal")

    date_lbl = tk.Label(header, text=_fmt_big_date(active_today), bg=BG, fg=FG, font=date_font)
    date_lbl.grid(row=0, column=0, sticky="n", pady=(0, 2))

    stage_lbl = tk.Label(header, text="", bg=BG, fg=MUTED, font=stage_font)
    stage_lbl.grid(row=1, column=0, sticky="n", pady=(0, 2))

    # ----- controls (arrows + slider) -----
    ctrl = tk.Frame(bgroot, bg=BG, bd=0, highlightthickness=0)
    ctrl.grid(row=1, column=0, sticky="ew", padx=10, pady=(2, 8))
    ctrl.grid_columnconfigure(1, weight=1)

    btn_l = _make_step_button(ctrl, "◀", lambda: _step(-1))
    btn_r = _make_step_button(ctrl, "▶", lambda: _step(1))
    btn_l.grid(row=0, column=0, padx=(0, 8))
    btn_r.grid(row=0, column=2, padx=(8, 0))

    scale = ttk.Scale(ctrl, orient="horizontal", from_=0, to=total_days, value=day_var.get())
    scale.grid(row=0, column=1, sticky="ew")

    # ----- games grid -----
    grid_host = tk.Frame(bgroot, bg=BG, bd=0, highlightthickness=0)
    grid_host.grid(row=2, column=0, sticky="nsew", padx=18, pady=(0, 18))

    empty_lbl = tk.Label(grid_host, text="", bg=BG, fg=MUTED, font=tkfont.Font(size=16))
    empty_lbl.place(relx=0.5, rely=0.5, anchor="center")

    cards: list[_Card] = []
    section_labels: list[tk.Label] = []
    refresh_after_id: Optional[str] = None
    resize_after_id: Optional[str] = None
    scale_after_id: Optional[str] = None
    day_payload_cache: dict[dt.date, dict[str, Any]] = {}
    day_payload_stamp: dict[dt.date, str] = {}
    day_external_cache: dict[dt.date, tuple[list[dict[str, Any]], list[dict[str, Any]]]] = {}
    day_external_stamp: dict[dt.date, str] = {}
    day_external_empty_checked: set[dt.date] = set()
    day_pwhl_cache: dict[dt.date, list[dict[str, Any]]] = {}
    day_pwhl_stamp: dict[dt.date, str] = {}
    day_external_last_try_s: dict[dt.date, float] = {}
    day_pwhl_last_try_s: dict[dt.date, float] = {}
    day_source_plan: dict[dt.date, tuple[bool, bool, bool]] = {}
    day_tbd_refresh_try_s: dict[dt.date, float] = {}
    day_moneypuck_probs: dict[dt.date, dict[tuple[str, str], tuple[float, float]]] = {}
    day_moneypuck_last_try_s: dict[dt.date, float] = {}
    game_moneypuck_probs: dict[int, tuple[float, float]] = {}
    game_moneypuck_probs_ts: dict[int, float] = {}
    game_moneypuck_last_try_s: dict[int, float] = {}
    game_moneypuck_live_force_try_s: dict[int, float] = {}
    game_win_probs_by_id: dict[int, tuple[float, float]] = {}
    game_win_prob_index_built = False
    day_points_pct_cache: dict[dt.date, dict[str, float]] = {}
    day_standings_context_cache: dict[dt.date, dict[str, dict[str, Any]]] = {}
    day_standings_last_try_s: dict[dt.date, float] = {}
    player_landing_cache: dict[int, dict[str, Any]] = {}
    club_goalie_stats_cache: dict[tuple[str, str], list[dict[str, Any]]] = {}
    club_skater_stats_cache: dict[tuple[str, str], list[dict[str, Any]]] = {}
    last_rendered_date: Optional[dt.date] = None
    refresh_inflight = False
    auto_refresh_s = 3
    auto_refresh_enabled = True
    auto_refresh_has_active_games = False
    season_series_rows_cache: Optional[list[dict[str, Any]]] = None
    season_series_matchup_cache: dict[tuple[str, str], dict[str, Any]] = {}
    espn_summary_index_built = False
    espn_summary_by_matchup: dict[tuple[dt.date, str, str], dict[str, Any]] = {}

    def _pick_text(v: Any) -> str:
        if isinstance(v, str):
            return v.strip()
        if isinstance(v, dict):
            for key in ("default", "en", "name", "fullName", "displayName", "shortName"):
                vv = v.get(key)
                if isinstance(vv, str) and vv.strip():
                    return vv.strip()
        return ""

    def _team_full_name(team: dict[str, Any], fallback_code: str) -> str:
        place = _pick_text(team.get("placeName"))
        common = _pick_text(team.get("commonName"))
        name = _pick_text(team.get("name"))
        if place and common:
            return f"{place} {common}".strip()
        if name:
            return name
        if place:
            return place
        if common:
            return common
        return str(fallback_code or "TBD").upper()

    def _fmt_local_start(iso_utc: Any, *, include_tz: bool = False) -> str:
        raw = str(iso_utc or "").strip()
        if not raw:
            return "[NF]"
        txt = raw
        if txt.endswith("Z"):
            txt = txt[:-1] + "+00:00"
        try:
            when = dt.datetime.fromisoformat(txt)
        except Exception:
            return "[NF]"
        if when.tzinfo is None:
            when = when.replace(tzinfo=ZoneInfo("UTC"))
        local = when.astimezone(tz)
        if include_tz:
            try:
                return local.strftime("%-I:%M %p %Z").strip()
            except Exception:
                return local.strftime("%I:%M %p %Z").lstrip("0").strip()
        try:
            return local.strftime("%-I:%M %p").strip()
        except Exception:
            return local.strftime("%I:%M %p").lstrip("0").strip()

    def _fmt_month_day(d: dt.date) -> str:
        try:
            return d.strftime("%b %-d").upper()
        except Exception:
            return d.strftime("%b %d").upper().replace(" 0", " ")

    def _is_final_state_text(state: Any) -> bool:
        u = str(state or "").upper().strip()
        return u in {"FINAL", "OFF"} or u.startswith("FINAL")

    def _game_date(game: dict[str, Any]) -> Optional[dt.date]:
        for key in ("gameDate", "date", "startDate"):
            raw = str(game.get(key) or "").strip()
            if not raw:
                continue
            try:
                return dt.date.fromisoformat(raw[:10])
            except Exception:
                continue
        start_local = _parse_start_local(game, tz)
        if isinstance(start_local, dt.datetime):
            return start_local.date()
        return None

    def _read_season_series_rows() -> list[dict[str, Any]]:
        nonlocal season_series_rows_cache
        if season_series_rows_cache is not None:
            return season_series_rows_cache
        season_series_rows_cache = []
        season_u = str(season or "").strip()
        if not season_u:
            return season_series_rows_cache
        xml_path = cache_dir() / "online" / "xml" / season_u / "games.xml"
        if not xml_path.exists():
            return season_series_rows_cache
        try:
            tree = ET.parse(xml_path)
            root_xml = tree.getroot()
        except Exception:
            return season_series_rows_cache
        out: list[dict[str, Any]] = []
        for day_node in root_xml.findall("day"):
            day_iso = str(day_node.get("date") or "").strip()
            try:
                day_date = dt.date.fromisoformat(day_iso[:10])
            except Exception:
                continue
            for g in day_node.findall("game"):
                away_code = str(g.get("away_code") or "").strip().upper()
                home_code = str(g.get("home_code") or "").strip().upper()
                if not away_code or not home_code:
                    continue
                out.append(
                    {
                        "id": _to_int(g.get("id") or 0, default=0),
                        "date": day_date,
                        "league": str(g.get("league") or "").strip().upper(),
                        "state": str(g.get("state") or "").strip().upper(),
                        "status_text": str(g.get("status_text") or "").strip(),
                        "start_utc": str(g.get("start_utc") or "").strip(),
                        "away_code": away_code,
                        "home_code": home_code,
                        "away_score": _to_int(g.get("away_score") or 0, default=0),
                        "home_score": _to_int(g.get("home_score") or 0, default=0),
                    }
                )
        out.sort(
            key=lambda row: (
                row.get("date") or dt.date.max,
                str(row.get("start_utc") or ""),
                _to_int(row.get("id") or 0, default=0),
            )
        )
        season_series_rows_cache = out
        return season_series_rows_cache

    def _season_series_for_matchup(
        code_a: str,
        code_b: str,
        *,
        live_game: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        a = str(code_a or "").upper()
        b = str(code_b or "").upper()
        key = tuple(sorted((a, b)))
        cached = season_series_matchup_cache.get(key)
        if cached is None:
            rows_all = _read_season_series_rows()
            rows = [
                row
                for row in rows_all
                if str(row.get("league") or "") == "NHL"
                and {str(row.get("away_code") or ""), str(row.get("home_code") or "")} == {a, b}
            ]
            if not rows:
                cached = {"headline": "[NF]", "rows": []}
                season_series_matchup_cache[key] = cached
            else:
                wins: dict[str, int] = {a: 0, b: 0}
                played: list[dict[str, Any]] = []
                upcoming: list[dict[str, Any]] = []
                for row in rows:
                    state_u = str(row.get("state") or "").upper()
                    if _is_final_state_text(state_u):
                        played.append(row)
                        away_code = str(row.get("away_code") or "")
                        home_code = str(row.get("home_code") or "")
                        away_score = _to_int(row.get("away_score") or 0, default=0)
                        home_score = _to_int(row.get("home_score") or 0, default=0)
                        if away_score > home_score and away_code in wins:
                            wins[away_code] += 1
                        elif home_score > away_score and home_code in wins:
                            wins[home_code] += 1
                    else:
                        upcoming.append(row)

                if wins[a] > wins[b]:
                    headline = f"{a} leads {wins[a]}-{wins[b]}"
                elif wins[b] > wins[a]:
                    headline = f"{b} leads {wins[b]}-{wins[a]}"
                else:
                    headline = f"Tied {wins[a]}-{wins[b]}"

                lines: list[str] = []
                recent = played[-2:]
                for row in recent:
                    away_code = str(row.get("away_code") or "")
                    home_code = str(row.get("home_code") or "")
                    away_score = _to_int(row.get("away_score") or 0, default=0)
                    home_score = _to_int(row.get("home_score") or 0, default=0)
                    day_date = row.get("date")
                    day_txt = _fmt_month_day(day_date) if isinstance(day_date, dt.date) else "[NF]"
                    lines.append(f"{away_code} {away_score} - {home_code} {home_score} FINAL {day_txt}")

                for row in upcoming[:1]:
                    away_code = str(row.get("away_code") or "")
                    home_code = str(row.get("home_code") or "")
                    day_date = row.get("date")
                    day_txt = _fmt_month_day(day_date) if isinstance(day_date, dt.date) else "[NF]"
                    start_txt = _fmt_local_start(row.get("start_utc"), include_tz=True)
                    lines.append(f"{away_code} @ {home_code} {start_txt} {day_txt}")

                cached = {"headline": headline, "rows": lines}
                season_series_matchup_cache[key] = cached

        if not isinstance(live_game, dict):
            return cached
        live_away, live_home = _game_codes(live_game)
        if {live_away, live_home} != {a, b}:
            return cached
        state_u = _game_state(live_game)
        if _is_final_state_text(state_u) or state_u in {"", "FUT", "PRE", "SCHEDULED"}:
            return cached

        away_score, home_score, away_code, home_code = _scores(live_game)
        live_status = _live_status(live_game)
        live_day = _game_date(live_game)
        day_txt = _fmt_month_day(live_day) if isinstance(live_day, dt.date) else ""
        live_line = f"{away_code} {away_score} - {home_code} {home_score} {live_status}".strip()
        if day_txt:
            live_line = f"{live_line} {day_txt}"
        rows_cached = [
            str(x).strip()
            for x in (cached.get("rows") if isinstance(cached.get("rows"), list) else [])
            if str(x).strip()
        ]
        rows_out = list(rows_cached)
        replaced_idx: Optional[int] = None
        matchup_prefix = f"{away_code} @ {home_code}"
        for idx, line in enumerate(rows_cached):
            up = str(line).upper()
            if up.startswith(matchup_prefix):
                if not day_txt or day_txt in up:
                    replaced_idx = idx
                    break
        if replaced_idx is not None:
            rows_out[replaced_idx] = live_line
        elif live_line not in rows_out:
            rows_out.append(live_line)
        rows: list[str] = []
        seen_rows: set[str] = set()
        for line in rows_out:
            txt = str(line).strip()
            if not txt or txt in seen_rows:
                continue
            seen_rows.add(txt)
            rows.append(txt)
        return {"headline": str(cached.get("headline") or "[NF]"), "rows": rows}

    def _build_espn_summary_index() -> None:
        nonlocal espn_summary_index_built
        if espn_summary_index_built:
            return
        espn_summary_index_built = True
        if espn is None:
            return
        cache_obj = getattr(espn, "cache", None)
        root_dir = getattr(cache_obj, "root", None)
        if not isinstance(root_dir, Path) or not root_dir.exists():
            return
        for p in root_dir.rglob("*.json"):
            try:
                payload = json.loads(p.read_text())
            except Exception:
                continue
            data = payload.get("data") if isinstance(payload, dict) and isinstance(payload.get("data"), dict) else payload
            if not isinstance(data, dict):
                continue
            header = data.get("header")
            boxscore = data.get("boxscore")
            if not isinstance(header, dict) or not isinstance(boxscore, dict):
                continue
            comp = (((header.get("competitions") or [{}])[0]) or {})
            if not isinstance(comp, dict):
                continue
            date_raw = str(comp.get("date") or "").strip()
            if not date_raw:
                continue
            try:
                game_day = dt.date.fromisoformat(date_raw[:10])
            except Exception:
                continue
            away_code = ""
            home_code = ""
            for c in comp.get("competitors") or []:
                if not isinstance(c, dict):
                    continue
                team = c.get("team") if isinstance(c.get("team"), dict) else {}
                code = _norm_abbrev(team.get("abbreviation") or team.get("shortDisplayName") or team.get("displayName"), fallback="")
                if not code:
                    continue
                side = str(c.get("homeAway") or "").strip().lower()
                if side == "away":
                    away_code = code.upper()
                elif side == "home":
                    home_code = code.upper()
            if not away_code or not home_code:
                continue
            espn_summary_by_matchup[(game_day, away_code, home_code)] = data

    def _espn_summary_for_game(game: dict[str, Any], away_code: str, home_code: str) -> Optional[dict[str, Any]]:
        _build_espn_summary_index()
        if not espn_summary_by_matchup:
            return None
        game_day = _game_date(game)
        if game_day is None:
            return None
        return espn_summary_by_matchup.get((game_day, away_code.upper(), home_code.upper()))

    def _load_cached_boxscore(game_id: int) -> Optional[dict[str, Any]]:
        if game_id <= 0:
            return None
        try:
            hit = nhl.cache.get_json(f"nhl/boxscore/{int(game_id)}", ttl_s=None)  # type: ignore[attr-defined]
        except Exception:
            hit = None
        return hit if isinstance(hit, dict) else None

    def _load_cached_pbp(game_id: int) -> Optional[dict[str, Any]]:
        if game_id <= 0:
            return None
        payload = None
        try:
            payload = nhl.cache.get_json(f"nhl/pbp/final/{int(game_id)}", ttl_s=None)  # type: ignore[attr-defined]
        except Exception:
            payload = None
        if not isinstance(payload, dict):
            try:
                payload = nhl.cache.get_json(f"nhl/pbp/live/{int(game_id)}", ttl_s=None)  # type: ignore[attr-defined]
            except Exception:
                payload = None
        return payload if isinstance(payload, dict) else None

    def _load_boxscore(
        game_id: int,
        *,
        allow_network: bool,
        force_network: bool = False,
    ) -> Optional[dict[str, Any]]:
        cached = _load_cached_boxscore(game_id)
        if cached is not None and not force_network:
            return cached
        if not allow_network:
            return cached
        try:
            raw = nhl.boxscore(game_id, force_network=force_network)
            return raw if isinstance(raw, dict) else cached
        except Exception:
            return cached

    def _load_pbp(
        game_id: int,
        *,
        allow_network: bool,
        force_network: bool = False,
    ) -> Optional[dict[str, Any]]:
        cached = _load_cached_pbp(game_id)
        if cached is not None and not force_network:
            return cached
        if not allow_network:
            return cached
        try:
            raw = nhl.play_by_play(game_id, force_network=force_network)
            return raw if isinstance(raw, dict) else cached
        except Exception:
            return cached

    def _load_player_landing(
        player_id: int,
        *,
        allow_network: bool,
        force_network: bool = False,
    ) -> Optional[dict[str, Any]]:
        if player_id <= 0:
            return None
        hit = player_landing_cache.get(int(player_id))
        if hit is not None and not force_network:
            return hit
        if not allow_network:
            return hit
        try:
            raw = nhl.player_landing(int(player_id), force_network=force_network)
            if isinstance(raw, dict):
                player_landing_cache[int(player_id)] = raw
                return raw
        except Exception:
            pass
        return hit

    def _clock_text_to_seconds(raw: Any) -> int:
        text = str(raw or "").strip()
        if not text:
            return 0
        parts = [p.strip() for p in text.split(":") if str(p).strip()]
        if not parts:
            return 0
        nums: list[int] = []
        for part in parts:
            if not part.isdigit():
                return 0
            nums.append(int(part))
        if len(nums) == 2:
            return (nums[0] * 60) + nums[1]
        if len(nums) == 3:
            return (nums[0] * 3600) + (nums[1] * 60) + nums[2]
        return 0

    def _goalie_activity_score(row: dict[str, Any]) -> int:
        if not isinstance(row, dict):
            return 0
        score = 0
        if bool(row.get("isOnIce")):
            score += 200_000
        toi_s = _clock_text_to_seconds(row.get("timeOnIce") or row.get("toi"))
        if toi_s > 0:
            score += 100_000 + toi_s
        shots_against = _to_int(row.get("shotsAgainst") or row.get("shots") or 0, default=0)
        saves = _to_int(row.get("saves") or 0, default=0)
        goals_against = _to_int(row.get("goalsAgainst") or max(0, shots_against - saves), default=0)
        if shots_against > 0 or saves > 0 or goals_against > 0:
            score += 10_000 + (shots_against * 100) + (saves * 10) + goals_against
        if str(row.get("decision") or "").strip():
            score += 1_000
        return score

    def _boxscore_has_confirmed_goalie(boxscore: Optional[dict[str, Any]], team_key: str) -> bool:
        if not isinstance(boxscore, dict):
            return False
        pstats = boxscore.get("playerByGameStats") if isinstance(boxscore.get("playerByGameStats"), dict) else {}
        team_blob = pstats.get(str(team_key)) if isinstance(pstats.get(str(team_key)), dict) else {}
        rows = team_blob.get("goalies") if isinstance(team_blob.get("goalies"), list) else []
        for row in rows:
            if not isinstance(row, dict):
                continue
            if bool(row.get("starter")):
                return True
            if _goalie_activity_score(row) > 0:
                return True
        return False

    def _club_stats_goalies(
        team_code: str,
        *,
        season_compact: str,
        allow_network: bool,
        force_network: bool = False,
    ) -> list[dict[str, Any]]:
        code = str(team_code or "").upper().strip()
        season_txt = str(season_compact or "").strip()
        if not code or not season_txt:
            return []
        key = (code, season_txt)
        cached = club_goalie_stats_cache.get(key)
        if isinstance(cached, list) and not force_network:
            return [x for x in cached if isinstance(x, dict)]
        if not allow_network:
            return [x for x in cached if isinstance(x, dict)] if isinstance(cached, list) else []
        rows: list[dict[str, Any]] = []
        try:
            payload = nhl.club_stats(
                code,
                season=season_txt,
                game_type=2,
                force_network=force_network,
            )
            data = payload.get("goalies") if isinstance(payload, dict) else []
            rows = [x for x in data if isinstance(x, dict)] if isinstance(data, list) else []
        except Exception:
            rows = []
        club_goalie_stats_cache[key] = rows
        return rows

    def _club_stats_skaters(
        team_code: str,
        *,
        season_compact: str,
        allow_network: bool,
        force_network: bool = False,
    ) -> list[dict[str, Any]]:
        code = str(team_code or "").upper().strip()
        season_txt = str(season_compact or "").strip()
        if not code or not season_txt:
            return []
        key = (code, season_txt)
        cached = club_skater_stats_cache.get(key)
        if isinstance(cached, list) and not force_network:
            return [x for x in cached if isinstance(x, dict)]
        if not allow_network:
            return [x for x in cached if isinstance(x, dict)] if isinstance(cached, list) else []
        rows: list[dict[str, Any]] = []
        try:
            payload = nhl.club_stats(
                code,
                season=season_txt,
                game_type=2,
                force_network=force_network,
            )
            data = payload.get("skaters") if isinstance(payload, dict) else []
            rows = [x for x in data if isinstance(x, dict)] if isinstance(data, list) else []
        except Exception:
            rows = []
        club_skater_stats_cache[key] = rows
        return rows

    def _period_length_seconds(period_num: int, game: Optional[dict[str, Any]] = None) -> int:
        p = int(period_num or 0)
        if p <= 0:
            return 1200
        if p <= 3:
            return 1200
        game_type = _to_int(
            (game or {}).get("gameType")
            or (game or {}).get("gameTypeId")
            or (game or {}).get("gameTypeCode")
            or 2,
            default=2,
        )
        # Regular-season OT is 5:00; playoff OT uses full 20:00 periods.
        return 300 if game_type == 2 else 1200

    def _elapsed_before_period(period_num: int, game: Optional[dict[str, Any]] = None) -> int:
        p = max(1, int(period_num or 1))
        out = 0
        for idx in range(1, p):
            out += _period_length_seconds(idx, game)
        return out

    def _fmt_mmss(seconds: float) -> str:
        total = max(0, int(round(float(seconds))))
        return f"{total // 60}:{total % 60:02d}"

    def _parse_situation_code(raw: Any) -> Optional[dict[str, int]]:
        txt = re.sub(r"[^0-9]", "", str(raw or "").strip())
        if len(txt) < 4:
            return None
        txt = txt[-4:]
        try:
            return {
                "away_goalie": int(txt[0]),
                "away_skaters": int(txt[1]),
                "home_skaters": int(txt[2]),
                "home_goalie": int(txt[3]),
            }
        except Exception:
            return None

    def _game_elapsed_seconds(game: dict[str, Any]) -> Optional[float]:
        period = _to_int(
            game.get("period")
            or ((game.get("periodDescriptor") or {}).get("number") if isinstance(game.get("periodDescriptor"), dict) else 0)
            or 0,
            default=0,
        )
        if period <= 0:
            return None
        clock = game.get("clock") if isinstance(game.get("clock"), dict) else {}
        rem_txt = str(clock.get("timeRemaining") or clock.get("time") or "").strip()
        mmss = _parse_mmss(rem_txt)
        if mmss is None:
            return None
        rem_s = (int(mmss[0]) * 60) + int(mmss[1])
        plen = _period_length_seconds(period, game)
        elapsed_in_period = max(0, min(plen, plen - rem_s))
        return float(_elapsed_before_period(period, game) + elapsed_in_period)

    def _play_elapsed_seconds(play: dict[str, Any], *, game: dict[str, Any]) -> Optional[float]:
        period = _to_int(
            ((play.get("periodDescriptor") or {}).get("number") if isinstance(play.get("periodDescriptor"), dict) else None)
            or ((play.get("period") or {}).get("number") if isinstance(play.get("period"), dict) else None)
            or 0,
            default=0,
        )
        if period <= 0:
            return None
        in_period_txt = str(play.get("timeInPeriod") or "").strip()
        mmss = _parse_mmss(in_period_txt)
        if mmss is None:
            rem_txt = str(play.get("timeRemaining") or "").strip()
            mmss_rem = _parse_mmss(rem_txt)
            if mmss_rem is None:
                return None
            plen = _period_length_seconds(period, game)
            rem_s = (int(mmss_rem[0]) * 60) + int(mmss_rem[1])
            elapsed_in_period = max(0, min(plen, plen - rem_s))
        else:
            elapsed_in_period = (int(mmss[0]) * 60) + int(mmss[1])
        return float(_elapsed_before_period(period, game) + elapsed_in_period)

    def _pbp_special_teams_context(
        game: dict[str, Any],
        pbp: dict[str, Any],
        *,
        away_code: str,
        home_code: str,
        away_id: int,
        home_id: int,
    ) -> dict[str, Any]:
        plays = pbp.get("plays") if isinstance(pbp.get("plays"), list) else []
        if not plays:
            return {
                "state_line": "",
                "away_state": "",
                "home_state": "",
                "away_taken": 0,
                "away_drawn": 0,
                "home_taken": 0,
                "home_drawn": 0,
                "pp_team": "",
                "pk_team": "",
                "pp_time_remaining": "",
            }

        now_elapsed = _game_elapsed_seconds(game)
        sorted_plays = sorted(
            [p for p in plays if isinstance(p, dict)],
            key=lambda p: _to_int(p.get("sortOrder") or p.get("eventId") or 0, default=0),
        )
        if now_elapsed is None:
            for play in reversed(sorted_plays):
                pe = _play_elapsed_seconds(play, game=game)
                if pe is not None:
                    now_elapsed = pe
                    break
        if now_elapsed is None:
            now_elapsed = 0.0

        taken = {away_code: 0, home_code: 0}
        drawn = {away_code: 0, home_code: 0}
        active_penalties: list[dict[str, Any]] = []
        latest_situation: Optional[dict[str, int]] = None

        for play in sorted_plays:
            play_elapsed = _play_elapsed_seconds(play, game=game)
            if play_elapsed is None:
                continue
            if play_elapsed > (float(now_elapsed) + 0.75):
                break

            active_penalties = [p for p in active_penalties if float(p.get("end", -1.0)) > float(play_elapsed)]

            sit = _parse_situation_code(play.get("situationCode"))
            if sit is not None:
                latest_situation = sit

            team_code = _play_team_code(
                play,
                away_code=away_code,
                home_code=home_code,
                away_id=away_id,
                home_id=home_id,
            )
            type_u = str(play.get("typeDescKey") or play.get("typeCode") or "").strip().lower()

            if type_u == "penalty" and team_code in taken:
                details = play.get("details") if isinstance(play.get("details"), dict) else {}
                duration_min = _to_int(details.get("duration") or details.get("durationMinutes") or 0, default=0)
                type_code = str(details.get("typeCode") or "").upper().strip()
                if duration_min > 0:
                    taken[team_code] += 1
                    other_code = home_code if team_code == away_code else away_code
                    drawn[other_code] += 1
                    if type_code not in {"MIS", "GAM", "MAT"}:
                        chunks: list[int]
                        if duration_min == 4:
                            chunks = [120, 120]
                        else:
                            chunks = [int(duration_min) * 60]
                        chunk_start = float(play_elapsed)
                        for chunk in chunks:
                            chunk_end = chunk_start + float(max(1, int(chunk)))
                            active_penalties.append(
                                {
                                    "team": team_code,
                                    "start": chunk_start,
                                    "end": chunk_end,
                                    "cancellable": (chunk <= 120 and type_code in {"MIN", "BEN"}),
                                }
                            )
                            chunk_start = chunk_end

            if type_u == "goal" and team_code in {away_code, home_code}:
                sit_goal = sit
                if sit_goal is None:
                    sit_goal = _parse_situation_code(play.get("situationCode"))
                if sit_goal is not None:
                    away_sk = int(sit_goal.get("away_skaters", 5))
                    home_sk = int(sit_goal.get("home_skaters", 5))
                    away_goalie = int(sit_goal.get("away_goalie", 1))
                    home_goalie = int(sit_goal.get("home_goalie", 1))
                    score_team_adv = (away_sk > home_sk) if team_code == away_code else (home_sk > away_sk)
                    # Avoid treating pulled-goalie extra attacker goals as PP goals.
                    if score_team_adv and away_goalie > 0 and home_goalie > 0:
                        conceded = home_code if team_code == away_code else away_code
                        cancellable = [
                            p
                            for p in active_penalties
                            if str(p.get("team") or "") == conceded
                            and bool(p.get("cancellable"))
                            and float(p.get("start", 0.0)) <= float(play_elapsed) < float(p.get("end", 0.0))
                        ]
                        if cancellable:
                            kill = min(cancellable, key=lambda p: float(p.get("end", 0.0)))
                            try:
                                active_penalties.remove(kill)
                            except Exception:
                                pass

        now_active = [
            p
            for p in active_penalties
            if float(p.get("start", 0.0)) <= float(now_elapsed) < float(p.get("end", 0.0))
        ]
        away_short = sum(1 for p in now_active if str(p.get("team") or "") == away_code)
        home_short = sum(1 for p in now_active if str(p.get("team") or "") == home_code)

        pp_team = ""
        pk_team = ""
        if away_short > home_short:
            pp_team = home_code
            pk_team = away_code
        elif home_short > away_short:
            pp_team = away_code
            pk_team = home_code
        elif latest_situation is not None:
            away_sk = int(latest_situation.get("away_skaters", 5))
            home_sk = int(latest_situation.get("home_skaters", 5))
            away_goalie = int(latest_situation.get("away_goalie", 1))
            home_goalie = int(latest_situation.get("home_goalie", 1))
            if away_goalie > 0 and home_goalie > 0 and away_sk != home_sk:
                if away_sk > home_sk:
                    pp_team = away_code
                    pk_team = home_code
                else:
                    pp_team = home_code
                    pk_team = away_code

        pp_time_remaining = ""
        if pp_team and pk_team:
            pk_penalties = [
                p
                for p in now_active
                if str(p.get("team") or "") == pk_team and float(p.get("end", 0.0)) > float(now_elapsed)
            ]
            if pk_penalties:
                next_end = min(float(p.get("end", 0.0)) for p in pk_penalties)
                pp_time_remaining = _fmt_mmss(max(0.0, next_end - float(now_elapsed)))

        away_state = ""
        home_state = ""
        state_line = ""
        if pp_team and pk_team:
            pp_txt = f"{pp_team} PP"
            if pp_time_remaining:
                pp_txt = f"{pp_txt} {pp_time_remaining}"
            state_line = pp_txt
            away_state = f"PP {pp_time_remaining}".strip() if pp_team == away_code else f"PK {pp_time_remaining}".strip()
            home_state = f"PP {pp_time_remaining}".strip() if pp_team == home_code else f"PK {pp_time_remaining}".strip()
        elif latest_situation is not None:
            away_sk = int(latest_situation.get("away_skaters", 5))
            home_sk = int(latest_situation.get("home_skaters", 5))
            away_goalie = int(latest_situation.get("away_goalie", 1))
            home_goalie = int(latest_situation.get("home_goalie", 1))
            if away_goalie > 0 and home_goalie > 0 and away_sk == home_sk and away_sk in {3, 4}:
                state_line = f"{away_sk}v{home_sk}"
                away_state = state_line
                home_state = state_line

        return {
            "state_line": state_line,
            "away_state": away_state,
            "home_state": home_state,
            "away_taken": int(taken.get(away_code, 0)),
            "away_drawn": int(drawn.get(away_code, 0)),
            "home_taken": int(taken.get(home_code, 0)),
            "home_drawn": int(drawn.get(home_code, 0)),
            "pp_team": pp_team,
            "pk_team": pk_team,
            "pp_time_remaining": pp_time_remaining,
        }

    def _player_name_map(pbp: dict[str, Any]) -> dict[int, str]:
        out: dict[int, str] = {}
        for row in pbp.get("rosterSpots") or []:
            if not isinstance(row, dict):
                continue
            pid = _to_int(row.get("playerId") or 0, default=0)
            if pid <= 0:
                continue
            first = _pick_text(row.get("firstName"))
            last = _pick_text(row.get("lastName"))
            full = " ".join([x for x in (first, last) if x]).strip()
            if full:
                out[pid] = full
        return out

    def _play_team_code(
        play: dict[str, Any],
        *,
        away_code: str,
        home_code: str,
        away_id: int,
        home_id: int,
    ) -> str:
        details = play.get("details") if isinstance(play.get("details"), dict) else {}
        owner_id = _to_int(details.get("eventOwnerTeamId") or 0, default=0)
        if owner_id > 0:
            if away_id > 0 and owner_id == away_id:
                return away_code
            if home_id > 0 and owner_id == home_id:
                return home_code
        team = play.get("team") if isinstance(play.get("team"), dict) else {}
        code = _norm_abbrev(
            team.get("abbrev")
            or team.get("abbreviation")
            or team.get("shortDisplayName")
            or team.get("displayName"),
            fallback="",
        ).upper()
        if code in {away_code, home_code}:
            return code
        return ""

    def _pbp_event_pack(
        game: dict[str, Any],
        pbp: dict[str, Any],
        *,
        away_code: str,
        home_code: str,
    ) -> dict[str, Any]:
        away_id = _to_int(
            ((game.get("awayTeam") or {}).get("id") if isinstance(game.get("awayTeam"), dict) else None)
            or ((pbp.get("awayTeam") or {}).get("id") if isinstance(pbp.get("awayTeam"), dict) else None)
            or 0,
            default=0,
        )
        home_id = _to_int(
            ((game.get("homeTeam") or {}).get("id") if isinstance(game.get("homeTeam"), dict) else None)
            or ((pbp.get("homeTeam") or {}).get("id") if isinstance(pbp.get("homeTeam"), dict) else None)
            or 0,
            default=0,
        )
        names_by_id = _player_name_map(pbp)
        plays = pbp.get("plays") if isinstance(pbp.get("plays"), list) else []

        shot_by_period: dict[int, dict[str, int]] = {}
        stats: dict[str, dict[str, int]] = {
            away_code: {
                "faceoff_wins": 0,
                "hits": 0,
                "blocked": 0,
                "giveaways": 0,
                "takeaways": 0,
                "pim": 0,
            },
            home_code: {
                "faceoff_wins": 0,
                "hits": 0,
                "blocked": 0,
                "giveaways": 0,
                "takeaways": 0,
                "pim": 0,
            },
        }
        seen_types: set[str] = set()
        penalties_rows: list[dict[str, Any]] = []

        for play in plays:
            if not isinstance(play, dict):
                continue
            type_u = str(play.get("typeDescKey") or "").strip().lower()
            if not type_u:
                type_u = str(play.get("typeCode") or "").strip().lower()
            if not type_u:
                continue
            seen_types.add(type_u)

            period = _to_int(
                ((play.get("periodDescriptor") or {}).get("number") if isinstance(play.get("periodDescriptor"), dict) else None)
                or ((play.get("period") or {}).get("number") if isinstance(play.get("period"), dict) else None)
                or 0,
                default=0,
            )
            team_code = _play_team_code(
                play,
                away_code=away_code,
                home_code=home_code,
                away_id=away_id,
                home_id=home_id,
            )

            if type_u in {"shot-on-goal", "goal"} and team_code in {away_code, home_code} and period > 0:
                period_bucket = shot_by_period.setdefault(period, {away_code: 0, home_code: 0})
                period_bucket[team_code] += 1

            if team_code not in stats:
                continue

            if type_u == "faceoff":
                stats[team_code]["faceoff_wins"] += 1
            elif type_u == "hit":
                stats[team_code]["hits"] += 1
            elif type_u == "blocked-shot":
                stats[team_code]["blocked"] += 1
            elif type_u == "giveaway":
                stats[team_code]["giveaways"] += 1
            elif type_u == "takeaway":
                stats[team_code]["takeaways"] += 1
            elif type_u == "penalty":
                details = play.get("details") if isinstance(play.get("details"), dict) else {}
                duration = _to_int(details.get("duration") or details.get("durationMinutes") or 0, default=0)
                if duration > 0:
                    stats[team_code]["pim"] += duration

                committed_id = _to_int(details.get("committedByPlayerId") or 0, default=0)
                drawn_id = _to_int(details.get("drawnByPlayerId") or 0, default=0)
                committed = names_by_id.get(committed_id, "")
                drawn = names_by_id.get(drawn_id, "")
                infraction = str(details.get("descKey") or details.get("reason") or "").strip().replace("-", " ")
                if infraction:
                    infraction = infraction.title()
                if not infraction:
                    infraction = "Penalty"
                mins_txt = f"{int(duration)} min" if duration > 0 else "[NF]"
                offender_txt = committed if committed else "[NF]"
                target_txt = f" on {drawn}" if drawn else ""
                desc = f"{offender_txt} {mins_txt} for {infraction}{target_txt}"
                penalties_rows.append(
                    {
                        "period": period,
                        "time": str(play.get("timeInPeriod") or "").strip() or "[NF]",
                        "team": team_code,
                        "minutes": int(duration) if duration > 0 else 0,
                        "infraction": infraction or "Penalty",
                        "desc": desc,
                    }
                )

        special_teams = _pbp_special_teams_context(
            game,
            pbp,
            away_code=away_code,
            home_code=home_code,
            away_id=away_id,
            home_id=home_id,
        )
        return {
            "shot_by_period": shot_by_period,
            "stats": stats,
            "seen_types": seen_types,
            "penalties": penalties_rows,
            "special_teams": special_teams,
            "has_plays": bool(plays),
        }

    def _espn_team_stat_values(
        summary: dict[str, Any],
        *,
        away_code: str,
        home_code: str,
    ) -> dict[str, tuple[str, str]]:
        boxscore = summary.get("boxscore") if isinstance(summary.get("boxscore"), dict) else {}
        teams = boxscore.get("teams") if isinstance(boxscore.get("teams"), list) else []
        away_stats: dict[str, str] = {}
        home_stats: dict[str, str] = {}
        for row in teams:
            if not isinstance(row, dict):
                continue
            side = str(row.get("homeAway") or "").strip().lower()
            stats_list = row.get("statistics") if isinstance(row.get("statistics"), list) else []
            target = away_stats if side == "away" else home_stats if side == "home" else None
            if target is None:
                continue
            for item in stats_list:
                if not isinstance(item, dict):
                    continue
                key = str(item.get("name") or item.get("label") or item.get("abbreviation") or "").strip().lower()
                val = str(item.get("displayValue") or item.get("value") or "").strip()
                if key and val and key not in target:
                    target[key] = val

        def _pick(*keys: str) -> tuple[str, str]:
            for key in keys:
                k = str(key).lower()
                av = away_stats.get(k)
                hv = home_stats.get(k)
                if av is not None or hv is not None:
                    return (av or "[NF]", hv or "[NF]")
            return ("[NF]", "[NF]")

        return {
            "shots_on_goal": _pick("shots on goal", "shots"),
            "faceoff_pct": _pick("faceoff %", "faceoffs won", "faceoffwins"),
            "power_play": _pick("power play", "powerPlay"),
            "penalty_minutes": _pick("penalty minutes", "penaltyMinutes", "pim"),
            "hits": _pick("hits"),
            "blocked_shots": _pick("blocked shots", "blocked"),
            "giveaways": _pick("giveaways"),
            "takeaways": _pick("takeaways"),
        }

    def _penalties_from_espn_summary(
        summary: dict[str, Any],
        *,
        away_code: str,
        home_code: str,
    ) -> list[dict[str, Any]]:
        plays = summary.get("plays") if isinstance(summary.get("plays"), list) else []
        out: list[dict[str, Any]] = []
        for play in plays:
            if not isinstance(play, dict):
                continue
            txt = str(play.get("text") or "").strip()
            if "penalty" not in txt.lower():
                continue
            period = _to_int(
                ((play.get("period") or {}).get("number") if isinstance(play.get("period"), dict) else None) or 0,
                default=0,
            )
            clock = play.get("clock") if isinstance(play.get("clock"), dict) else {}
            clock_txt = str(clock.get("displayValue") or clock.get("value") or "").strip() or "[NF]"
            team = play.get("team") if isinstance(play.get("team"), dict) else {}
            code = _norm_abbrev(
                team.get("abbreviation") or team.get("shortDisplayName") or team.get("displayName"),
                fallback="",
            ).upper()
            if code not in {away_code, home_code}:
                code = "[NF]"
            out.append(
                {
                    "period": period,
                    "time": clock_txt,
                    "team": code,
                    "minutes": _penalty_minutes_from_text(txt),
                    "desc": txt or "[NF]",
                }
            )
        return out

    def _selected_date() -> dt.date:
        return dmin + dt.timedelta(days=int(day_var.get()))

    def _remember_game_win_probs(games: list[dict[str, Any]]) -> None:
        for g in games:
            if not isinstance(g, dict):
                continue
            gid = _to_int(g.get("id") or g.get("gameId") or 0, default=0)
            if gid <= 0:
                continue
            odds_probs = _implied_probs_from_game_odds(g)
            if odds_probs is not None:
                game_win_probs_by_id[gid] = odds_probs

    def _build_cached_game_win_prob_index() -> None:
        nonlocal game_win_prob_index_built
        if game_win_prob_index_built:
            return
        game_win_prob_index_built = True
        season_u = str(season or "").strip()
        if not season_u:
            return
        roots = [
            Path("cache") / "online" / "nhl" / season_u,
            Path("MoneyPuck Data") / "cache" / "nhl" / season_u,
        ]
        for root in roots:
            if not root.exists() or not root.is_dir():
                continue
            for p in root.rglob("*.json"):
                try:
                    payload = json.loads(p.read_text())
                except Exception:
                    continue
                if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
                    payload = payload.get("data")
                if not isinstance(payload, dict):
                    continue
                games = payload.get("games")
                if not isinstance(games, list):
                    continue
                _remember_game_win_probs([x for x in games if isinstance(x, dict)])

    def _moneypuck_game_cache_key(season_compact: str, game_id: int) -> str:
        return f"moneypuck/gamedata/{str(season_compact).strip()}/{int(game_id)}.csv"

    def _get_moneypuck_game_data_csv(
        game: dict[str, Any],
        selected_date: dt.date,
        *,
        allow_network: bool,
        force_network: bool = False,
    ) -> Optional[str]:
        gid = _to_int(game.get("id") or game.get("gameId") or 0, default=0)
        if gid <= 0:
            return None

        season_candidates = _moneypuck_season_candidates_for_game(
            season_text=season,
            selected_date=selected_date,
            game_id=gid,
        )
        live_like = selected_date >= today
        ttl = MONEYPUCK_GAMEDATA_LIVE_TTL_S if live_like else None

        if not force_network:
            for season_compact in season_candidates:
                key = _moneypuck_game_cache_key(season_compact, gid)
                try:
                    blob = nhl.cache.get_bytes(key, ttl_s=ttl)  # type: ignore[attr-defined]
                except Exception:
                    blob = None
                if not blob:
                    continue
                try:
                    txt = blob.decode("utf-8", errors="ignore")
                except Exception:
                    continue
                if "liveAwayTeamWinOverallScore" in txt:
                    return txt

        if not allow_network:
            return None
        now_s = time.time()
        if not force_network:
            last_try = float(game_moneypuck_last_try_s.get(gid, 0.0) or 0.0)
            if (now_s - last_try) < MONEYPUCK_RETRY_S:
                return None
        game_moneypuck_last_try_s[gid] = now_s

        for season_compact in season_candidates:
            url = _moneypuck_gamedata_csv_url(season_compact, gid)
            try:
                resp = requests.get(url, headers=MONEYPUCK_HEADERS, timeout=MONEYPUCK_GAMEDATA_TIMEOUT_S)
                if int(resp.status_code) >= 400:
                    continue
                txt = str(resp.text or "")
                if "liveAwayTeamWinOverallScore" not in txt:
                    continue
                try:
                    nhl.cache.set_bytes(  # type: ignore[attr-defined]
                        _moneypuck_game_cache_key(season_compact, gid),
                        txt.encode("utf-8"),
                    )
                except Exception:
                    pass
                return txt
            except Exception:
                continue
        return None

    def _get_moneypuck_game_probs(
        game: dict[str, Any],
        selected_date: dt.date,
        *,
        allow_network: bool,
        force_network: bool = False,
    ) -> Optional[tuple[float, float]]:
        gid = _to_int(game.get("id") or game.get("gameId") or 0, default=0)
        if gid <= 0:
            return None
        txt = _get_moneypuck_game_data_csv(
            game,
            selected_date,
            allow_network=allow_network,
            force_network=force_network,
        )
        if txt:
            pair = _parse_latest_game_data_win_probs(txt)
            if pair is not None:
                game_moneypuck_probs[gid] = pair
                game_moneypuck_probs_ts[gid] = time.time()
                return pair
        if allow_network and force_network:
            # A forced live refetch that returns no usable CSV should not keep
            # serving an old probability snapshot for this game.
            game_moneypuck_probs.pop(gid, None)
            game_moneypuck_probs_ts.pop(gid, None)
        pair_cached = game_moneypuck_probs.get(gid)
        if pair_cached is None:
            return None
        if selected_date >= today:
            ts_cached = float(game_moneypuck_probs_ts.get(gid, 0.0) or 0.0)
            if ts_cached <= 0.0 or (time.time() - ts_cached) > float(MONEYPUCK_GAMEDATA_LIVE_TTL_S):
                return None
        return pair_cached

    def _prefetch_moneypuck_game_probs_for_day(
        d: dt.date,
        games_now: list[dict[str, Any]],
        *,
        allow_network: bool,
        force_network: bool = False,
    ) -> None:
        for gg in games_now:
            if not isinstance(gg, dict):
                continue
            if str(gg.get("league") or "").upper() != "NHL":
                continue
            if _is_olympic_game(gg):
                continue
            try:
                _get_moneypuck_game_probs(
                    gg,
                    d,
                    allow_network=allow_network,
                    force_network=force_network,
                )
            except Exception:
                continue

    def _get_moneypuck_probs_for_date(
        d: dt.date,
        *,
        allow_network: bool,
        force_network: bool = False,
    ) -> dict[tuple[str, str], tuple[float, float]]:
        cached = day_moneypuck_probs.get(d)
        if cached is not None and not force_network:
            return cached
        if not allow_network:
            return cached or {}
        now_s = time.time()
        if not force_network:
            last_try = float(day_moneypuck_last_try_s.get(d, 0.0) or 0.0)
            if (now_s - last_try) < MONEYPUCK_RETRY_S:
                return cached or {}
        day_moneypuck_last_try_s[d] = now_s
        html_text = _download_moneypuck_predictions_html(d)
        if not html_text:
            if cached is None:
                day_moneypuck_probs[d] = {}
                return {}
            return cached

        rows = _parse_moneypuck_prediction_rows(html_text, selected_date=d)
        exact: dict[tuple[str, str], tuple[float, float]] = {}
        unknown_date: dict[tuple[str, str], tuple[float, float]] = {}
        for row_date, code_a, pct_a, code_b, pct_b in rows:
            if code_a not in NHL_TEAM_CODES or code_b not in NHL_TEAM_CODES:
                continue
            if row_date is not None and row_date != d:
                continue
            bucket = exact if row_date == d else unknown_date
            key = (code_a, code_b)
            rev = (code_b, code_a)
            bucket[key] = (pct_a, pct_b)
            bucket[rev] = (pct_b, pct_a)

        out = dict(unknown_date)
        out.update(exact)
        if out:
            day_moneypuck_probs[d] = out
            return out
        if cached is None:
            day_moneypuck_probs[d] = {}
            return {}
        # Keep last known percentages for active games if refresh returns empty.
        return cached

    def _team_points_pct_by_date(d: dt.date) -> dict[str, float]:
        cached = day_points_pct_cache.get(d)
        if isinstance(cached, dict):
            return cached

        points: dict[str, int] = {}
        games_played: dict[str, int] = {}
        for row in _read_season_series_rows():
            if str(row.get("league") or "").upper() != "NHL":
                continue
            row_day = row.get("date")
            if not isinstance(row_day, dt.date) or row_day > d:
                continue
            if not _is_final_state_text(row.get("state")):
                continue
            away_code = str(row.get("away_code") or "").upper()
            home_code = str(row.get("home_code") or "").upper()
            if away_code not in NHL_TEAM_CODES or home_code not in NHL_TEAM_CODES:
                continue
            away_score = _to_int(row.get("away_score") or 0, default=0)
            home_score = _to_int(row.get("home_score") or 0, default=0)
            if away_score == home_score:
                continue
            status_text = str(row.get("status_text") or "").upper()
            ot_or_so = ("OT" in status_text) or ("SO" in status_text)

            games_played[away_code] = int(games_played.get(away_code, 0)) + 1
            games_played[home_code] = int(games_played.get(home_code, 0)) + 1
            if away_score > home_score:
                points[away_code] = int(points.get(away_code, 0)) + 2
                points[home_code] = int(points.get(home_code, 0)) + (1 if ot_or_so else 0)
            else:
                points[home_code] = int(points.get(home_code, 0)) + 2
                points[away_code] = int(points.get(away_code, 0)) + (1 if ot_or_so else 0)

        out: dict[str, float] = {}
        for code, gp in games_played.items():
            if int(gp) <= 0:
                continue
            out[code] = max(0.0, min(1.0, float(points.get(code, 0)) / float(2 * int(gp))))
        day_points_pct_cache[d] = out
        return out

    def _implied_probs_from_points_cache(
        game: dict[str, Any],
        selected_date: dt.date,
    ) -> Optional[tuple[float, float]]:
        away_code, home_code = _game_codes(game)
        if away_code not in NHL_TEAM_CODES or home_code not in NHL_TEAM_CODES:
            return None
        ppct = _team_points_pct_by_date(selected_date)
        away_ppct = ppct.get(away_code)
        home_ppct = ppct.get(home_code)
        if away_ppct is None or home_ppct is None:
            return None
        home_prob = 0.5 + ((float(home_ppct) - float(away_ppct)) * 0.90) + 0.04
        home_prob = max(0.01, min(0.99, float(home_prob)))
        away_prob = 1.0 - home_prob
        return away_prob, home_prob

    def _standings_context_by_date(
        d: dt.date,
        *,
        allow_network: bool,
        force_network: bool = False,
    ) -> dict[str, dict[str, Any]]:
        cached = day_standings_context_cache.get(d)
        if cached is not None and not force_network:
            return cached
        if not allow_network:
            return cached or {}
        now_s = time.time()
        if not force_network:
            last_try = float(day_standings_last_try_s.get(d, 0.0) or 0.0)
            if (now_s - last_try) < NHL_STANDINGS_RETRY_S:
                return cached or {}
        day_standings_last_try_s[d] = now_s

        try:
            payload = nhl.standings(d, force_network=force_network)
        except Exception:
            return cached or {}
        rows = payload.get("standings") if isinstance(payload, dict) else []
        if not isinstance(rows, list):
            return cached or {}

        parsed: dict[str, dict[str, Any]] = {}
        conf_buckets: dict[str, list[dict[str, Any]]] = {"E": [], "W": []}
        for row in rows:
            if not isinstance(row, dict):
                continue
            team_obj = row.get("teamAbbrev")
            code = _norm_abbrev(_pick_text(team_obj), fallback="").upper()
            if code not in NHL_TEAM_CODES:
                continue
            conf = str(row.get("conferenceAbbrev") or "").strip().upper()
            if conf not in {"E", "W"}:
                continue
            div = str(row.get("divisionAbbrev") or "").strip().upper()
            points = _to_int(row.get("points") or 0, default=0)
            gp = _to_int(row.get("gamesPlayed") or 0, default=0)
            pace = (float(points) * 82.0 / float(gp)) if gp > 0 else None
            item = {
                "team": code,
                "conference": conf,
                "conference_rank": _to_int(row.get("conferenceSequence") or 0, default=999),
                "division": div,
                "division_rank": _to_int(row.get("divisionSequence") or 0, default=999),
                "wildcard_rank": _to_int(row.get("wildcardSequence") or 0, default=0),
                "points": int(points),
                "games_played": int(gp),
                "pace": pace,
                "row": _to_int(row.get("regulationPlusOtWins") or 0, default=0),
                "rw": _to_int(row.get("regulationWins") or 0, default=0),
            }
            parsed[code] = item
            conf_buckets.setdefault(conf, []).append(item)

        for conf, bucket in conf_buckets.items():
            conf_rows = sorted(
                bucket,
                key=lambda r: (
                    _to_int(r.get("conference_rank") or 0, default=999),
                    -_to_int(r.get("points") or 0, default=0),
                    str(r.get("team") or ""),
                ),
            )
            if not conf_rows:
                continue
            in_line_pts = _to_int(conf_rows[7].get("points") if len(conf_rows) > 7 else conf_rows[-1].get("points"), default=0)
            out_line_pts = _to_int(conf_rows[8].get("points") if len(conf_rows) > 8 else in_line_pts, default=in_line_pts)
            for row in conf_rows:
                conf_rank = _to_int(row.get("conference_rank") or 0, default=999)
                pts = _to_int(row.get("points") or 0, default=0)
                if conf_rank <= 8:
                    row["wc_gap"] = int(pts - out_line_pts)
                else:
                    row["wc_gap"] = int(pts - in_line_pts)

        day_standings_context_cache[d] = parsed
        return parsed

    def _team_standings_ribbon(
        team_code: str,
        selected_date: dt.date,
        *,
        allow_network: bool,
    ) -> Optional[str]:
        code = str(team_code or "").upper().strip()
        if code not in NHL_TEAM_CODES:
            return None
        context = _standings_context_by_date(selected_date, allow_network=allow_network, force_network=False)
        row = context.get(code)
        if not isinstance(row, dict):
            return None
        div_rank = _to_int(row.get("division_rank") or 0, default=0)
        div = str(row.get("division") or "").strip().upper()
        # Keep ribbon focused on division placement only.
        return f"{div}{div_rank}" if div and div_rank > 0 else None

    def _future_win_prediction_labels(
        game: dict[str, Any],
        selected_date: dt.date,
    ) -> tuple[Optional[str], Optional[str]]:
        if str(game.get("league") or "").upper() != "NHL":
            return None, None
        away_code, home_code = _game_codes(game)
        if away_code not in NHL_TEAM_CODES or home_code not in NHL_TEAM_CODES:
            return None, None

        def _best_dynamic_odds_pair() -> Optional[tuple[float, float]]:
            odds_pair = _implied_probs_from_game_odds(game)
            if odds_pair is None:
                gid = _to_int(game.get("id") or game.get("gameId") or 0, default=0)
                if gid > 0:
                    odds_pair = game_win_probs_by_id.get(gid)
                    if odds_pair is None:
                        _build_cached_game_win_prob_index()
                        odds_pair = game_win_probs_by_id.get(gid)
            if odds_pair is None:
                odds_pair = _implied_probs_from_records(game)
            if odds_pair is None:
                odds_pair = _implied_probs_from_points_cache(game, selected_date)
            return odds_pair

        state = _game_state(game)
        is_live = state in {"LIVE", "CRIT"}
        gid = _to_int(game.get("id") or game.get("gameId") or 0, default=0)
        live_clock_running = bool(selected_date == today and _is_live_clock_running(game))
        force_live_event_fetch = False
        if live_clock_running and gid > 0:
            now_s = time.time()
            last_force = float(game_moneypuck_live_force_try_s.get(gid, 0.0) or 0.0)
            # Pull newest gameData rows frequently enough to track live events
            # while avoiding duplicate requests within a single render burst.
            if (now_s - last_force) >= 2.5:
                force_live_event_fetch = True
                game_moneypuck_live_force_try_s[gid] = now_s
        game_data_pair = _get_moneypuck_game_probs(
            game,
            selected_date,
            allow_network=live_clock_running,
            force_network=force_live_event_fetch,
        )
        probs = _get_moneypuck_probs_for_date(selected_date, allow_network=(selected_date == today))
        row = probs.get((away_code, home_code))

        if game_data_pair is not None:
            away_pct, home_pct = (
                float(game_data_pair[0]) * 100.0,
                float(game_data_pair[1]) * 100.0,
            )
        elif is_live:
            odds_pair_live = _best_dynamic_odds_pair()
            if odds_pair_live is not None:
                away_pct, home_pct = (float(odds_pair_live[0]) * 100.0, float(odds_pair_live[1]) * 100.0)
            elif row is not None:
                away_pct, home_pct = row
            else:
                return None, None
        elif row is not None:
            away_pct, home_pct = row
        else:
            odds_pair = _best_dynamic_odds_pair()
            if odds_pair is None:
                return None, None
            away_pct, home_pct = (float(odds_pair[0]) * 100.0, float(odds_pair[1]) * 100.0)

        def _fmt_pct(v: float) -> str:
            vv = max(0.0, min(100.0, float(v)))
            return f"{vv:.2f}%"

        return _fmt_pct(away_pct), _fmt_pct(home_pct)

    def _has_game_moneypuck_probs_for_date(
        d: dt.date,
        games_now: list[dict[str, Any]],
    ) -> bool:
        saw_nhl_regular = False
        for gg in games_now:
            if not isinstance(gg, dict):
                continue
            if str(gg.get("league") or "").upper() != "NHL":
                continue
            if _is_olympic_game(gg):
                continue
            saw_nhl_regular = True
            pair = _get_moneypuck_game_probs(gg, d, allow_network=False)
            if pair is None:
                return False
        return saw_nhl_regular

    def _planned_sources_for_date(d: dt.date) -> tuple[bool, bool, bool]:
        """
        Returns (need_nhl, need_olympics, need_pwhl) for this date.
        Plan is cache-first and memoized per-day, with a one-shot lightweight
        probe fallback when cache has no source evidence yet.
        """
        if d in day_source_plan and d != today:
            return day_source_plan[d]

        # 1) Cache-only evidence (fast path).
        nhl_regular = False
        nhl_olympic = False
        pwhl_any = False
        olympics_any = False
        try:
            raw_cached, _msg, _stamp = _get_score_payload(d, prefer_cached=True, allow_network=False)
            nhl_games = [g for g in list(raw_cached.get("games") or []) if isinstance(g, dict)]
            nhl_ol = [g for g in nhl_games if _is_olympic_game(g)]
            nhl_rg = [g for g in nhl_games if not _is_olympic_game(g)]
            nhl_regular = bool(nhl_rg)
            nhl_olympic = bool(nhl_ol)
        except Exception:
            pass
        try:
            eo, _ep, _estamp = _fetch_espn_games(d, allow_network=False)
            olympics_any = bool(eo)
        except Exception:
            pass
        try:
            pd, _pstamp = _fetch_pwhl_games(d, allow_network=False)
            pwhl_any = pwhl_any or bool(pd)
        except Exception:
            pass

        # NHL fallback can carry Olympic games.
        olympics_any = olympics_any or nhl_olympic

        # 2) If unknown from cache, do one lightweight probe.
        if not (nhl_regular or olympics_any or pwhl_any):
            try:
                raw_probe, _msg, _stamp = _get_score_payload(
                    d, prefer_cached=False, allow_network=True, force_network=False
                )
                probe_games = [g for g in list(raw_probe.get("games") or []) if isinstance(g, dict)]
                nhl_ol = [g for g in probe_games if _is_olympic_game(g)]
                nhl_rg = [g for g in probe_games if not _is_olympic_game(g)]
                nhl_regular = bool(nhl_rg)
                olympics_any = olympics_any or bool(nhl_ol)
            except Exception:
                pass
            try:
                eo, _ep, _estamp = _fetch_espn_games(d, allow_network=True, force_network=False)
                olympics_any = olympics_any or bool(eo)
            except Exception:
                pass
            try:
                pd, _pstamp = _fetch_pwhl_games(d, allow_network=True, force_network=False)
                pwhl_any = pwhl_any or bool(pd)
            except Exception:
                pass

        # Keep NHL enabled on "today" so auto-refresh can recover from stale/empty cache.
        plan = ((True if d == today else nhl_regular), olympics_any, pwhl_any)
        if d != today:
            day_source_plan[d] = plan
        return plan

    def _cancel_refresh() -> None:
        nonlocal refresh_after_id
        if refresh_after_id is not None:
            try:
                bgroot.after_cancel(refresh_after_id)
            except Exception:
                pass
            refresh_after_id = None

    def _should_auto_refresh(d: dt.date) -> bool:
        # Auto-refresh only when looking at today and the day is not finalized.
        return auto_refresh_enabled and d == today and not _is_day_finalized(d)

    def _auto_refresh_tick() -> None:
        nonlocal refresh_after_id
        refresh_after_id = None
        d = _selected_date()
        if not _should_auto_refresh(d):
            return
        _run_refresh_async(d, force_manual=False, reason="Auto refresh")

    def _schedule_auto_refresh() -> None:
        _cancel_refresh()
        if refresh_inflight:
            return
        d = _selected_date()
        if not _should_auto_refresh(d):
            return
        nonlocal refresh_after_id
        delay_ms = int(auto_refresh_s * 1000)
        if not auto_refresh_has_active_games:
            now_local = dt.datetime.now(tz)
            next_minute = (now_local + dt.timedelta(minutes=1)).replace(second=0, microsecond=0)
            delay_ms = max(250, int((next_minute - now_local).total_seconds() * 1000))
        refresh_after_id = bgroot.after(delay_ms, _auto_refresh_tick)

    def _clear_cards() -> None:
        nonlocal cards
        for c in cards:
            if c.scorer_popup is not None:
                try:
                    c.scorer_popup.destroy()
                except Exception:
                    pass
                c.scorer_popup = None
            c.frame.destroy()
        cards = []

    def _clear_section_labels() -> None:
        nonlocal section_labels
        for lbl in section_labels:
            try:
                lbl.destroy()
            except Exception:
                pass
        section_labels = []

    def _make_card() -> _Card:
        # Frame stays on page background; inner panel is the visible box.
        # This lets logos sit "above" the panel for the bleed effect.
        f = tk.Frame(grid_host, bg=BG, bd=0, highlightthickness=0)
        f.grid_propagate(False)
        panel = tk.Frame(f, bg=CARD_BG, bd=0, highlightthickness=0)
        overlay = tk.Canvas(f, bg=BG, bd=0, highlightthickness=0)

        score_font = tkfont.Font(family="Helvetica", size=44, weight="normal")
        dash_font = tkfont.Font(family="Helvetica", size=50, weight="normal")
        at_font = tkfont.Font(family="Helvetica", size=26, weight="bold")
        mid_font = tkfont.Font(family="Helvetica", size=14, weight="normal")
        status_font = tkfont.Font(family="Helvetica", size=14, weight="normal")

        return _Card(
            frame=f,
            panel=panel,
            overlay=overlay,
            img_refs=[],
            score_font=score_font,
            dash_font=dash_font,
            at_font=at_font,
            mid_font=mid_font,
            status_font=status_font,
        )

    def _goal_scorer_lines(
        g: dict[str, Any],
        away_code: str,
        home_code: str,
        *,
        allow_network: bool = True,
    ) -> tuple[list[str], list[str]]:
        away_up = away_code.upper()
        home_up = home_code.upper()
        olympics_elapsed_clock = _is_olympic_game(g)
        left: list[str] = []
        right: list[str] = []

        def _to_name(v: Any) -> str:
            if isinstance(v, str):
                return v.strip()
            if isinstance(v, dict):
                for key in ("name", "fullName", "displayName", "default", "en", "shortName"):
                    vv = v.get(key)
                    if isinstance(vv, str) and vv.strip():
                        return vv.strip()
                athlete = v.get("athlete")
                if isinstance(athlete, dict):
                    dv = athlete.get("displayName")
                    if isinstance(dv, str) and dv.strip():
                        return dv.strip()
            return ""

        def _to_time(v: Any) -> str:
            def _period_text_from(raw: Any) -> str:
                if isinstance(raw, dict):
                    ptype = str(raw.get("periodType") or raw.get("type") or "").strip().upper()
                    pnum = raw.get("number")
                    if ptype in {"OT", "SO"}:
                        return ptype
                    if isinstance(pnum, int):
                        return _period_suffix(pnum)
                    return ""
                if isinstance(raw, str):
                    s = raw.strip().upper()
                    if s in {"OT", "SO"}:
                        return s
                    if s.isdigit():
                        return _period_suffix(int(s))
                if isinstance(raw, (int, float)):
                    return _period_suffix(int(raw))
                return ""

            if isinstance(v, str):
                t = v.strip()
                return t
            if isinstance(v, dict):
                period_txt = (
                    _period_text_from(v.get("periodDescriptor"))
                    or _period_text_from(v.get("period"))
                    or _period_text_from(v.get("periodNumber"))
                    or _period_text_from(v.get("periodNum"))
                    or _period_text_from(v.get("periodType"))
                )
                for key in ("timeInPeriod", "timeRemaining", "periodTime", "displayTime", "clock"):
                    vv = v.get(key)
                    if isinstance(vv, str) and vv.strip():
                        ts = vv.strip()
                        if period_txt and " - " not in ts:
                            return f"{period_txt} - {ts}"
                        return ts
                vv = v.get("time")
                if isinstance(vv, str) and vv.strip():
                    ts = vv.strip()
                    if period_txt and " - " not in ts:
                        return f"{period_txt} - {ts}"
                    return ts
            return ""

        def _line_sort_key(line: str, idx: int) -> tuple[int, int, int]:
            # Chronological order:
            # period ascending (1st -> 2nd -> 3rd -> OT -> SO),
            # then clock descending (time remaining high -> low).
            txt = ""
            m = re.search(r"\(([^)]*)\)\s*$", line)
            if m:
                txt = m.group(1).strip().upper()
            period_order = 99
            for token, ordv in (("1ST", 1), ("2ND", 2), ("3RD", 3), ("OT", 4), ("SO", 5)):
                if token in txt:
                    period_order = ordv
                    break
            mm = re.search(r"\b(\d{1,2}):(\d{2})\b", txt)
            rem_sort = 9999
            if mm:
                mins = int(mm.group(1))
                secs = int(mm.group(2))
                rem_sort = -(mins * 60 + secs)
            return (period_order, rem_sort, idx)

        def _sort_chronological(lines: list[str]) -> list[str]:
            return [line for idx, line in sorted(enumerate(lines), key=lambda t: _line_sort_key(t[1], t[0]))]

        def _has_timed_line(lines: list[str]) -> bool:
            for line in lines:
                if re.search(r"\(\s*[^)]*\d{1,2}:\d{2}\s*\)\s*$", str(line)):
                    return True
            return False

        def _elapsed_to_remaining(ttxt: str) -> str:
            m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*$", ttxt)
            if not m:
                return ttxt
            elapsed = int(m.group(1)) * 60 + int(m.group(2))
            # Treat PBP fallback as elapsed clock and convert to remaining.
            if 0 <= elapsed <= 20 * 60:
                rem = max(0, 20 * 60 - elapsed)
                return f"{rem // 60}:{rem % 60:02d}"
            return ttxt

        def _normalize_goal_time(ttxt: str) -> str:
            text = str(ttxt or "").strip()
            if not text or not olympics_elapsed_clock:
                return text
            # ESPN Olympic scorer clocks are elapsed within period; convert only mm:ss part.
            m = re.search(r"(\d{1,2}:\d{2})\s*$", text)
            if not m:
                return text
            mmss = m.group(1)
            rem = _elapsed_to_remaining(mmss)
            if rem == mmss:
                return text
            return text[: m.start(1)] + rem + text[m.end(1) :]

        def _team_code_from(v: Any) -> str:
            if isinstance(v, str):
                return v.strip().upper()
            if isinstance(v, dict):
                for key in ("abbrev", "abbreviation", "teamAbbrev", "code"):
                    vv = v.get(key)
                    if isinstance(vv, str) and vv.strip():
                        return vv.strip().upper()
                side = str(v.get("side") or v.get("teamType") or "").strip().lower()
                if side == "away":
                    return away_up
                if side == "home":
                    return home_up
            return ""

        def _append_line(team_code: str, name: str, ttxt: str) -> None:
            if not name:
                return
            line = f"{name} ({ttxt})" if ttxt else name
            if team_code == away_up:
                left.append(line)
            elif team_code == home_up:
                right.append(line)

        def _timed_lines_from_cached_summary(event_id: int) -> tuple[list[str], list[str]]:
            if event_id <= 0 or espn is None:
                return [], []
            cands = [
                "olympics-womens-ice-hockey",
                "olympics-mens-ice-hockey",
                "olympic-womens-hockey",
                "olympic-mens-hockey",
                "olympics",
                "summary",
            ]
            payload: dict[str, Any] = {}

            def _extract_lines(raw_payload: dict[str, Any]) -> tuple[list[str], list[str]]:
                tmap: dict[str, str] = {}
                comp = (((raw_payload.get("header") or {}).get("competitions") or [{}])[0] or {})
                for c in (comp.get("competitors") or []):
                    if not isinstance(c, dict):
                        continue
                    team = c.get("team") or {}
                    code = _norm_abbrev(
                        team.get("abbreviation")
                        or team.get("shortDisplayName")
                        or team.get("displayName")
                        or team.get("name")
                    , fallback="").upper()
                    tid = str(team.get("id") or c.get("id") or "").strip()
                    if code and tid:
                        tmap[tid] = code

                plays = raw_payload.get("scoringPlays")
                if not isinstance(plays, list):
                    plays = raw_payload.get("plays")
                if not isinstance(plays, list):
                    return [], []

                lsum: list[str] = []
                rsum: list[str] = []
                for p in plays:
                    if not isinstance(p, dict) or not bool(p.get("scoringPlay")):
                        continue
                    team = p.get("team") or {}
                    code = _norm_abbrev(
                        team.get("abbreviation")
                        or team.get("shortDisplayName")
                        or team.get("displayName")
                        or team.get("name")
                    , fallback="").upper()
                    if not code:
                        tid = str(team.get("id") or "").strip()
                        if tid:
                            code = tmap.get(tid, "")
                    if code not in {away_up, home_up}:
                        continue
                    scorer = ""
                    for part in (p.get("participants") or []):
                        if not isinstance(part, dict):
                            continue
                        if str(part.get("type") or "").strip().lower() != "scorer":
                            continue
                        ath = part.get("athlete") or {}
                        scorer = str(ath.get("displayName") or ath.get("fullName") or "").strip()
                        if scorer:
                            break
                    if not scorer:
                        ath = p.get("athlete")
                        if isinstance(ath, dict):
                            scorer = str(ath.get("displayName") or ath.get("fullName") or "").strip()
                    if not scorer:
                        continue
                    clk_txt = ""
                    clk = p.get("clock")
                    if isinstance(clk, dict):
                        for k in ("displayValue", "shortDisplayValue", "value", "time"):
                            vv = clk.get(k)
                            if isinstance(vv, str) and vv.strip():
                                clk_txt = vv.strip()
                                break
                    ptxt = ""
                    period = p.get("period")
                    if isinstance(period, dict):
                        pnum = _to_int(period.get("number"), default=-1)
                        if pnum > 0:
                            ptxt = _period_suffix(pnum)
                        ptype = str(period.get("type") or period.get("abbreviation") or "").upper().strip()
                        if ptype in {"OT", "SO"}:
                            ptxt = ptype
                    time_txt = _normalize_goal_time(f"{ptxt} - {clk_txt}" if ptxt and clk_txt else (clk_txt or ptxt))
                    line = f"{scorer} ({time_txt})" if time_txt else scorer
                    if code == away_up:
                        lsum.append(line)
                    else:
                        rsum.append(line)

                seen_l: set[str] = set()
                dedup_l: list[str] = []
                for x in lsum:
                    if x in seen_l:
                        continue
                    seen_l.add(x)
                    dedup_l.append(x)
                seen_r: set[str] = set()
                dedup_r: list[str] = []
                for x in rsum:
                    if x in seen_r:
                        continue
                    seen_r.add(x)
                    dedup_r.append(x)
                return _sort_chronological(dedup_l), _sort_chronological(dedup_r)

            for lc in cands:
                slug = re.sub(r"[^a-z0-9-]+", "-", str(lc or "").lower()).strip("-") or "league"
                key = f"espn/hockey/{slug}/summary/{int(event_id)}"
                try:
                    raw = espn.cache.get_json(key, ttl_s=None)  # type: ignore[attr-defined]
                except Exception:
                    raw = None
                if isinstance(raw, dict) and raw:
                    l_cached, r_cached = _extract_lines(raw)
                    if l_cached or r_cached:
                        return l_cached, r_cached
                    if not payload:
                        payload = raw

            if not allow_network:
                if isinstance(payload, dict) and payload:
                    return _extract_lines(payload)
                return [], []

            # Final fallback: live summary request when cached summary is stale/incomplete.
            base_url = str(getattr(espn, "base_url", "https://site.api.espn.com/apis/site/v2")).rstrip("/")
            headers = cast(dict[str, str], getattr(espn, "headers", {}))
            timeout_s = min(int(getattr(espn, "timeout_s", 20)), 6)
            for lc in cands:
                try:
                    if lc == "summary":
                        url = f"{base_url}/sports/hockey/summary?event={int(event_id)}"
                    else:
                        url = f"{base_url}/sports/hockey/{lc}/summary?event={int(event_id)}"
                    resp = requests.get(url, headers=headers, timeout=timeout_s)
                    resp.raise_for_status()
                    raw = resp.json()
                    if isinstance(raw, dict) and raw:
                        slug = re.sub(r"[^a-z0-9-]+", "-", str(lc or "").lower()).strip("-") or "league"
                        try:
                            espn.cache.set_json(f"espn/hockey/{slug}/summary/{int(event_id)}", raw)  # type: ignore[attr-defined]
                        except Exception:
                            pass
                        l_live, r_live = _extract_lines(raw)
                        if l_live or r_live:
                            return l_live, r_live
                except Exception:
                    continue
            if isinstance(payload, dict) and payload:
                return _extract_lines(payload)
            return [], []

        game_id_now = _to_int(g.get("id") or g.get("gameId") or 0, default=0)
        pre_l, pre_r = _timed_lines_from_cached_summary(game_id_now)
        if pre_l or pre_r:
            return pre_l, pre_r

        for side_code, team_obj in ((away_up, g.get("awayTeam") or {}), (home_up, g.get("homeTeam") or {})):
            if not isinstance(team_obj, dict):
                continue
            for key in ("goalScorers", "scorers", "goals"):
                vals = team_obj.get(key)
                if not isinstance(vals, list):
                    continue
                for item in vals:
                    if not isinstance(item, dict):
                        continue
                    name = _to_name(item.get("name") or item.get("player") or item.get("scorer") or item)
                    ttxt = _normalize_goal_time(_to_time(item))
                    _append_line(side_code, name, ttxt)

        raw_lists: list[Any] = [
            g.get("goals"),
            g.get("scoringPlays"),
            g.get("scoring"),
            g.get("plays"),
            (g.get("summary") or {}).get("scoring") if isinstance(g.get("summary"), dict) else None,
        ]
        for raw in raw_lists:
            if not isinstance(raw, list):
                continue
            for item in raw:
                if not isinstance(item, dict):
                    continue
                tcode = _team_code_from(
                    item.get("team")
                    or item.get("teamCode")
                    or item.get("teamAbbrev")
                    or item.get("teamType")
                )
                name = _to_name(item.get("player") or item.get("scorer") or item.get("name") or item)
                ttxt = _normalize_goal_time(_to_time(item))
                _append_line(tcode, name, ttxt)

        def _dedupe_keep_order(values: list[str]) -> list[str]:
            out: list[str] = []
            seen: set[str] = set()
            for val in values:
                if val in seen:
                    continue
                seen.add(val)
                out.append(val)
            return out

        left_out = _dedupe_keep_order(left)
        right_out = _dedupe_keep_order(right)

        def _timed_lines_from_summary_payload(payload: dict[str, Any]) -> tuple[list[str], list[str]]:
            lsum: list[str] = []
            rsum: list[str] = []
            team_id_to_code: dict[str, str] = {}
            side_map_local: dict[str, str] = {}

            def _append_summary(team_code: str, name: str, time_txt: str) -> None:
                if not name:
                    return
                line = f"{name} ({time_txt})" if time_txt else name
                if team_code == away_up:
                    lsum.append(line)
                elif team_code == home_up:
                    rsum.append(line)

            comp = (((payload.get("header") or {}).get("competitions") or [{}])[0] or {})
            for c in (comp.get("competitors") or []):
                if not isinstance(c, dict):
                    continue
                team = c.get("team") or {}
                code = _norm_abbrev(
                    team.get("abbreviation")
                    or team.get("shortDisplayName")
                    or team.get("displayName")
                    or team.get("name")
                , fallback="").upper()
                tid = str(team.get("id") or c.get("id") or "").strip()
                if code and tid:
                    team_id_to_code[tid] = code
                side = str(c.get("homeAway") or "").strip().lower()
                if code and side in {"away", "home"}:
                    side_map_local[side] = code

            boxscore = payload.get("boxscore")
            if isinstance(boxscore, dict):
                for bt in (boxscore.get("teams") or []):
                    if not isinstance(bt, dict):
                        continue
                    team = bt.get("team") or {}
                    code = _norm_abbrev(
                        team.get("abbreviation")
                        or team.get("shortDisplayName")
                        or team.get("displayName")
                        or team.get("name")
                    , fallback="").upper()
                    tid = str(team.get("id") or bt.get("id") or "").strip()
                    if code and tid:
                        team_id_to_code[tid] = code
                    side = str(bt.get("homeAway") or "").strip().lower()
                    if code and side in {"away", "home"}:
                        side_map_local[side] = code

            plays = payload.get("scoringPlays")
            if not isinstance(plays, list):
                plays = payload.get("plays")
            if not isinstance(plays, list):
                return [], []

            for play in plays:
                if not isinstance(play, dict) or not bool(play.get("scoringPlay")):
                    continue
                team = play.get("team") or {}
                code = _norm_abbrev(
                    team.get("abbreviation")
                    or team.get("shortDisplayName")
                    or team.get("displayName")
                    or team.get("name")
                , fallback="").upper()
                if not code:
                    team_id = str(team.get("id") or "").strip()
                    if team_id:
                        code = team_id_to_code.get(team_id, "")
                if not code:
                    side = str(play.get("homeAway") or "").strip().lower()
                    if side in {"away", "home"}:
                        code = side_map_local.get(side, "")
                if not code:
                    continue

                scorer = ""
                parts = play.get("participants")
                if isinstance(parts, list):
                    for p in parts:
                        if not isinstance(p, dict):
                            continue
                        if str(p.get("type") or "").strip().lower() != "scorer":
                            continue
                        ath = p.get("athlete") or {}
                        scorer = str(ath.get("displayName") or ath.get("fullName") or p.get("displayName") or "").strip()
                        if scorer:
                            break
                if not scorer:
                    ath = play.get("athlete")
                    if isinstance(ath, dict):
                        scorer = str(ath.get("displayName") or ath.get("fullName") or "").strip()
                if not scorer:
                    continue

                clock_txt = ""
                clk = play.get("clock")
                if isinstance(clk, dict):
                    for k in ("displayValue", "shortDisplayValue", "value", "time"):
                        vv = clk.get(k)
                        if isinstance(vv, str) and vv.strip():
                            clock_txt = vv.strip()
                            break
                ptxt = ""
                period = play.get("period")
                if isinstance(period, dict):
                    ptype = str(period.get("type") or period.get("abbreviation") or "").strip().upper()
                    if ptype in {"OT", "SO"}:
                        ptxt = ptype
                    else:
                        pnum = _to_int(period.get("number"), default=-1)
                        if pnum > 0:
                            ptxt = _period_suffix(pnum)
                goal_time = f"{ptxt} - {clock_txt}" if ptxt and clock_txt else (clock_txt or ptxt)
                goal_time = _normalize_goal_time(goal_time)
                _append_summary(code, scorer, goal_time)

            return _sort_chronological(_dedupe_keep_order(lsum)), _sort_chronological(_dedupe_keep_order(rsum))

        if (not _has_timed_line(left_out) and not _has_timed_line(right_out)):
            game_id = _to_int(g.get("id") or g.get("gameId") or 0, default=0)
            if game_id > 0 and espn is not None:
                cands = [
                    "olympics-womens-ice-hockey",
                    "olympic-womens-hockey",
                    "olympics-womens-hockey",
                    "womens-olympics-hockey",
                    "olympics",
                ]
                seen_keys: set[str] = set()
                payloads: list[dict[str, Any]] = []
                for lc in cands:
                    skey = f"espn/hockey/{re.sub(r'[^a-z0-9-]+', '-', str(lc).lower()).strip('-') or 'league'}/summary/{int(game_id)}"
                    if skey in seen_keys:
                        continue
                    seen_keys.add(skey)
                    try:
                        cached = espn.cache.get_json(skey, ttl_s=None)  # type: ignore[attr-defined]
                        if isinstance(cached, dict) and cached:
                            payloads.append(cached)
                    except Exception:
                        pass
                for payload in payloads:
                    lsum, rsum = _timed_lines_from_summary_payload(payload)
                    if _has_timed_line(lsum) or _has_timed_line(rsum):
                        return lsum, rsum

        # Live cards may need gamecenter PBP to show current scorers.
        if not left_out and not right_out:
            game_id = _to_int(g.get("id") or g.get("gameId") or 0, default=0)
            if game_id > 0:
                try:
                    goals = nhl.get_goal_events(game_id)
                except Exception:
                    goals = []
                for ev in goals:
                    period = str(ev.period or "").strip()
                    if period.isdigit():
                        period_txt = _period_suffix(int(period))
                    else:
                        period_txt = period.upper()
                    ttxt = str(ev.time_in_period or "").strip()
                    if olympics_elapsed_clock:
                        ttxt = _elapsed_to_remaining(ttxt)
                    goal_time = f"{period_txt} - {ttxt}" if period_txt and ttxt else (ttxt or period_txt)
                    _append_line(str(ev.team_abbrev or "").upper(), str(ev.scorer or "").strip(), goal_time)
                left_out = _dedupe_keep_order(left)
                right_out = _dedupe_keep_order(right)

        return _sort_chronological(left_out), _sort_chronological(right_out)

    def _layout_card(
        card: _Card,
        game: dict[str, Any],
        selected_date: dt.date,
        *,
        show_rollover: bool = False,
    ) -> None:
        w = int(card.frame.winfo_width() or 1)
        h = int(card.frame.winfo_height() or 1)
        if w < 10 or h < 10:
            return
        base_h = int(card.base_height or h)
        if base_h < 10:
            base_h = h
        if (not show_rollover) and h != base_h:
            try:
                card.frame.place_configure(height=base_h)
            except Exception:
                pass
            h = base_h
        layout_h = max(1, int(base_h if base_h > 0 else h))

        away_score, home_score, away_code, home_code = _scores(game)
        away_shots, home_shots = _shots(game)
        state = _game_state(game)
        league_name = str(game.get("league") or "NHL")
        start_local = _parse_start_local(game, tz)
        now_local = dt.datetime.now(tz)
        if (
            state not in {"FINAL", "OFF"}
            and not state.startswith("FINAL")
            and start_local is not None
            and start_local > now_local + dt.timedelta(minutes=1)
        ):
            state = "FUT"
        is_final_state = state in {"FINAL", "OFF"} or state.startswith("FINAL")

        # Shared logo width target with small per-team visual balancing.
        logo_w_target = int(min(max(100, w * 0.25), 176))
        away_w = int(round(logo_w_target * LOGO_VISUAL_SCALE.get(away_code.upper(), 1.0)))
        home_w = int(round(logo_w_target * LOGO_VISUAL_SCALE.get(home_code.upper(), 1.0)))
        away_h = _logo_height_for_width(
            logos,
            away_code,
            away_w,
            min_h=26,
            max_h=int(layout_h * 0.42),
            league=league_name,
            master=card.frame,
        )
        home_h = _logo_height_for_width(
            logos,
            home_code,
            home_w,
            min_h=26,
            max_h=int(layout_h * 0.42),
            league=league_name,
            master=card.frame,
        )

        xL = int(w * 0.30)
        xR = int(w * 0.70)
        away_y = 0
        home_y = 0

        bleed = int(max(16, max(away_h, home_h) * 0.34))
        panel_h = max(1, layout_h - bleed)
        card.panel.place(x=0, y=bleed, width=w, height=panel_h)
        card.overlay.place(x=0, y=0, width=w, height=h)
        card.overlay.delete("all")
        card.overlay.create_rectangle(0, 0, w, bleed, fill=BG, outline="")
        card.overlay.create_rectangle(0, bleed, w, h, fill=CARD_BG, outline="")

        away_img = _logo_get(logos, away_code, height=away_h, master=card.frame, league=league_name)
        home_img = _logo_get(logos, home_code, height=home_h, master=card.frame, league=league_name)
        card.img_refs.clear()

        if away_img:
            card.img_refs.append(away_img)
        if home_img:
            card.img_refs.append(home_img)

        if state in {"FUT", "PRE"}:
            away_txt = ""
            home_txt = ""
            dash_txt = ""
            center_top_txt = _future_big_text(game, tz)
            status = ""
        elif is_final_state:
            away_txt = str(away_score)
            home_txt = str(home_score)
            dash_txt = "-"
            center_top_txt = None
            status = _final_status(game)
        else:
            away_txt = str(away_score)
            home_txt = str(home_score)
            dash_txt = "-"
            center_top_txt = None
            status = _live_status(game)

        show_win_probs = (
            str(game.get("league") or "").upper() == "NHL"
            and not is_final_state
        )
        away_future_pct, home_future_pct = (
            _future_win_prediction_labels(game, selected_date)
            if show_win_probs
            else (None, None)
        )
        away_standings_ribbon: Optional[str] = None
        home_standings_ribbon: Optional[str] = None
        if str(game.get("league") or "").upper() == "NHL":
            away_standings_ribbon = _team_standings_ribbon(
                away_code,
                selected_date,
                allow_network=False,
            )
            home_standings_ribbon = _team_standings_ribbon(
                home_code,
                selected_date,
                allow_network=False,
            )
        special_state_line = ""
        away_special_state = ""
        home_special_state = ""
        if str(game.get("league") or "").upper() == "NHL" and state in {"LIVE", "CRIT"}:
            gid = _to_int(game.get("id") or game.get("gameId") or 0, default=0)
            live_clock_running = bool(selected_date == today and _is_live_clock_running(game))
            pbp_live = _load_pbp(
                gid,
                allow_network=live_clock_running,
                force_network=False,
            )
            if isinstance(pbp_live, dict):
                live_pack = _pbp_event_pack(
                    game,
                    pbp_live,
                    away_code=away_code,
                    home_code=home_code,
                )
                special = live_pack.get("special_teams") if isinstance(live_pack.get("special_teams"), dict) else {}
                special_state_line = str((special or {}).get("state_line") or "").strip()
                away_special_state = str((special or {}).get("away_state") or "").strip()
                home_special_state = str((special or {}).get("home_state") or "").strip()
        middle_txt = _game_middle_label(game, selected_date)

        score_size = max(28, min(78, int(panel_h * 0.40)))
        future_score_size = max(22, min(60, int(panel_h * 0.30)))
        dash_size = max(34, min(94, int(panel_h * 0.52)))
        mid_size = max(12, min(24, int(panel_h * 0.12)))
        status_size = max(12, min(26, int(panel_h * 0.14)))
        side_metric_size = max(9, min(16, int(score_size * 0.34)))
        side_metric_font = tkfont.Font(root=card.frame, family="Helvetica", size=side_metric_size, weight="normal")
        side_metric_offset = max(16, int(w * 0.11))
        card.score_font.configure(size=(future_score_size if center_top_txt is not None else score_size))
        card.dash_font.configure(size=dash_size)
        card.mid_font.configure(size=mid_size)
        card.status_font.configure(size=status_size)

        # Keep category text in a consistent band; push status to the bottom.
        y_middle = bleed + panel_h * 0.36
        if center_top_txt is not None:
            # Future start times should sit lower in the card.
            y_scores = bleed + panel_h * 0.70
        else:
            y_scores = bleed + panel_h * 0.58
        y_status = bleed + panel_h * 0.88
        if special_state_line or away_special_state or home_special_state:
            y_status = bleed + panel_h * 0.90
        if middle_txt:
            card.overlay.create_text(
                w // 2,
                y_middle,
                text=middle_txt,
                fill=MUTED,
                font=card.mid_font,
                anchor="center",
            )
        if center_top_txt is not None:
            card.overlay.create_text(
                w // 2,
                y_scores,
                text=center_top_txt,
                fill=FG,
                font=card.score_font,
                anchor="center",
            )
        else:
            card.overlay.create_text(xL, y_scores, text=away_txt, fill=FG, font=card.score_font, anchor="center")
            card.overlay.create_text(w // 2, y_scores, text=dash_txt, fill=FG, font=card.dash_font, anchor="center")
            card.overlay.create_text(xR, y_scores, text=home_txt, fill=FG, font=card.score_font, anchor="center")
            if away_shots is not None:
                card.overlay.create_text(
                    xL - side_metric_offset,
                    y_scores,
                    text=str(away_shots),
                    fill=MUTED,
                    font=side_metric_font,
                    anchor="e",
                )
            if home_shots is not None:
                card.overlay.create_text(
                    xR + side_metric_offset,
                    y_scores,
                    text=str(home_shots),
                    fill=MUTED,
                    font=side_metric_font,
                    anchor="w",
                )

        away_special_draw = str(away_special_state or "").strip()
        home_special_draw = str(home_special_state or "").strip()
        if away_special_draw.upper().startswith("PK"):
            away_special_draw = ""
        if home_special_draw.upper().startswith("PK"):
            home_special_draw = ""

        if away_special_draw or home_special_draw:
            y_special = bleed + panel_h * 0.79
            if away_special_draw:
                card.overlay.create_text(
                    xL,
                    y_special,
                    text=away_special_draw,
                    fill=MUTED,
                    font=card.mid_font,
                    anchor="center",
                )
            if home_special_draw:
                card.overlay.create_text(
                    xR,
                    y_special,
                    text=home_special_draw,
                    fill=MUTED,
                    font=card.mid_font,
                    anchor="center",
                )
        elif special_state_line:
            # Fallback path if side-specific labels are unavailable.
            special_txt = str(special_state_line or "").strip()
            for code in (away_code, home_code):
                prefix = f"{str(code).upper()} "
                if special_txt.upper().startswith(prefix):
                    special_txt = special_txt[len(prefix):].strip()
                    break
            if special_txt:
                card.overlay.create_text(
                    w // 2,
                    bleed + panel_h * 0.79,
                    text=special_txt,
                    fill=MUTED,
                    font=card.mid_font,
                    anchor="center",
                )
        card.overlay.create_text(w // 2, y_status, text=status, fill=MUTED, font=card.status_font, anchor="center")

        # "@"
        at_size = max(18, min(42, int(max(away_h, home_h) * 0.50)))
        card.at_font.configure(size=at_size)
        at_y_factor = 0.18
        card.overlay.create_text(
            w // 2,
            int(max(away_h, home_h) * at_y_factor),
            text="@",
            fill=MUTED,
            font=card.at_font,
            anchor="n",
        )

        # Fallback: show code only when logo/flag is missing.
        code_size = max(10, min(18, int(max(away_h, home_h) * 0.20)))
        code_y = int(max(away_h, home_h) * 0.18)
        if away_img is None:
            card.overlay.create_text(xL, code_y, text=str(away_code).upper(), fill=FG, font=("Helvetica", code_size), anchor="n")
        if home_img is None:
            card.overlay.create_text(xR, code_y, text=str(home_code).upper(), fill=FG, font=("Helvetica", code_size), anchor="n")

        # Keep logos above all text when overlap happens.
        if away_img:
            card.overlay.create_image(xL, away_y, image=away_img, anchor="n")
        if home_img:
            card.overlay.create_image(xR, home_y, image=home_img, anchor="n")

        # Keep percentages/ribbons inside top card corners.
        corner_pad_x = max(10, int(w * 0.024))
        top_corner_y = int(max(12, min(layout_h - 20, max(away_h, home_h) * 0.46)))
        y_division = top_corner_y
        y_probs = int(max(18, min(layout_h - 10, max(away_h, home_h) * 0.66)))
        division_linespace = 0
        if away_standings_ribbon or home_standings_ribbon:
            ribbon_size = max(11, min(19, int(max(away_h, home_h) * 0.17)))
            ribbon_font = tkfont.Font(root=card.frame, family="Helvetica", size=ribbon_size, weight="bold")
            division_linespace = int(ribbon_font.metrics("linespace") or ribbon_size)
            if away_standings_ribbon:
                card.overlay.create_text(
                    corner_pad_x,
                    y_division,
                    text=away_standings_ribbon,
                    fill=MUTED,
                    font=ribbon_font,
                    anchor="w",
                )
            if home_standings_ribbon:
                card.overlay.create_text(
                    w - corner_pad_x,
                    y_division,
                    text=home_standings_ribbon,
                    fill=MUTED,
                    font=ribbon_font,
                    anchor="e",
                )
        if away_future_pct or home_future_pct:
            prob_size = max(14, min(24, int(max(away_h, home_h) * 0.23)))
            prob_font = tkfont.Font(root=card.frame, family="Helvetica", size=prob_size, weight="normal")
            if division_linespace > 0:
                corner_line_gap = max(4, int(max(away_h, home_h) * 0.025))
                y_probs = int(min(layout_h - 10, y_division + division_linespace + corner_line_gap))
            else:
                y_probs = int(max(18, min(layout_h - 10, top_corner_y)))
            if away_future_pct:
                card.overlay.create_text(
                    corner_pad_x,
                    y_probs,
                    text=away_future_pct,
                    fill=MUTED,
                    font=prob_font,
                    anchor="w",
                )
            if home_future_pct:
                card.overlay.create_text(
                    w - corner_pad_x,
                    y_probs,
                    text=home_future_pct,
                    fill=MUTED,
                    font=prob_font,
                    anchor="e",
                )

        if show_rollover and state not in {"FUT", "PRE"}:
            roll_left, roll_right = _goal_scorer_lines(
                game,
                away_code,
                home_code,
                allow_network=False,
            )
            roll_left = [str(x).strip() for x in roll_left if str(x).strip()]
            roll_right = [str(x).strip() for x in roll_right if str(x).strip()]
            if roll_left or roll_right:
                top = int(min(layout_h - 30, y_scores + (score_size * 0.42)))
                if top < (bleed + panel_h * 0.50):
                    top = int(bleed + panel_h * 0.50)
                side_font = tkfont.Font(root=card.frame, family="Helvetica", size=max(8, min(11, int(mid_size * 0.78))), weight="normal")
                left_txt = "\n".join(roll_left) if roll_left else ""
                right_txt = "\n".join(roll_right) if roll_right else ""
                left_lines_n = 1 + left_txt.count("\n")
                right_lines_n = 1 + right_txt.count("\n")
                max_lines_n = max(1, left_lines_n, right_lines_n)
                line_h = int(side_font.metrics("linespace") or 12)
                box_h = max(36, int((line_h * max_lines_n) + 16))
                need_h = int(top + box_h + 8)
                if need_h > h:
                    try:
                        card.frame.place_configure(height=need_h)
                        h = need_h
                        card.overlay.place_configure(height=h)
                    except Exception:
                        pass
                bottom = min(h - 8, top + box_h)
                card.overlay.create_rectangle(8, top, w - 8, bottom, fill="#3f3f3f", outline="")
                card.overlay.create_text(xL, top + 8, text=left_txt, fill=FG, font=side_font, anchor="n", justify="center")
                card.overlay.create_text(xR, top + 8, text=right_txt, fill=FG, font=side_font, anchor="n", justify="center")

    def _position_cards_grouped(grouped: list[tuple[str, list[dict[str, Any]]]], selected_date: dt.date) -> list[dict[str, Any]]:
        _clear_section_labels()
        ordered_games: list[dict[str, Any]] = []
        for _league, items in grouped:
            ordered_games.extend(items)
        n = len(ordered_games)
        if n <= 0:
            return []

        w = int(grid_host.winfo_width() or 1)
        h = int(grid_host.winfo_height() or 1)
        per_league_max = max((len(items) for _league, items in grouped), default=n)
        cols = _choose_cols(per_league_max, w, h)
        multi = len(grouped) >= 1
        if multi:
            # Mixed-league days (e.g., NHL + PWHL) read better at 4-up max.
            cols = min(cols, 4)
        header_h = 30 if multi else 0

        # each league starts at a new row
        rows = 0
        for _lg, items in grouped:
            rows += int(math.ceil(len(items) / max(1, cols)))

        avail_w = max(1.0, w - CARD_GAP_X * (cols + 1))
        card_w = avail_w / max(1, cols)
        card_h = card_w / CARD_RATIO
        total_h = rows * card_h + CARD_GAP_Y * (rows + 1) + header_h * (len(grouped) if multi else 0)
        if total_h > h:
            avail_h = max(1.0, h - CARD_GAP_Y * (rows + 1) - header_h * (len(grouped) if multi else 0))
            card_h = avail_h / max(1, rows)
            card_w = card_h * CARD_RATIO

        used_w = cols * card_w + CARD_GAP_X * (cols + 1)
        used_h = rows * card_h + CARD_GAP_Y * (rows + 1) + header_h * (len(grouped) if multi else 0)
        start_x = int(max(0.0, (w - used_w) / 2.0))
        start_y = int(max(0.0, (h - used_h) / 2.0))

        y = start_y + CARD_GAP_Y
        card_i = 0
        for league, items in grouped:
            if multi:
                lbl = tk.Label(
                    grid_host,
                    text=_section_label_text(str(league), items, selected_date, boundaries),
                    bg=BG,
                    fg=MUTED,
                    font=tkfont.Font(size=14, weight="bold"),
                )
                lbl.place(x=start_x + CARD_GAP_X, y=y - 24, anchor="nw")
                section_labels.append(lbl)

            col = 0
            for _g in items:
                if card_i >= len(cards):
                    break
                x = start_x + CARD_GAP_X + col * (card_w + CARD_GAP_X)
                cards[card_i].base_width = int(card_w)
                cards[card_i].base_height = int(card_h)
                cards[card_i].frame.place(x=x, y=int(y), width=int(card_w), height=int(card_h))
                card_i += 1
                col += 1
                if col >= cols:
                    col = 0
                    y += card_h + CARD_GAP_Y

            if col != 0:
                y += card_h + CARD_GAP_Y

            if multi:
                y += header_h

        return ordered_games

    def _update_cards(games: list[dict[str, Any]], selected_date: dt.date, attempts: int = 0) -> None:
        # Wait for card geometry before painting card contents.
        if attempts < 10:
            not_ready = any(
                int(c.frame.winfo_width() or 0) < 10 or int(c.frame.winfo_height() or 0) < 10
                for c in cards
            )
            if not_ready:
                bgroot.after(40, lambda: _update_cards(games, selected_date, attempts + 1))
                return

        def _pointer_inside(widget: tk.Misc) -> bool:
            try:
                if not bool(widget.winfo_exists()):
                    return False
                px = int(widget.winfo_pointerx())
                py = int(widget.winfo_pointery())
                x0 = int(widget.winfo_rootx())
                y0 = int(widget.winfo_rooty())
                x1 = x0 + int(widget.winfo_width())
                y1 = y0 + int(widget.winfo_height())
                return x0 <= px <= x1 and y0 <= py <= y1
            except Exception:
                return False

        def _hide_popup(card: _Card) -> None:
            if card.scorer_popup is not None:
                try:
                    card.scorer_popup.destroy()
                except Exception:
                    pass
                card.scorer_popup = None

        def _show_popup(card: _Card, game: dict[str, Any]) -> None:
            _hide_popup(card)
            away_score, home_score, away_code, home_code = _scores(game)
            league_name = str(game.get("league") or "NHL")
            gid = _to_int(game.get("id") or game.get("gameId") or 0, default=0)
            left_lines, right_lines = _goal_scorer_lines(game, away_code, home_code)
            left_lines = [str(x).strip() for x in left_lines if str(x).strip()]
            right_lines = [str(x).strip() for x in right_lines if str(x).strip()]
            mp_penalties_rows: list[dict[str, Any]] = []
            mp_csv = _get_moneypuck_game_data_csv(
                game,
                selected_date,
                allow_network=True,
            )
            if mp_csv:
                mp_left, mp_right, mp_penalties_rows = _parse_moneypuck_popup_fallback(
                    mp_csv,
                    away_code=away_code,
                    home_code=home_code,
                )
                if not left_lines and mp_left:
                    left_lines = mp_left
                if not right_lines and mp_right:
                    right_lines = mp_right

            allow_gamecenter_network = bool(selected_date == today)
            force_live_network = bool(_is_live_clock_running(game))
            state_now = _game_state(game)
            is_final_now = state_now in {"FINAL", "OFF"} or state_now.startswith("FINAL")
            boxscore = _load_boxscore(
                gid,
                allow_network=allow_gamecenter_network,
                force_network=force_live_network,
            )
            # Pregame starters are often published late. Keep refreshing boxscore
            # data until both teams have a confirmed starter for today's games.
            if allow_gamecenter_network and (not is_final_now):
                away_confirmed = _boxscore_has_confirmed_goalie(boxscore, "awayTeam")
                home_confirmed = _boxscore_has_confirmed_goalie(boxscore, "homeTeam")
                if not (away_confirmed and home_confirmed):
                    refreshed_boxscore = _load_boxscore(
                        gid,
                        allow_network=True,
                        force_network=True,
                    )
                    if isinstance(refreshed_boxscore, dict):
                        boxscore = refreshed_boxscore
            pbp = _load_pbp(
                gid,
                allow_network=allow_gamecenter_network,
                force_network=force_live_network,
            )
            espn_summary = _espn_summary_for_game(game, away_code, home_code)

            away_shots, home_shots = _shots(game)
            pbp_pack = (
                _pbp_event_pack(game, pbp, away_code=away_code, home_code=home_code)
                if isinstance(pbp, dict)
                else {"shot_by_period": {}, "stats": {}, "seen_types": set(), "penalties": [], "has_plays": False}
            )
            shot_by_period = pbp_pack.get("shot_by_period") if isinstance(pbp_pack.get("shot_by_period"), dict) else {}
            pbp_stats = pbp_pack.get("stats") if isinstance(pbp_pack.get("stats"), dict) else {}
            seen_types = pbp_pack.get("seen_types") if isinstance(pbp_pack.get("seen_types"), set) else set()
            penalties_rows = pbp_pack.get("penalties") if isinstance(pbp_pack.get("penalties"), list) else []
            special_pack = pbp_pack.get("special_teams") if isinstance(pbp_pack.get("special_teams"), dict) else {}
            has_pbp_plays = bool(pbp_pack.get("has_plays"))

            if (away_shots is None or home_shots is None) and shot_by_period:
                away_total_calc = 0
                home_total_calc = 0
                for vals in shot_by_period.values():
                    if isinstance(vals, dict):
                        away_total_calc += _to_int(vals.get(away_code) or 0, default=0)
                        home_total_calc += _to_int(vals.get(home_code) or 0, default=0)
                if away_shots is None:
                    away_shots = away_total_calc
                if home_shots is None:
                    home_shots = home_total_calc

            espn_stat_pack = (
                _espn_team_stat_values(espn_summary, away_code=away_code, home_code=home_code)
                if isinstance(espn_summary, dict)
                else {}
            )
            if (not penalties_rows) and isinstance(espn_summary, dict):
                penalties_rows = _penalties_from_espn_summary(espn_summary, away_code=away_code, home_code=home_code)
            if not penalties_rows and mp_penalties_rows:
                penalties_rows = mp_penalties_rows

            tv_rows = game.get("tvBroadcasts") if isinstance(game.get("tvBroadcasts"), list) else []
            if not tv_rows and isinstance(boxscore, dict):
                tv_rows = boxscore.get("tvBroadcasts") if isinstance(boxscore.get("tvBroadcasts"), list) else []
            networks: list[str] = []
            for row in tv_rows:
                if not isinstance(row, dict):
                    continue
                network = str(row.get("network") or "").strip()
                if network and network not in networks:
                    networks.append(network)
            if not networks and isinstance(espn_summary, dict):
                for row in espn_summary.get("broadcasts") or []:
                    if not isinstance(row, dict):
                        continue
                    names = row.get("names") if isinstance(row.get("names"), list) else []
                    for n in names:
                        nn = str(n).strip()
                        if nn and nn not in networks:
                            networks.append(nn)

            venue_name = _pick_text(game.get("venue"))
            venue_city = _pick_text(game.get("venueLocation"))
            if isinstance(boxscore, dict):
                venue_name = venue_name or _pick_text(boxscore.get("venue"))
                venue_city = venue_city or _pick_text(boxscore.get("venueLocation"))
            if isinstance(espn_summary, dict):
                info = espn_summary.get("gameInfo") if isinstance(espn_summary.get("gameInfo"), dict) else {}
                venue = info.get("venue") if isinstance(info.get("venue"), dict) else {}
                venue_name = venue_name or str(venue.get("fullName") or "").strip()
                address = venue.get("address") if isinstance(venue.get("address"), dict) else {}
                if not venue_city:
                    city = str(address.get("city") or "").strip()
                    state_txt = str(address.get("state") or address.get("stateAbbreviation") or "").strip()
                    venue_city = ", ".join([x for x in (city, state_txt) if x]).strip(", ")

            def _extract_names(rows: Any) -> list[str]:
                out: list[str] = []
                seen: set[str] = set()
                if not isinstance(rows, list):
                    return out
                for row in rows:
                    name = ""
                    if isinstance(row, dict):
                        sources = [
                            row,
                            row.get("athlete") if isinstance(row.get("athlete"), dict) else {},
                            row.get("person") if isinstance(row.get("person"), dict) else {},
                            row.get("coach") if isinstance(row.get("coach"), dict) else {},
                            row.get("player") if isinstance(row.get("player"), dict) else {},
                        ]
                        for src in sources:
                            if not isinstance(src, dict):
                                continue
                            for key in ("fullName", "displayName", "shortName", "name"):
                                cand = _pick_text(src.get(key))
                                if cand:
                                    name = cand
                                    break
                            if name:
                                break
                    else:
                        name = str(row).strip()
                    if name and name not in seen:
                        seen.add(name)
                        out.append(name)
                return out

            def _coach_from_blob(blob: Any) -> str:
                if not isinstance(blob, dict):
                    return ""
                for key in ("headCoach", "coach", "head_coach"):
                    val = blob.get(key)
                    if isinstance(val, dict):
                        names = _extract_names([val])
                        if names:
                            return names[0]
                    txt = _pick_text(val)
                    if txt:
                        return txt
                coaches = blob.get("coaches")
                names = _extract_names(coaches if isinstance(coaches, list) else [])
                if names:
                    return ", ".join(names)
                return ""

            def _scratches_from_blob(blob: Any) -> str:
                if not isinstance(blob, dict):
                    return ""
                for key in ("scratches", "scratchedPlayers", "scratchedSkaters", "projectedScratches"):
                    rows = blob.get(key)
                    names = _extract_names(rows if isinstance(rows, list) else [])
                    if names:
                        return ", ".join(names)
                injuries = blob.get("injuries") if isinstance(blob.get("injuries"), list) else []
                picked: list[str] = []
                seen: set[str] = set()
                for row in injuries:
                    if not isinstance(row, dict):
                        continue
                    status_txt = " ".join(
                        [
                            str(row.get("status") or "").strip().upper(),
                            str(row.get("type") or "").strip().upper(),
                            str(row.get("designation") or "").strip().upper(),
                        ]
                    )
                    if not any(x in status_txt for x in ("SCRATCH", "OUT", "DNP", "INACTIVE")):
                        continue
                    for nm in _extract_names([row]):
                        if nm and nm not in seen:
                            seen.add(nm)
                            picked.append(nm)
                return ", ".join(picked) if picked else ""

            officials_txt = "[NF]"
            off_parts: list[str] = []
            if isinstance(espn_summary, dict):
                info = espn_summary.get("gameInfo") if isinstance(espn_summary.get("gameInfo"), dict) else {}
                offs = info.get("officials") if isinstance(info.get("officials"), list) else []
                for row in offs:
                    if not isinstance(row, dict):
                        continue
                    names = _extract_names([row])
                    name = names[0] if names else ""
                    pos = str(row.get("position") or row.get("type") or row.get("role") or "").strip()
                    if name and pos:
                        off_parts.append(f"{name} - {pos}")
                    elif name:
                        off_parts.append(name)
            if not off_parts and isinstance(boxscore, dict):
                for key in ("officials", "referees", "linespersons"):
                    rows = boxscore.get(key)
                    if not isinstance(rows, list):
                        continue
                    for row in rows:
                        if not isinstance(row, dict):
                            continue
                        names = _extract_names([row])
                        name = names[0] if names else ""
                        pos = str(row.get("position") or row.get("type") or row.get("role") or "").strip()
                        if name and pos:
                            off_parts.append(f"{name} - {pos}")
                        elif name:
                            off_parts.append(name)
                game_info = boxscore.get("gameInfo") if isinstance(boxscore.get("gameInfo"), dict) else {}
                rows = game_info.get("officials") if isinstance(game_info.get("officials"), list) else []
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    names = _extract_names([row])
                    name = names[0] if names else ""
                    pos = str(row.get("position") or row.get("type") or row.get("role") or "").strip()
                    if name and pos:
                        off_parts.append(f"{name} - {pos}")
                    elif name:
                        off_parts.append(name)
            if off_parts:
                dedup_parts: list[str] = []
                seen_off: set[str] = set()
                for part in off_parts:
                    if part not in seen_off:
                        seen_off.add(part)
                        dedup_parts.append(part)
                if dedup_parts:
                    officials_txt = ", ".join(dedup_parts)

            away_coach_txt = "[NF]"
            home_coach_txt = "[NF]"
            away_scratches_txt = "[NF]"
            home_scratches_txt = "[NF]"
            away_sources: list[dict[str, Any]] = []
            home_sources: list[dict[str, Any]] = []
            if isinstance(boxscore, dict):
                away_team_blob = boxscore.get("awayTeam") if isinstance(boxscore.get("awayTeam"), dict) else {}
                home_team_blob = boxscore.get("homeTeam") if isinstance(boxscore.get("homeTeam"), dict) else {}
                if away_team_blob:
                    away_sources.append(away_team_blob)
                if home_team_blob:
                    home_sources.append(home_team_blob)
                pstats = boxscore.get("playerByGameStats") if isinstance(boxscore.get("playerByGameStats"), dict) else {}
                away_p = pstats.get("awayTeam") if isinstance(pstats.get("awayTeam"), dict) else {}
                home_p = pstats.get("homeTeam") if isinstance(pstats.get("homeTeam"), dict) else {}
                if away_p:
                    away_sources.append(away_p)
                if home_p:
                    home_sources.append(home_p)
                game_info = boxscore.get("gameInfo") if isinstance(boxscore.get("gameInfo"), dict) else {}
                away_gi = game_info.get("awayTeam") if isinstance(game_info.get("awayTeam"), dict) else {}
                home_gi = game_info.get("homeTeam") if isinstance(game_info.get("homeTeam"), dict) else {}
                if away_gi:
                    away_sources.append(away_gi)
                if home_gi:
                    home_sources.append(home_gi)

            if isinstance(espn_summary, dict):
                comp = (((espn_summary.get("header") or {}).get("competitions") or [{}])[0] or {})
                competitors = comp.get("competitors") if isinstance(comp.get("competitors"), list) else []
                for row in competitors:
                    if not isinstance(row, dict):
                        continue
                    side = str(row.get("homeAway") or "").strip().lower()
                    team_blob = row.get("team") if isinstance(row.get("team"), dict) else {}
                    if side == "away":
                        away_sources.append(row)
                        if team_blob:
                            away_sources.append(team_blob)
                    elif side == "home":
                        home_sources.append(row)
                        if team_blob:
                            home_sources.append(team_blob)

            for src in away_sources:
                coach = _coach_from_blob(src)
                if coach:
                    away_coach_txt = coach
                    break
            for src in home_sources:
                coach = _coach_from_blob(src)
                if coach:
                    home_coach_txt = coach
                    break
            for src in away_sources:
                scratches = _scratches_from_blob(src)
                if scratches:
                    away_scratches_txt = scratches
                    break
            for src in home_sources:
                scratches = _scratches_from_blob(src)
                if scratches:
                    home_scratches_txt = scratches
                    break

            current_period = _to_int(
                game.get("period")
                or ((game.get("periodDescriptor") or {}).get("number") if isinstance(game.get("periodDescriptor"), dict) else 0)
                or 0,
                default=0,
            )
            is_final = _is_final_state_text(game.get("gameState") or game.get("state"))

            period_rows: list[tuple[str, str, str]] = []
            if has_pbp_plays and shot_by_period:
                extra_periods = [p for p in sorted(shot_by_period.keys()) if p > 3]
                period_order = [1, 2, 3] + extra_periods

                def _shot_slot_text(bucket: dict[str, Any], team: str) -> str:
                    if not isinstance(bucket, dict):
                        return "--"
                    raw_val = bucket.get(team)
                    if raw_val in (None, ""):
                        return "--"
                    val = _to_int(raw_val, default=-1)
                    return str(val) if val >= 0 else "--"

                for pnum in period_order:
                    bucket = shot_by_period.get(pnum) if isinstance(shot_by_period.get(pnum), dict) else {}
                    if (not is_final) and current_period > 0 and pnum > current_period:
                        av = "--"
                        hv = "--"
                    else:
                        av = _shot_slot_text(bucket, away_code)
                        hv = _shot_slot_text(bucket, home_code)
                    label = _period_suffix(pnum) if pnum <= 3 else f"{pnum}TH"
                    period_rows.append((label, av, hv))
            else:
                period_rows = [("1ST", "--", "--"), ("2ND", "--", "--"), ("3RD", "--", "--")]

            total_away_txt = str(int(away_shots)) if isinstance(away_shots, (int, float)) else "--"
            total_home_txt = str(int(home_shots)) if isinstance(home_shots, (int, float)) else "--"
            period_rows.append(("TOTAL", total_away_txt, total_home_txt))

            def _from_pbp_stat(key: str) -> tuple[str, str]:
                away_row = pbp_stats.get(away_code) if isinstance(pbp_stats.get(away_code), dict) else {}
                home_row = pbp_stats.get(home_code) if isinstance(pbp_stats.get(home_code), dict) else {}
                if key not in away_row or key not in home_row:
                    return ("[NF]", "[NF]")
                return (str(_to_int(away_row.get(key) or 0, default=0)), str(_to_int(home_row.get(key) or 0, default=0)))

            if "faceoff" in seen_types:
                away_face = _to_int(((pbp_stats.get(away_code) or {}).get("faceoff_wins") if isinstance(pbp_stats.get(away_code), dict) else 0) or 0, default=0)
                home_face = _to_int(((pbp_stats.get(home_code) or {}).get("faceoff_wins") if isinstance(pbp_stats.get(home_code), dict) else 0) or 0, default=0)
                face_total = away_face + home_face
                if face_total > 0:
                    away_face_txt = f"{(100.0 * away_face / face_total):.1f}%".replace(".0%", "%")
                    home_face_txt = f"{(100.0 * home_face / face_total):.1f}%".replace(".0%", "%")
                else:
                    away_face_txt, home_face_txt = ("[NF]", "[NF]")
            else:
                away_face_txt, home_face_txt = espn_stat_pack.get("faceoff_pct", ("[NF]", "[NF]"))

            if "penalty" in seen_types:
                pim_pair = _from_pbp_stat("pim")
            else:
                pim_pair = espn_stat_pack.get("penalty_minutes", ("[NF]", "[NF]"))
            if "hit" in seen_types:
                hit_pair = _from_pbp_stat("hits")
            else:
                hit_pair = espn_stat_pack.get("hits", ("[NF]", "[NF]"))
            if "blocked-shot" in seen_types:
                block_pair = _from_pbp_stat("blocked")
            else:
                block_pair = espn_stat_pack.get("blocked_shots", ("[NF]", "[NF]"))
            if "giveaway" in seen_types:
                give_pair = _from_pbp_stat("giveaways")
            else:
                give_pair = espn_stat_pack.get("giveaways", ("[NF]", "[NF]"))
            if "takeaway" in seen_types:
                take_pair = _from_pbp_stat("takeaways")
            else:
                take_pair = espn_stat_pack.get("takeaways", ("[NF]", "[NF]"))

            if isinstance(away_shots, (int, float)) and isinstance(home_shots, (int, float)):
                shots_pair = (str(int(away_shots)), str(int(home_shots)))
            else:
                shots_pair = espn_stat_pack.get("shots_on_goal", ("[NF]", "[NF]"))
            power_play_pair = espn_stat_pack.get("power_play", ("[NF]", "[NF]"))

            game_stat_rows = [
                ("Shots On Goal", shots_pair[0], shots_pair[1]),
                ("Face-off %", away_face_txt, home_face_txt),
                ("Power Play", power_play_pair[0], power_play_pair[1]),
                ("Penalty Minutes", pim_pair[0], pim_pair[1]),
                ("Hits", hit_pair[0], hit_pair[1]),
                ("Blocked Shots", block_pair[0], block_pair[1]),
                ("Giveaways", give_pair[0], give_pair[1]),
                ("Takeaways", take_pair[0], take_pair[1]),
            ]

            season_series = _season_series_for_matchup(away_code, home_code, live_game=game)
            series_headline = str(season_series.get("headline") or "[NF]").strip() or "[NF]"
            series_rows = [
                str(x).strip()
                for x in (season_series.get("rows") if isinstance(season_series.get("rows"), list) else [])
                if str(x).strip()
            ]

            def _fmt_sv_pct(raw: Any) -> str:
                try:
                    val = float(raw)
                except Exception:
                    return "[NF]"
                if val < 0:
                    return "[NF]"
                if val <= 1.0:
                    return f"{(val * 100.0):.2f}%"
                return f"{val:.2f}%"

            season_compact = str(_to_int(game.get("season") or 0, default=0) or "").strip()
            if not season_compact or season_compact == "0":
                season_compact = re.sub(r"[^0-9]", "", str(season or "").strip())

            def _goalie_name_from_row(row: dict[str, Any]) -> str:
                name = _pick_text(row.get("name"))
                if name:
                    return name
                first = _pick_text(row.get("firstName"))
                last = _pick_text(row.get("lastName"))
                full = " ".join([x for x in (first, last) if x]).strip()
                return full or "[NF]"

            def _skater_name_from_row(row: dict[str, Any]) -> str:
                first = _pick_text(row.get("firstName"))
                last = _pick_text(row.get("lastName"))
                full = " ".join([x for x in (first, last) if x]).strip()
                if full:
                    return full
                return _pick_text(row.get("name")) or "[NF]"

            def _team_split_leader_lines(team_code: str) -> list[str]:
                if not season_compact:
                    return ["[NF]"]
                rows = _club_stats_skaters(
                    team_code,
                    season_compact=season_compact,
                    allow_network=allow_gamecenter_network,
                )
                if not rows:
                    return ["[NF]"]

                skaters: list[dict[str, Any]] = []
                for row in rows:
                    goals = _to_int(row.get("goals") or 0, default=0)
                    pp_goals = _to_int(row.get("powerPlayGoals") or 0, default=0)
                    pk_goals = _to_int(row.get("shorthandedGoals") or 0, default=0)
                    ev_goals = max(0, goals - pp_goals - pk_goals)
                    skaters.append(
                        {
                            "name": _skater_name_from_row(row),
                            "goals": goals,
                            "ev_goals": ev_goals,
                            "pp_goals": pp_goals,
                            "pk_goals": pk_goals,
                            "points": _to_int(row.get("points") or 0, default=0),
                            "games": _to_int(row.get("gamesPlayed") or 0, default=0),
                        }
                    )
                if not skaters:
                    return ["[NF]"]

                ev_total = sum(_to_int(r.get("ev_goals") or 0, default=0) for r in skaters)
                pp_total = sum(_to_int(r.get("pp_goals") or 0, default=0) for r in skaters)
                pk_total = sum(_to_int(r.get("pk_goals") or 0, default=0) for r in skaters)

                def _leader(metric_key: str) -> tuple[str, int]:
                    ranked = sorted(
                        skaters,
                        key=lambda r: (
                            _to_int(r.get(metric_key) or 0, default=0),
                            _to_int(r.get("points") or 0, default=0),
                            _to_int(r.get("games") or 0, default=0),
                            str(r.get("name") or ""),
                        ),
                        reverse=True,
                    )
                    if not ranked:
                        return "[NF]", 0
                    top = ranked[0]
                    return (
                        str(top.get("name") or "[NF]"),
                        _to_int(top.get(metric_key) or 0, default=0),
                    )

                ev_name, ev_val = _leader("ev_goals")
                pp_name, pp_val = _leader("pp_goals")
                pk_name, pk_val = _leader("pk_goals")
                return [
                    f"Team Goals: EV {ev_total} | PP {pp_total} | PK {pk_total}",
                    f"EV Leader: {ev_name} ({ev_val})",
                    f"PP Leader: {pp_name} ({pp_val})",
                    f"PK Leader: {pk_name} ({pk_val})",
                ]

            def _goalie_metrics(player_id: int, fallback_sv: Any = None) -> tuple[str, str]:
                season_line = f"Season SV% {_fmt_sv_pct(fallback_sv)}"
                last5_line = "Last 5 SV% [NF]"
                if player_id <= 0:
                    return season_line, last5_line
                landing = _load_player_landing(
                    player_id,
                    allow_network=allow_gamecenter_network,
                    force_network=False,
                )
                if not isinstance(landing, dict):
                    return season_line, last5_line
                season_rows = landing.get("seasonTotals") if isinstance(landing.get("seasonTotals"), list) else []
                season_rows_nhl = [
                    r
                    for r in season_rows
                    if isinstance(r, dict)
                    and str(r.get("leagueAbbrev") or "").upper() == "NHL"
                    and _to_int(r.get("gameTypeId") or 0, default=0) == 2
                ]
                season_row = None
                season_target = _to_int(season_compact or 0, default=0)
                if season_rows_nhl and season_target > 0:
                    for rr in season_rows_nhl:
                        if _to_int(rr.get("season") or 0, default=0) == season_target:
                            season_row = rr
                            break
                if season_row is None and season_rows_nhl:
                    season_row = season_rows_nhl[-1]
                if isinstance(season_row, dict):
                    sv = season_row.get("savePctg")
                    if sv is None:
                        sv = season_row.get("savePercentage")
                    wins = _to_int(season_row.get("wins") or 0, default=0)
                    losses = _to_int(season_row.get("losses") or 0, default=0)
                    otl = _to_int(
                        season_row.get("otLosses")
                        or season_row.get("overtimeLosses")
                        or 0,
                        default=0,
                    )
                    season_line = f"Season SV% {_fmt_sv_pct(sv)} | {wins}-{losses}-{otl}"
                last5_rows = landing.get("last5Games") if isinstance(landing.get("last5Games"), list) else []
                vals: list[float] = []
                for rr in last5_rows[:5]:
                    if not isinstance(rr, dict):
                        continue
                    vv = rr.get("savePctg")
                    if vv is None:
                        vv = rr.get("savePercentage")
                    try:
                        vals.append(float(vv))
                    except Exception:
                        continue
                if vals:
                    last5_line = f"Last 5 SV% {_fmt_sv_pct(sum(vals) / float(len(vals)))}"
                return season_line, last5_line

            def _team_goalie_slots(team_code: str, box_key: str) -> list[str]:
                rows_box: list[dict[str, Any]] = []
                if isinstance(boxscore, dict):
                    pstats = boxscore.get("playerByGameStats") if isinstance(boxscore.get("playerByGameStats"), dict) else {}
                    blob = pstats.get(box_key) if isinstance(pstats.get(box_key), dict) else {}
                    g_rows = blob.get("goalies") if isinstance(blob.get("goalies"), list) else []
                    rows_box = [r for r in g_rows if isinstance(r, dict)]

                candidates: list[dict[str, Any]] = []
                box_candidates: list[dict[str, Any]] = []
                seen_ids: set[int] = set()
                for row in rows_box:
                    pid = _to_int(row.get("playerId") or 0, default=0)
                    name = _goalie_name_from_row(row)
                    starter = bool(row.get("starter"))
                    fallback_sv = row.get("savePctg")
                    activity_score = _goalie_activity_score(row)
                    if pid > 0 and pid in seen_ids:
                        continue
                    if pid > 0:
                        seen_ids.add(pid)
                    slot = {
                        "player_id": pid,
                        "name": name,
                        "starter": starter,
                        "fallback_sv": fallback_sv,
                        "activity_score": activity_score,
                        "source": "box",
                    }
                    candidates.append(slot)
                    box_candidates.append(slot)

                if season_compact:
                    club_rows = _club_stats_goalies(
                        team_code,
                        season_compact=season_compact,
                        allow_network=allow_gamecenter_network,
                    )
                    club_rows = sorted(
                        club_rows,
                        key=lambda r: (
                            -_to_int(r.get("gamesStarted") or 0, default=0),
                            -_to_int(r.get("gamesPlayed") or 0, default=0),
                            -_to_int(r.get("wins") or 0, default=0),
                        ),
                    )
                    for row in club_rows:
                        pid = _to_int(row.get("playerId") or 0, default=0)
                        if pid <= 0 or pid in seen_ids:
                            continue
                        name = _goalie_name_from_row(row)
                        fallback_sv = row.get("savePercentage")
                        seen_ids.add(pid)
                        candidates.append(
                            {
                                "player_id": pid,
                                "name": name,
                                "starter": False,
                                "fallback_sv": fallback_sv,
                                "activity_score": 0,
                                "source": "club",
                            }
                        )

                game_state_u = _game_state(game)
                game_started = game_state_u not in {"FUT", "PRE"}
                confirmed = None
                if game_started and box_candidates:
                    active_rows = [
                        c
                        for c in box_candidates
                        if _to_int(c.get("activity_score") or 0, default=0) > 0
                    ]
                    if active_rows:
                        active_rows.sort(
                            key=lambda c: (
                                _to_int(c.get("activity_score") or 0, default=0),
                                1 if bool(c.get("starter")) else 0,
                                _to_int(c.get("player_id") or 0, default=0),
                            ),
                            reverse=True,
                        )
                        confirmed = active_rows[0]
                if confirmed is None:
                    confirmed = next((c for c in candidates if bool(c.get("starter"))), None)
                probable = None
                if confirmed is not None:
                    probable = next(
                        (
                            c
                            for c in candidates
                            if _to_int(c.get("player_id") or 0, default=0)
                            != _to_int(confirmed.get("player_id") or 0, default=0)
                        ),
                        None,
                    )
                elif candidates:
                    probable = candidates[0]

                lines: list[str] = []

                def _append_goalie_slot(label: str, slot: dict[str, Any]) -> None:
                    pid = _to_int(slot.get("player_id") or 0, default=0)
                    name = str(slot.get("name") or "[NF]").strip() or "[NF]"
                    season_line, last5_line = _goalie_metrics(pid, fallback_sv=slot.get("fallback_sv"))
                    lines.append(f"{label}: {name}")
                    lines.append(f"  {season_line}")
                    lines.append(f"  {last5_line}")
                if isinstance(confirmed, dict):
                    # When confirmed is available, suppress probable to reduce noise.
                    _append_goalie_slot("Confirmed", confirmed)
                elif isinstance(probable, dict):
                    _append_goalie_slot("Probable", probable)
                else:
                    lines.append("Probable: [NF]")
                return lines

            away_goalie_lines = _team_goalie_slots(away_code, "awayTeam")
            home_goalie_lines = _team_goalie_slots(home_code, "homeTeam")

            cw = int(card.frame.winfo_width() or 0)
            ch = int(card.frame.winfo_height() or 0)
            if cw < 20 or ch < 20:
                return
            host_w = int(bgroot.winfo_width() or 0)
            host_h = int(bgroot.winfo_height() or 0)
            popup_w = int(max(360, min(640, cw + 120)))
            popup_h = int(max(440, min(760, int(ch * 1.95))))
            if host_w > 40:
                popup_w = min(popup_w, max(320, host_w - 16))
            if host_h > 40:
                popup_h = min(popup_h, max(320, host_h - 16))
            start_x = int(max(8, min(max(8, host_w - popup_w - 8), (host_w - popup_w) / 2 if host_w > 0 else 8)))
            start_y = int(max(8, min(max(8, host_h - popup_h - 8), (host_h - popup_h) / 2 if host_h > 0 else 8)))

            popup = tk.Frame(
                bgroot,
                bg="#171717",
                bd=1,
                relief="solid",
                highlightthickness=1,
                highlightbackground="#3a3a3a",
            )
            popup.place(x=start_x, y=start_y, width=popup_w, height=popup_h)
            popup.lift()

            def _close_popup(_e=None) -> None:
                _hide_popup(card)

            popup.bind("<Escape>", _close_popup)
            try:
                popup.focus_set()
            except Exception:
                pass

            shell = popup

            topbar = tk.Frame(shell, bg="#202020")
            topbar.pack(fill="x")
            topbar.grid_columnconfigure(0, weight=1)
            topbar.grid_columnconfigure(1, weight=0)
            topbar.grid_columnconfigure(2, weight=1)

            title_var = tk.StringVar(value=f"{away_code} @ {home_code} Game Details")
            back_lbl = tk.Label(
                topbar,
                text="< Back",
                bg="#202020",
                fg=FG,
                font=("Helvetica", 10, "bold"),
                cursor="hand2",
                padx=10,
                pady=8,
            )
            back_lbl.grid(row=0, column=0, sticky="w")
            back_lbl.grid_remove()

            title_lbl = tk.Label(
                topbar,
                textvariable=title_var,
                bg="#202020",
                fg=FG,
                font=("Helvetica", 12, "bold"),
                anchor="center",
                justify="center",
                pady=8,
            )
            title_lbl.grid(row=0, column=1, sticky="n")

            close_lbl = tk.Label(
                topbar,
                text="x",
                bg="#202020",
                fg=FG,
                font=("Helvetica", 12, "bold"),
                cursor="hand2",
                padx=12,
                pady=8,
            )
            close_lbl.grid(row=0, column=2, sticky="e")
            close_lbl.bind("<Button-1>", _close_popup)

            drag: dict[str, int] = {"dx": 0, "dy": 0}

            def _drag_start(e) -> None:
                drag["dx"] = int(e.x_root - popup.winfo_x())
                drag["dy"] = int(e.y_root - popup.winfo_y())

            def _drag_move(e) -> None:
                max_x = max(8, int((bgroot.winfo_width() or host_w) - popup_w - 8))
                max_y = max(8, int((bgroot.winfo_height() or host_h) - popup_h - 8))
                nx = int(e.x_root - drag["dx"])
                ny = int(e.y_root - drag["dy"])
                nx = max(8, min(max_x, nx))
                ny = max(8, min(max_y, ny))
                popup.place_configure(x=nx, y=ny)

            for ww in (topbar, title_lbl):
                ww.bind("<ButtonPress-1>", _drag_start, add="+")
                ww.bind("<B1-Motion>", _drag_move, add="+")

            views_host = tk.Frame(shell, bg="#171717")
            views_host.pack(fill="both", expand=True)

            main_wrap = tk.Frame(views_host, bg="#171717")
            main_wrap.pack(fill="both", expand=True)
            canvas_wrap = tk.Frame(main_wrap, bg="#171717")
            canvas_wrap.pack(fill="both", expand=True)
            canvas = tk.Canvas(canvas_wrap, bg="#171717", highlightthickness=0, bd=0)
            vbar = ttk.Scrollbar(canvas_wrap, orient="vertical", command=canvas.yview)
            canvas.configure(yscrollcommand=vbar.set)
            vbar.pack(side="right", fill="y")
            canvas.pack(side="left", fill="both", expand=True)

            body = tk.Frame(canvas, bg="#171717")
            body_window = canvas.create_window((0, 0), window=body, anchor="nw")

            def _sync_scroll(_e=None) -> None:
                canvas.configure(scrollregion=canvas.bbox("all"))

            def _sync_width(e) -> None:
                canvas.itemconfigure(body_window, width=e.width)

            body.bind("<Configure>", _sync_scroll)
            canvas.bind("<Configure>", _sync_width)

            roster_wrap = tk.Frame(views_host, bg="#171717")
            roster_canvas_wrap = tk.Frame(roster_wrap, bg="#171717")
            roster_canvas_wrap.pack(fill="both", expand=True)
            roster_canvas = tk.Canvas(roster_canvas_wrap, bg="#171717", highlightthickness=0, bd=0)
            roster_vbar = ttk.Scrollbar(roster_canvas_wrap, orient="vertical", command=roster_canvas.yview)
            roster_canvas.configure(yscrollcommand=roster_vbar.set)
            roster_vbar.pack(side="right", fill="y")
            roster_canvas.pack(side="left", fill="both", expand=True)
            roster_body = tk.Frame(roster_canvas, bg="#171717")
            roster_body_window = roster_canvas.create_window((0, 0), window=roster_body, anchor="nw")

            def _sync_roster_scroll(_e=None) -> None:
                roster_canvas.configure(scrollregion=roster_canvas.bbox("all"))

            def _sync_roster_width(e) -> None:
                roster_canvas.itemconfigure(roster_body_window, width=e.width)

            roster_body.bind("<Configure>", _sync_roster_scroll)
            roster_canvas.bind("<Configure>", _sync_roster_width)

            def _on_popup_wheel_for(canvas_target: tk.Canvas, e) -> str | None:
                delta = 0
                if hasattr(e, "delta") and int(getattr(e, "delta", 0)):
                    d = int(getattr(e, "delta", 0))
                    if abs(d) >= 120:
                        delta = -int(d / 120)
                    else:
                        delta = -1 if d > 0 else 1
                elif int(getattr(e, "num", 0)) == 4:
                    delta = -1
                elif int(getattr(e, "num", 0)) == 5:
                    delta = 1
                if delta == 0:
                    return None
                canvas_target.yview_scroll(delta, "units")
                return "break"

            def _bind_popup_scroll_recursive(widget: tk.Widget, canvas_target: tk.Canvas) -> None:
                for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                    widget.bind(seq, lambda e, cv=canvas_target: _on_popup_wheel_for(cv, e), add="+")
                for child in widget.winfo_children():
                    _bind_popup_scroll_recursive(child, canvas_target)

            def _section_title(text: str) -> None:
                tk.Label(
                    body,
                    text=text,
                    bg="#171717",
                    fg=FG,
                    font=("Helvetica", 11, "bold"),
                    anchor="center",
                    justify="center",
                ).pack(fill="x", padx=12, pady=(12, 4))

            def _info_row(label: str, value: str) -> None:
                row = tk.Frame(body, bg="#171717")
                row.pack(fill="x", padx=12, pady=1)
                tk.Label(
                    row,
                    text=f"{label}:",
                    bg="#171717",
                    fg=MUTED,
                    font=("Helvetica", 10, "bold"),
                    width=14,
                    anchor="w",
                ).pack(side="left")
                tk.Label(
                    row,
                    text=(value if value else "[NF]"),
                    bg="#171717",
                    fg=FG,
                    font=("Helvetica", 10),
                    anchor="w",
                    justify="left",
                    wraplength=max(220, popup_w - 230),
                ).pack(side="left", fill="x", expand=True)

            def _show_main_view(_e=None) -> None:
                if str(roster_wrap.winfo_manager() or "").strip():
                    roster_wrap.pack_forget()
                if not str(main_wrap.winfo_manager() or "").strip():
                    main_wrap.pack(fill="both", expand=True)
                title_var.set(f"{away_code} @ {home_code} Game Details")
                back_lbl.grid_remove()
                try:
                    canvas.yview_moveto(0.0)
                except Exception:
                    pass

            popup_imgs: list[Any] = []

            def _player_table_rows(box_key: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
                if not isinstance(boxscore, dict):
                    return [], []
                pstats = boxscore.get("playerByGameStats") if isinstance(boxscore.get("playerByGameStats"), dict) else {}
                blob = pstats.get(box_key) if isinstance(pstats.get(box_key), dict) else {}
                seen_ids: set[int] = set()
                skaters: list[dict[str, Any]] = []
                for grp in ("forwards", "defense", "defencemen", "skaters"):
                    rows = blob.get(grp) if isinstance(blob.get(grp), list) else []
                    for row in rows:
                        if not isinstance(row, dict):
                            continue
                        pid = _to_int(row.get("playerId") or 0, default=0)
                        if pid > 0 and pid in seen_ids:
                            continue
                        if pid > 0:
                            seen_ids.add(pid)
                        skaters.append(row)
                goalies = [r for r in (blob.get("goalies") if isinstance(blob.get("goalies"), list) else []) if isinstance(r, dict)]
                return skaters, goalies

            def _render_roster_view(team_code: str, box_key: str) -> None:
                for child in roster_body.winfo_children():
                    child.destroy()

                skaters, goalies = _player_table_rows(box_key)
                tk.Label(
                    roster_body,
                    text=f"{team_code} Roster Stats",
                    bg="#171717",
                    fg=FG,
                    font=("Helvetica", 12, "bold"),
                    anchor="center",
                    justify="center",
                ).pack(fill="x", padx=12, pady=(12, 8))

                sk_box = tk.Frame(roster_body, bg="#202020", bd=1, relief="solid")
                sk_box.pack(fill="x", padx=12, pady=(0, 6))
                sk_box.grid_columnconfigure(0, weight=0)
                sk_box.grid_columnconfigure(1, weight=1)
                sk_box.grid_columnconfigure(2, weight=0)
                sk_box.grid_columnconfigure(3, weight=0)
                sk_box.grid_columnconfigure(4, weight=0)
                sk_box.grid_columnconfigure(5, weight=0)
                for col, head in enumerate(("#", "Player", "G", "A", "P", "TOI")):
                    tk.Label(sk_box, text=head, bg="#202020", fg=MUTED, font=("Helvetica", 10, "bold")).grid(
                        row=0, column=col, padx=6, pady=(8, 4), sticky="w"
                    )
                if skaters:
                    for i, row in enumerate(skaters, start=1):
                        num = _to_int(row.get("sweaterNumber") or row.get("jerseyNumber") or 0, default=0)
                        g = _to_int(row.get("goals") or 0, default=0)
                        a = _to_int(row.get("assists") or 0, default=0)
                        p = _to_int(row.get("points") or (g + a), default=g + a)
                        toi = str(row.get("toi") or row.get("timeOnIce") or "[NF]").strip() or "[NF]"
                        nm = _goalie_name_from_row(row)
                        vals = (str(num) if num > 0 else "--", nm, str(g), str(a), str(p), toi)
                        for col, txt in enumerate(vals):
                            tk.Label(sk_box, text=txt, bg="#202020", fg=FG, font=("Helvetica", 10)).grid(
                                row=i, column=col, padx=6, pady=1, sticky="w"
                            )
                else:
                    tk.Label(sk_box, text="[NF]", bg="#202020", fg=FG, font=("Helvetica", 10)).grid(
                        row=1, column=0, columnspan=6, padx=8, pady=(0, 8), sticky="w"
                    )

                g_box = tk.Frame(roster_body, bg="#202020", bd=1, relief="solid")
                g_box.pack(fill="x", padx=12, pady=(0, 10))
                for col, head in enumerate(("#", "Goalie", "SV", "SA", "SV%", "TOI")):
                    tk.Label(g_box, text=head, bg="#202020", fg=MUTED, font=("Helvetica", 10, "bold")).grid(
                        row=0, column=col, padx=6, pady=(8, 4), sticky="w"
                    )
                if goalies:
                    for i, row in enumerate(goalies, start=1):
                        num = _to_int(row.get("sweaterNumber") or row.get("jerseyNumber") or 0, default=0)
                        sv = _to_int(row.get("saves") or 0, default=0)
                        sa = _to_int(row.get("shotsAgainst") or 0, default=0)
                        svp = row.get("savePctg")
                        if svp is None:
                            svp = row.get("savePercentage")
                        toi = str(row.get("toi") or row.get("timeOnIce") or "[NF]").strip() or "[NF]"
                        nm = _goalie_name_from_row(row)
                        vals = (str(num) if num > 0 else "--", nm, str(sv), str(sa), _fmt_sv_pct(svp), toi)
                        for col, txt in enumerate(vals):
                            tk.Label(g_box, text=txt, bg="#202020", fg=FG, font=("Helvetica", 10)).grid(
                                row=i, column=col, padx=6, pady=1, sticky="w"
                            )
                else:
                    tk.Label(g_box, text="[NF]", bg="#202020", fg=FG, font=("Helvetica", 10)).grid(
                        row=1, column=0, columnspan=6, padx=8, pady=(0, 8), sticky="w"
                    )

            def _show_roster_view(team_code: str, box_key: str, _e=None) -> None:
                _render_roster_view(team_code, box_key)
                if str(main_wrap.winfo_manager() or "").strip():
                    main_wrap.pack_forget()
                if not str(roster_wrap.winfo_manager() or "").strip():
                    roster_wrap.pack(fill="both", expand=True)
                title_var.set(f"{team_code} Game Roster")
                back_lbl.grid()
                try:
                    roster_canvas.yview_moveto(0.0)
                except Exception:
                    pass

            back_lbl.bind("<Button-1>", _show_main_view)

            # Scoreboard header
            _section_title("Scoreboard")
            score_box = tk.Frame(body, bg="#202020", bd=1, relief="solid")
            score_box.pack(fill="x", padx=12, pady=(0, 4))
            score_box.grid_columnconfigure(0, weight=1)
            score_box.grid_columnconfigure(1, weight=0)
            score_box.grid_columnconfigure(2, weight=1)

            away_logo = _logo_get(logos, away_code, height=62, master=popup, league=league_name)
            home_logo = _logo_get(logos, home_code, height=62, master=popup, league=league_name)
            if away_logo is not None:
                popup_imgs.append(away_logo)
                away_logo_lbl = tk.Label(score_box, image=away_logo, bg="#202020", cursor="hand2")
            else:
                away_logo_lbl = tk.Label(score_box, text=away_code, bg="#202020", fg=FG, font=("Helvetica", 12, "bold"), cursor="hand2")
            away_logo_lbl.grid(row=0, column=0, pady=(10, 2))
            tk.Label(score_box, text="@", bg="#202020", fg=MUTED, font=("Helvetica", 13, "bold")).grid(row=0, column=1, padx=8, pady=(10, 2))
            if home_logo is not None:
                popup_imgs.append(home_logo)
                home_logo_lbl = tk.Label(score_box, image=home_logo, bg="#202020", cursor="hand2")
            else:
                home_logo_lbl = tk.Label(score_box, text=home_code, bg="#202020", fg=FG, font=("Helvetica", 12, "bold"), cursor="hand2")
            home_logo_lbl.grid(row=0, column=2, pady=(10, 2))

            away_logo_lbl.bind("<Button-1>", lambda e: _show_roster_view(away_code, "awayTeam", e))
            home_logo_lbl.bind("<Button-1>", lambda e: _show_roster_view(home_code, "homeTeam", e))

            tk.Label(score_box, text=str(away_score), bg="#202020", fg=FG, font=("Helvetica", 22, "bold")).grid(row=1, column=0, pady=(0, 10))
            tk.Label(score_box, text="-", bg="#202020", fg=FG, font=("Helvetica", 20, "bold")).grid(row=1, column=1, pady=(0, 10))
            tk.Label(score_box, text=str(home_score), bg="#202020", fg=FG, font=("Helvetica", 22, "bold")).grid(row=1, column=2, pady=(0, 10))

            # Goalie panel
            _section_title("Goalies")
            goalie_box = tk.Frame(body, bg="#202020", bd=1, relief="solid")
            goalie_box.pack(fill="x", padx=12, pady=(0, 4))
            goalie_box.grid_columnconfigure(0, weight=1, uniform="goalie")
            goalie_box.grid_columnconfigure(1, weight=1, uniform="goalie")
            away_goalie_txt = "\n".join(away_goalie_lines) if away_goalie_lines else "[NF]"
            home_goalie_txt = "\n".join(home_goalie_lines) if home_goalie_lines else "[NF]"
            tk.Label(
                goalie_box,
                text=away_goalie_txt,
                bg="#202020",
                fg=FG,
                font=("Helvetica", 10),
                justify="left",
                anchor="nw",
                wraplength=max(140, (popup_w // 2) - 44),
            ).grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
            tk.Label(
                goalie_box,
                text=home_goalie_txt,
                bg="#202020",
                fg=FG,
                font=("Helvetica", 10),
                justify="left",
                anchor="nw",
                wraplength=max(140, (popup_w // 2) - 44),
            ).grid(row=0, column=1, sticky="nsew", padx=8, pady=8)

            # Goal scorers
            _section_title("Goal Scorers")
            scorer_box = tk.Frame(body, bg="#202020", bd=1, relief="solid")
            scorer_box.pack(fill="x", padx=12, pady=(0, 4))
            scorer_box.grid_columnconfigure(0, weight=1, uniform="sc")
            scorer_box.grid_columnconfigure(1, weight=1, uniform="sc")
            left_txt = "\n".join(left_lines) if left_lines else ""
            right_txt = "\n".join(right_lines) if right_lines else ""
            tk.Label(
                scorer_box,
                text=left_txt,
                bg="#202020",
                fg=FG,
                font=("Helvetica", 10),
                justify="left",
                anchor="nw",
                wraplength=max(140, (popup_w // 2) - 44),
            ).grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
            tk.Label(
                scorer_box,
                text=right_txt,
                bg="#202020",
                fg=FG,
                font=("Helvetica", 10),
                justify="left",
                anchor="nw",
                wraplength=max(140, (popup_w // 2) - 44),
            ).grid(row=0, column=1, sticky="nsew", padx=8, pady=8)

            # Location / game info
            _section_title("Location / Scratches")
            location_txt = ", ".join([x for x in (venue_name, venue_city) if x]).strip() or "[NF]"
            _info_row("Networks", ", ".join(networks) if networks else "[NF]")
            _info_row("Location", location_txt)
            _info_row("Officials", officials_txt)
            _info_row("Away Coach", away_coach_txt)
            _info_row("Home Coach", home_coach_txt)
            _info_row("Away Scratches", away_scratches_txt)
            _info_row("Home Scratches", home_scratches_txt)

            # Shots per period
            _section_title("Shots On Goal")
            shots_box = tk.Frame(body, bg="#202020", bd=1, relief="solid")
            shots_box.pack(fill="x", padx=12, pady=(0, 4))
            shots_box.grid_columnconfigure(0, weight=1, uniform="shots")
            shots_box.grid_columnconfigure(1, weight=1, uniform="shots")
            shots_box.grid_columnconfigure(2, weight=1, uniform="shots")
            for r, row in enumerate(period_rows, start=0):
                tk.Label(
                    shots_box,
                    text=row[1],
                    bg="#202020",
                    fg=FG,
                    font=("Helvetica", 10),
                    anchor="center",
                    justify="center",
                ).grid(row=r, column=0, padx=8, pady=2, sticky="ew")
                tk.Label(
                    shots_box,
                    text=row[0],
                    bg="#202020",
                    fg=FG,
                    font=("Helvetica", 10, "bold" if row[0] == "TOTAL" else "normal"),
                    anchor="center",
                    justify="center",
                ).grid(row=r, column=1, padx=8, pady=2, sticky="ew")
                tk.Label(
                    shots_box,
                    text=row[2],
                    bg="#202020",
                    fg=FG,
                    font=("Helvetica", 10),
                    anchor="center",
                    justify="center",
                ).grid(row=r, column=2, padx=8, pady=2, sticky="ew")

            # Game stats
            _section_title("Game Stats")
            stat_box = tk.Frame(body, bg="#202020", bd=1, relief="solid")
            stat_box.pack(fill="x", padx=12, pady=(0, 4))
            stat_box.grid_columnconfigure(0, weight=1, uniform="stat")
            stat_box.grid_columnconfigure(1, weight=1, uniform="stat")
            stat_box.grid_columnconfigure(2, weight=1, uniform="stat")
            for r, row in enumerate(game_stat_rows, start=0):
                tk.Label(stat_box, text=row[1], bg="#202020", fg=FG, font=("Helvetica", 10), anchor="center", justify="center").grid(row=r, column=0, padx=8, pady=2, sticky="ew")
                tk.Label(stat_box, text=row[0], bg="#202020", fg=MUTED, font=("Helvetica", 10), anchor="center", justify="center").grid(row=r, column=1, padx=8, pady=2, sticky="ew")
                tk.Label(stat_box, text=row[2], bg="#202020", fg=FG, font=("Helvetica", 10), anchor="center", justify="center").grid(row=r, column=2, padx=8, pady=2, sticky="ew")

            # Team leader splits from NHL club stats
            _section_title("Team Stats Leader Splits")
            split_box = tk.Frame(body, bg="#202020", bd=1, relief="solid")
            split_box.pack(fill="x", padx=12, pady=(0, 4))
            split_box.grid_columnconfigure(0, weight=1, uniform="splits")
            split_box.grid_columnconfigure(1, weight=1, uniform="splits")
            away_split_txt = "\n".join(_team_split_leader_lines(away_code))
            home_split_txt = "\n".join(_team_split_leader_lines(home_code))
            tk.Label(
                split_box,
                text=away_split_txt,
                bg="#202020",
                fg=FG,
                font=("Helvetica", 10),
                justify="left",
                anchor="nw",
                wraplength=max(140, (popup_w // 2) - 44),
            ).grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
            tk.Label(
                split_box,
                text=home_split_txt,
                bg="#202020",
                fg=FG,
                font=("Helvetica", 10),
                justify="left",
                anchor="nw",
                wraplength=max(140, (popup_w // 2) - 44),
            ).grid(row=0, column=1, sticky="nsew", padx=8, pady=8)

            # Live special teams context
            _section_title("Special Teams Context")
            special_box = tk.Frame(body, bg="#202020", bd=1, relief="solid")
            special_box.pack(fill="x", padx=12, pady=(0, 4))
            special_state = str(special_pack.get("state_line") or "").strip() if isinstance(special_pack, dict) else ""
            away_taken = _to_int((special_pack.get("away_taken") if isinstance(special_pack, dict) else 0) or 0, default=0)
            away_drawn = _to_int((special_pack.get("away_drawn") if isinstance(special_pack, dict) else 0) or 0, default=0)
            home_taken = _to_int((special_pack.get("home_taken") if isinstance(special_pack, dict) else 0) or 0, default=0)
            home_drawn = _to_int((special_pack.get("home_drawn") if isinstance(special_pack, dict) else 0) or 0, default=0)
            tk.Label(
                special_box,
                text=(special_state if special_state else "Even Strength / [NF]"),
                bg="#202020",
                fg=FG,
                font=("Helvetica", 10, "bold"),
                anchor="center",
                justify="center",
            ).pack(fill="x", padx=8, pady=(8, 4))
            tk.Label(
                special_box,
                text=f"{away_code} Penalties: Taken {away_taken}, Drawn {away_drawn}",
                bg="#202020",
                fg=FG,
                font=("Helvetica", 10),
                anchor="w",
            ).pack(fill="x", padx=8, pady=1)
            tk.Label(
                special_box,
                text=f"{home_code} Penalties: Taken {home_taken}, Drawn {home_drawn}",
                bg="#202020",
                fg=FG,
                font=("Helvetica", 10),
                anchor="w",
            ).pack(fill="x", padx=8, pady=(1, 8))

            # Penalty summary (from gamecenter play-by-play when available)
            _section_title("Penalty Summary")
            pen_box = tk.Frame(body, bg="#202020", bd=1, relief="solid")
            pen_box.pack(fill="x", padx=12, pady=(0, 4))
            if penalties_rows:
                for i, head in enumerate(("Per", "Time", "Team", "Min", "Penalty")):
                    tk.Label(pen_box, text=head, bg="#202020", fg=MUTED, font=("Helvetica", 10, "bold")).grid(row=0, column=i, padx=6, pady=(8, 4), sticky="w")
                for idx, row in enumerate(penalties_rows[:16], start=1):
                    period_num = _to_int(row.get("period") or 0, default=0)
                    period_txt = _period_suffix(period_num) if period_num > 0 else "[NF]"
                    tk.Label(pen_box, text=period_txt, bg="#202020", fg=FG, font=("Helvetica", 9)).grid(row=idx, column=0, padx=6, pady=1, sticky="w")
                    tk.Label(pen_box, text=str(row.get("time") or "[NF]"), bg="#202020", fg=FG, font=("Helvetica", 9)).grid(row=idx, column=1, padx=6, pady=1, sticky="w")
                    tk.Label(pen_box, text=str(row.get("team") or "[NF]"), bg="#202020", fg=FG, font=("Helvetica", 9, "bold")).grid(row=idx, column=2, padx=6, pady=1, sticky="w")
                    mins_val = _to_int(row.get("minutes") or 0, default=0)
                    mins_txt = str(int(mins_val)) if mins_val > 0 else "[NF]"
                    tk.Label(
                        pen_box,
                        text=mins_txt,
                        bg="#202020",
                        fg=FG,
                        font=("Helvetica", 9),
                    ).grid(row=idx, column=3, padx=6, pady=1, sticky="w")
                    tk.Label(
                        pen_box,
                        text=str(row.get("desc") or "[NF]"),
                        bg="#202020",
                        fg=FG,
                        font=("Helvetica", 9),
                        justify="left",
                        anchor="w",
                        wraplength=max(170, popup_w - 290),
                    ).grid(row=idx, column=4, padx=6, pady=1, sticky="w")
            else:
                tk.Label(pen_box, text="[NF]", bg="#202020", fg=FG, font=("Helvetica", 10)).pack(anchor="w", padx=8, pady=8)

            # Season series
            _section_title("Season Series")
            series_box = tk.Frame(body, bg="#202020", bd=1, relief="solid")
            series_box.pack(fill="x", padx=12, pady=(0, 12))
            tk.Label(
                series_box,
                text=series_headline,
                bg="#202020",
                fg=FG,
                font=("Helvetica", 10, "bold"),
                anchor="center",
                justify="center",
            ).pack(fill="x", padx=8, pady=(8, 4))
            if series_rows:
                cards_wrap = tk.Frame(series_box, bg="#202020")
                cards_wrap.pack(fill="x", padx=8, pady=(0, 8))
                cards_wrap.grid_columnconfigure(0, weight=1, uniform="series")
                cards_wrap.grid_columnconfigure(1, weight=1, uniform="series")

                def _series_card_data(text: str) -> dict[str, str]:
                    raw = str(text or "").strip()
                    out = {
                        "date": "[NF]",
                        "away": "",
                        "home": "",
                        "score": raw or "[NF]",
                        "status": "",
                    }
                    if not raw:
                        return out
                    date_match = re.search(
                        r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2}(?:,\s*\d{4})?\b",
                        raw,
                        flags=re.IGNORECASE,
                    )
                    if date_match is None:
                        date_match = re.search(r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b", raw)
                    if date_match is None:
                        date_match = re.search(r"\b\d{4}-\d{2}-\d{2}\b", raw)
                    if date_match is not None:
                        out["date"] = str(date_match.group(0) or "").strip() or "[NF]"
                    m_final = re.search(
                        r"\b([A-Z]{2,3})\s+(\d+)\s*-\s*([A-Z]{2,3})\s+(\d+)\b(.*)",
                        raw,
                    )
                    if m_final is not None:
                        out["away"] = str(m_final.group(1) or "").strip()
                        out["home"] = str(m_final.group(3) or "").strip()
                        out["score"] = f"{m_final.group(2)} - {m_final.group(4)}"
                        tail = str(m_final.group(5) or "").strip()
                        if out["date"] != "[NF]" and out["date"] in tail:
                            tail = tail.replace(out["date"], "").strip()
                        out["status"] = tail
                        return out
                    m_upcoming = re.search(r"\b([A-Z]{2,3})\s+@\s+([A-Z]{2,3})\b(.*)", raw)
                    if m_upcoming is not None:
                        out["away"] = str(m_upcoming.group(1) or "").strip()
                        out["home"] = str(m_upcoming.group(2) or "").strip()
                        tail = str(m_upcoming.group(3) or "").strip()
                        if out["date"] != "[NF]" and out["date"] in tail:
                            tail = tail.replace(out["date"], "").strip()
                        out["score"] = tail or "@"
                        return out
                    return out

                for idx, row in enumerate(series_rows):
                    card_data = _series_card_data(row)
                    mini = tk.Frame(
                        cards_wrap,
                        bg="#3f3f3f",
                        bd=1,
                        relief="solid",
                        highlightthickness=1,
                        highlightbackground="#4a4a4a",
                    )
                    mini.grid(row=idx // 2, column=idx % 2, sticky="nsew", padx=4, pady=4)
                    tk.Label(
                        mini,
                        text=card_data.get("date") or "[NF]",
                        bg="#3f3f3f",
                        fg=MUTED,
                        font=("Helvetica", 9, "bold"),
                        anchor="center",
                        justify="center",
                    ).pack(fill="x", padx=8, pady=(6, 1))
                    logos_row = tk.Frame(mini, bg="#3f3f3f")
                    logos_row.pack(fill="x", padx=8, pady=(0, 1))
                    logos_row.grid_columnconfigure(0, weight=1)
                    logos_row.grid_columnconfigure(1, weight=0)
                    logos_row.grid_columnconfigure(2, weight=1)
                    away_code_sr = str(card_data.get("away") or "").upper().strip()
                    home_code_sr = str(card_data.get("home") or "").upper().strip()
                    away_sr_img = _logo_get(logos, away_code_sr, height=22, master=popup, league="NHL") if away_code_sr else None
                    home_sr_img = _logo_get(logos, home_code_sr, height=22, master=popup, league="NHL") if home_code_sr else None
                    if away_sr_img is not None:
                        popup_imgs.append(away_sr_img)
                        tk.Label(logos_row, image=away_sr_img, bg="#3f3f3f").grid(row=0, column=0, sticky="e")
                    else:
                        tk.Label(logos_row, text=(away_code_sr or "[NF]"), bg="#3f3f3f", fg=FG, font=("Helvetica", 9, "bold")).grid(row=0, column=0, sticky="e")
                    tk.Label(logos_row, text="@", bg="#3f3f3f", fg=MUTED, font=("Helvetica", 9, "bold")).grid(row=0, column=1, padx=6)
                    if home_sr_img is not None:
                        popup_imgs.append(home_sr_img)
                        tk.Label(logos_row, image=home_sr_img, bg="#3f3f3f").grid(row=0, column=2, sticky="w")
                    else:
                        tk.Label(logos_row, text=(home_code_sr or "[NF]"), bg="#3f3f3f", fg=FG, font=("Helvetica", 9, "bold")).grid(row=0, column=2, sticky="w")
                    tk.Label(
                        mini,
                        text=str(card_data.get("score") or "[NF]"),
                        bg="#3f3f3f",
                        fg=FG,
                        font=("Helvetica", 10),
                        anchor="center",
                        justify="center",
                        wraplength=max(220, popup_w - 88),
                    ).pack(fill="x", padx=8, pady=(0, 6))
                    status_txt = str(card_data.get("status") or "").strip()
                    if status_txt:
                        tk.Label(
                            mini,
                            text=status_txt,
                            bg="#3f3f3f",
                            fg=MUTED,
                            font=("Helvetica", 9),
                            anchor="center",
                            justify="center",
                            wraplength=max(220, popup_w - 88),
                        ).pack(fill="x", padx=8, pady=(0, 6))
            else:
                tk.Label(series_box, text="[NF]", bg="#202020", fg=FG, font=("Helvetica", 10), anchor="center").pack(fill="x", padx=8, pady=(0, 8))

            try:
                popup.update_idletasks()
                req_h = int(topbar.winfo_reqheight() + body.winfo_reqheight() + 14)
                max_h = max(320, int((bgroot.winfo_height() or host_h) - 16))
                target_h = max(320, min(max_h, req_h))
                cur_x = int(popup.winfo_x() or start_x)
                cur_y = int(popup.winfo_y() or start_y)
                max_x = max(8, int((bgroot.winfo_width() or host_w) - popup_w - 8))
                max_y = max(8, int((bgroot.winfo_height() or host_h) - target_h - 8))
                popup.place_configure(
                    x=max(8, min(max_x, cur_x)),
                    y=max(8, min(max_y, cur_y)),
                    width=popup_w,
                    height=target_h,
                )
            except Exception:
                pass

            _bind_popup_scroll_recursive(main_wrap, canvas)
            _bind_popup_scroll_recursive(roster_wrap, roster_canvas)

            popup._popup_imgs = popup_imgs  # type: ignore[attr-defined]
            card.scorer_popup = popup

        def _toggle_popup(card: _Card, game: dict[str, Any]) -> None:
            if card.scorer_popup is not None:
                _hide_popup(card)
                return
            _show_popup(card, game)

        def _set_rollover_card(target: Optional[_Card]) -> None:
            for cc, gg in zip(cards, games):
                is_active = cc is target
                cc.is_hovered = is_active
                _layout_card(cc, gg, selected_date, show_rollover=is_active)

        pointer_target = None
        for cc in cards:
            if _pointer_inside(cc.frame):
                pointer_target = cc
                break

        for card, game in zip(cards, games):
            try:
                card.is_hovered = bool(card is pointer_target)
                _layout_card(card, game, selected_date, show_rollover=card.is_hovered)
                for w in (card.frame, card.panel, card.overlay):
                    w.bind(
                        "<Enter>",
                        lambda _e, c=card: _set_rollover_card(c),
                        add="+",
                    )
                    w.bind(
                        "<Leave>",
                        lambda _e, c=card: (None if _pointer_inside(c.frame) else _set_rollover_card(None)),
                        add="+",
                    )
                    w.bind("<Button-1>", lambda _e, c=card, g=game: _toggle_popup(c, g))
            except Exception:
                # Never leave a silently blank grid because one card failed.
                continue

    def _cache_keys_for_date(d: dt.date) -> tuple[str, str]:
        iso = d.isoformat()
        return (f"nhl/score/final/{iso}", f"nhl/score/live/{iso}")

    def _schedule_cache_key_for_date(d: dt.date) -> str:
        return f"nhl/schedule/{d.isoformat()}"

    def _load_schedule_payload_for_date(
        d: dt.date,
        *,
        allow_network: bool,
        force_network: bool = False,
    ) -> Optional[dict[str, Any]]:
        key = _schedule_cache_key_for_date(d)
        if allow_network and force_network:
            # Manual refresh path: bypass long schedule TTL and repopulate cache.
            try:
                force_get = getattr(nhl, "_get_json", None)
                if callable(force_get):
                    raw_force = force_get(f"/v1/schedule/{d.isoformat()}", key, ttl_s=-1)
                    if isinstance(raw_force, dict):
                        return raw_force
            except Exception:
                pass
        try:
            hit = nhl.cache.get_json(key, ttl_s=None)  # type: ignore[attr-defined]
            if isinstance(hit, dict):
                return hit
        except Exception:
            pass
        if not allow_network:
            return None
        try:
            raw = nhl.schedule_by_date(d)
            if isinstance(raw, dict):
                return raw
        except Exception:
            pass
        return None

    def _extract_schedule_games(payload: dict[str, Any]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        direct = payload.get("games")
        if isinstance(direct, list):
            out.extend([g for g in direct if isinstance(g, dict)])
        weeks = payload.get("gameWeek")
        if isinstance(weeks, list):
            for wk in weeks:
                if not isinstance(wk, dict):
                    continue
                rows = wk.get("games")
                if isinstance(rows, list):
                    out.extend([g for g in rows if isinstance(g, dict)])
        return out

    def _apply_schedule_start_overrides(
        d: dt.date,
        score_payload: dict[str, Any],
        *,
        allow_network: bool,
        force_network: bool = False,
    ) -> dict[str, Any]:
        games = score_payload.get("games")
        if not isinstance(games, list) or not games:
            return score_payload

        sched_payload = _load_schedule_payload_for_date(
            d,
            allow_network=allow_network,
            force_network=force_network,
        )
        if not isinstance(sched_payload, dict):
            return score_payload

        sched_map: dict[int, dict[str, Any]] = {}
        for sg in _extract_schedule_games(sched_payload):
            gid = _to_int(sg.get("id") or sg.get("gameId") or 0, default=0)
            if gid > 0:
                sched_map[gid] = sg
        if not sched_map:
            return score_payload

        changed = False
        merged_games: list[dict[str, Any]] = []
        for g in games:
            if not isinstance(g, dict):
                continue
            gid = _to_int(g.get("id") or g.get("gameId") or 0, default=0)
            sg = sched_map.get(gid)
            if sg is None:
                merged_games.append(g)
                continue
            state = _game_state(g)
            # Prefer schedule feed times for future/pre-game cards when score feed lags.
            if state not in {"FUT", "PRE", "SCHEDULED"}:
                merged_games.append(g)
                continue

            sched_start = str(sg.get("startTimeUTC") or sg.get("startTime") or "").strip()
            sched_state = str(sg.get("gameScheduleState") or "").strip()
            if not sched_start and not sched_state:
                merged_games.append(g)
                continue

            cur = dict(g)
            if sched_start:
                cur["startTimeUTC"] = sched_start
                if sg.get("startTime") is not None:
                    cur["startTime"] = sg.get("startTime")
            if sched_state:
                cur["gameScheduleState"] = sched_state
            if cur != g:
                changed = True
            merged_games.append(cur)

        if not changed:
            return score_payload
        out = dict(score_payload)
        out["games"] = merged_games
        return out

    def _finalized_key(d: dt.date) -> str:
        return f"nhl/day_finalized/{d.isoformat()}"

    def _is_day_finalized(d: dt.date) -> bool:
        if d == today:
            # Never hard-lock "today"; live updates may still occur.
            return False
        try:
            hit = nhl.cache.get_json(_finalized_key(d), ttl_s=None)  # type: ignore[attr-defined]
            return bool(hit is True or (isinstance(hit, dict) and bool(hit.get("finalized"))))
        except Exception:
            return False

    def _set_day_finalized(d: dt.date, finalized: bool) -> None:
        try:
            nhl.cache.set_json(_finalized_key(d), {"finalized": bool(finalized)})  # type: ignore[attr-defined]
        except Exception:
            pass

    def _game_started_and_not_final(
        g: dict[str, Any],
        *,
        assume_started_if_unknown: bool = False,
    ) -> bool:
        st = _game_state(g)
        if st in {"FINAL", "OFF"} or st.startswith("FINAL"):
            return False
        start_local = _parse_start_local(g, tz)
        if start_local is not None:
            return dt.datetime.now(tz) >= start_local
        if assume_started_if_unknown:
            return st not in {"", "FUT", "PRE", "SCHEDULED"}
        return st in {"LIVE", "CRIT"}

    def _is_live_clock_running(g: dict[str, Any]) -> bool:
        st = _game_state(g)
        if st not in {"LIVE", "CRIT"}:
            return False
        clock = g.get("clock") if isinstance(g.get("clock"), dict) else {}
        if bool(clock.get("inIntermission")):
            return False
        rem = str(clock.get("timeRemaining") or clock.get("time") or "").strip()
        if rem and re.fullmatch(r"0*:00", rem):
            return False
        return "INTERMISSION" not in _live_status(g).upper()

    def _format_refresh_status(
        prefix: str,
        *,
        nhl_n: int,
        olympics_n: int,
        pwhl_n: int,
        elapsed_s: float | None = None,
        target_date: Optional[dt.date] = None,
    ) -> str:
        counts: list[str] = []
        if int(nhl_n) > 0:
            counts.append(f"NHL {int(nhl_n)}")
        if int(olympics_n) > 0:
            counts.append(f"Olympics {int(olympics_n)}")
        if int(pwhl_n) > 0:
            counts.append(f"PWHL {int(pwhl_n)}")
        head = f"{prefix} ({_fmt_short_date(target_date)}) {_fmt_updated_ts()}" if isinstance(target_date, dt.date) else f"{prefix} {_fmt_updated_ts()}"
        chunks: list[str] = [head]
        if counts:
            chunks.append("  ".join(counts))
        if elapsed_s is not None:
            chunks.append(f"{max(0.0, float(elapsed_s)):.2f}s")
        return "  |  ".join(chunks)

    def _needs_live_refresh(
        games: list[dict[str, Any]],
        *,
        assume_started_if_unknown: bool = False,
    ) -> bool:
        if not games:
            return False
        return any(
            _game_started_and_not_final(
                g, assume_started_if_unknown=assume_started_if_unknown
            )
            for g in games
        )

    def _get_score_payload(
        d: dt.date,
        *,
        prefer_cached: bool,
        allow_network: bool,
        force_network: bool = False,
    ) -> tuple[dict[str, Any], Optional[str], str]:
        def _stamp_from_cache() -> str:
            fk, lk = _cache_keys_for_date(d)
            fdata, fts = nhl.cache.get_json_with_meta(fk, ttl_s=None)  # type: ignore[attr-defined]
            ldata, lts = nhl.cache.get_json_with_meta(lk, ttl_s=None)  # type: ignore[attr-defined]
            cands: list[float] = []
            if isinstance(fdata, dict) and isinstance(fts, (int, float)):
                cands.append(float(fts))
            if isinstance(ldata, dict) and isinstance(lts, (int, float)):
                cands.append(float(lts))
            return f"Updated: {_fmt_updated_from_unix(max(cands) if cands else None)}"

        def _all_final(games: list[dict[str, Any]]) -> bool:
            if not games:
                return False
            return all((_game_state(g) in {"FINAL", "OFF"} or _game_state(g).startswith("FINAL")) for g in games)

        if d == today:
            # Forced manual refresh should always bypass cache short-circuits.
            if allow_network and force_network:
                try:
                    raw_today = nhl.score(d, force_network=True)
                    if isinstance(raw_today, dict):
                        _set_day_finalized(d, _all_final(list(raw_today.get("games") or [])))
                        day_payload_cache[d] = raw_today
                        stamp = _stamp_from_cache()
                        day_payload_stamp[d] = stamp
                        return raw_today, None, stamp
                except Exception as e:
                    if d in day_payload_cache:
                        return day_payload_cache[d], f"Using cached data ({e})", day_payload_stamp.get(d, f"Updated: {_fmt_updated_ts()}")
                    return {"games": []}, f"Failed to load games ({e})", f"Updated: {_fmt_updated_ts()}"

            if _is_day_finalized(d):
                if d in day_payload_cache:
                    return day_payload_cache[d], None, day_payload_stamp.get(d, f"Updated: {_fmt_updated_ts()}")
                fk, lk = _cache_keys_for_date(d)
                fdata = nhl.cache.get_json(fk, ttl_s=None)  # type: ignore[attr-defined]
                ldata = nhl.cache.get_json(lk, ttl_s=None)  # type: ignore[attr-defined]
                if isinstance(fdata, dict):
                    stamp = _stamp_from_cache()
                    day_payload_cache[d] = fdata
                    day_payload_stamp[d] = stamp
                    return fdata, None, stamp
                if isinstance(ldata, dict):
                    stamp = _stamp_from_cache()
                    day_payload_cache[d] = ldata
                    day_payload_stamp[d] = stamp
                    return ldata, None, stamp
            # If today is cached and no in-progress game could exist, avoid API calls.
            if d in day_payload_cache:
                cached_games = list((day_payload_cache[d].get("games") or []))
                if not _needs_live_refresh(
                    cached_games, assume_started_if_unknown=True
                ):
                    _set_day_finalized(d, _all_final(cached_games))
                    return day_payload_cache[d], None, day_payload_stamp.get(d, f"Updated: {_fmt_updated_ts()}")
            # Also honor disk cache first under same policy.
            fk, lk = _cache_keys_for_date(d)
            fdata, fts = nhl.cache.get_json_with_meta(fk, ttl_s=None)  # type: ignore[attr-defined]
            ldata, lts = nhl.cache.get_json_with_meta(lk, ttl_s=None)  # type: ignore[attr-defined]
            for data_obj, ts in ((fdata, fts), (ldata, lts)):
                if isinstance(data_obj, dict):
                    games = list(data_obj.get("games") or [])
                    if not _needs_live_refresh(
                        games, assume_started_if_unknown=True
                    ):
                        _set_day_finalized(d, _all_final(games))
                        stamp = f"Updated: {_fmt_updated_from_unix(ts)}"
                        day_payload_cache[d] = data_obj
                        day_payload_stamp[d] = stamp
                        return data_obj, None, stamp
            if allow_network:
                # Manual refresh path for today: use API only when requested.
                try:
                    raw_today = nhl.score(d, force_network=force_network)
                    if isinstance(raw_today, dict):
                        _set_day_finalized(d, _all_final(list(raw_today.get("games") or [])))
                        day_payload_cache[d] = raw_today
                        stamp = _stamp_from_cache()
                        day_payload_stamp[d] = stamp
                        return raw_today, None, stamp
                except Exception as e:
                    if d in day_payload_cache:
                        return day_payload_cache[d], f"Using cached data ({e})", day_payload_stamp.get(d, f"Updated: {_fmt_updated_ts()}")
                    return {"games": []}, f"Failed to load games ({e})", f"Updated: {_fmt_updated_ts()}"

        if prefer_cached and d in day_payload_cache:
            return day_payload_cache[d], None, day_payload_stamp.get(d, f"Updated: {_fmt_updated_ts()}")

        # Disk cache first (no TTL) to minimize network calls.
        final_key, live_key = _cache_keys_for_date(d)
        final_hit: Optional[dict[str, Any]] = None
        live_hit: Optional[dict[str, Any]] = None
        try:
            hit = nhl.cache.get_json(final_key, ttl_s=None)  # type: ignore[attr-defined]
            if isinstance(hit, dict):
                final_hit = hit
            hit = nhl.cache.get_json(live_key, ttl_s=None)  # type: ignore[attr-defined]
            if isinstance(hit, dict):
                live_hit = hit
        except Exception:
            pass

        # Past/future policy:
        # - Use cached FINAL when present.
        # - If only LIVE cache exists and it's final, use it.
        # - Only hit network for past days that still show non-final games.
        if final_hit is not None:
            _set_day_finalized(d, True)
            day_payload_cache[d] = final_hit
            stamp = _stamp_from_cache()
            day_payload_stamp[d] = stamp
            return final_hit, None, stamp

        if live_hit is not None:
            live_games = list(live_hit.get("games") or [])
            if _all_final(live_games):
                _set_day_finalized(d, True)
                day_payload_cache[d] = live_hit
                stamp = _stamp_from_cache()
                day_payload_stamp[d] = stamp
                return live_hit, None, stamp
            _set_day_finalized(d, False)
            if allow_network and (d < today or force_network):
                # Past non-final days can refresh from API.
                # Also allow a forced manual refresh for future days
                # so upcoming playoff games can be fetched even if the
                # live cache is stale or empty.
                try:
                    raw = nhl.score(d, force_network=force_network)
                    if isinstance(raw, dict):
                        if d <= today:
                            _set_day_finalized(d, _all_final(list(raw.get("games") or [])))
                        day_payload_cache[d] = raw
                        stamp = _stamp_from_cache()
                        day_payload_stamp[d] = stamp
                        return raw, None, stamp
                except Exception as e:
                    day_payload_cache[d] = live_hit
                    stamp = _stamp_from_cache()
                    day_payload_stamp[d] = stamp
                    return live_hit, f"Using cached data ({e})", stamp
            day_payload_cache[d] = live_hit
            stamp = _stamp_from_cache()
            day_payload_stamp[d] = stamp
            return live_hit, None, stamp

        # No cache entry:
        if allow_network and (d < today or force_network):
            # Allow one API fill for past days, and also for future days
            # when the user explicitly forces a refresh.
            try:
                raw = nhl.score(d, force_network=force_network)
                if isinstance(raw, dict):
                    if d <= today:
                        _set_day_finalized(d, _all_final(list(raw.get("games") or [])))
                    day_payload_cache[d] = raw
                    stamp = _stamp_from_cache()
                    day_payload_stamp[d] = stamp
                    return raw, None, stamp
            except Exception as e:
                return {"games": []}, f"Failed to load games ({e})", f"Updated: {_fmt_updated_ts()}"

        # Future (and any unresolved case): cache-only.
        return {"games": []}, None, f"Updated: {_fmt_updated_ts()}"

    def _fetch_espn_games(
        d: dt.date,
        *,
        allow_network: bool,
        force_network: bool = False,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
        discovered: list[dict[str, str]] = []

        def _summary_key(league_code: str, event_id: int) -> str:
            slug = re.sub(r"[^a-z0-9-]+", "-", str(league_code or "").lower()).strip("-")
            return f"espn/hockey/{slug or 'league'}/summary/{int(event_id)}"

        def _summary_shots_from_stats(rows: Any) -> Optional[int]:
            if not isinstance(rows, list):
                return None
            for r in rows:
                if not isinstance(r, dict):
                    continue
                nm = str(r.get("name") or r.get("displayName") or "").lower()
                ab = str(r.get("abbreviation") or "").upper()
                if "shootout" in nm:
                    continue
                if nm in {"shotstotal", "shots total", "total shots"} or (ab in {"S", "ST"} and "shot" in nm):
                    v = _to_int(r.get("value") or r.get("displayValue"), default=-1)
                    if v >= 0:
                        return v
            return None

        def _parse_summary_enrichment(payload: dict[str, Any], *, league_hint: str = "") -> dict[str, dict[str, Any]]:
            out: dict[str, dict[str, Any]] = {}
            side_map: dict[str, str] = {}
            team_id_to_code: dict[str, str] = {}
            athlete_to_code: dict[str, str] = {}
            athlete_name_to_code: dict[str, str] = {}
            header = payload.get("header") if isinstance(payload.get("header"), dict) else {}
            league = header.get("league") if isinstance(header.get("league"), dict) else {}
            league_slug = str(league.get("slug") or "").lower()
            league_name = str(league.get("name") or "").lower()
            hint_u = str(league_hint or "").upper()
            is_olympics_summary = hint_u == "OLYMPICS" or ("olympic" in league_slug) or ("olympic" in league_name)

            boxscore = payload.get("boxscore")
            if isinstance(boxscore, dict):
                box_teams = boxscore.get("teams")
                if isinstance(box_teams, list):
                    for bt in box_teams:
                        if not isinstance(bt, dict):
                            continue
                        team = bt.get("team") or {}
                        code = _norm_abbrev(
                            team.get("abbreviation")
                            or team.get("shortDisplayName")
                            or team.get("displayName")
                            or team.get("name")
                        , fallback="").upper()
                        if not code:
                            continue
                        tid = str(team.get("id") or bt.get("id") or "").strip()
                        if tid:
                            team_id_to_code[tid] = code
                        side = str(bt.get("homeAway") or "").strip().lower()
                        if side in {"away", "home"}:
                            side_map[side] = code
                        shots = _summary_shots_from_stats(bt.get("statistics"))
                        bucket = out.setdefault(code, {"shotsOnGoal": None, "goalScorers": []})
                        if bucket.get("shotsOnGoal") is None and shots is not None:
                            bucket["shotsOnGoal"] = shots
                box_players = boxscore.get("players")
                if isinstance(box_players, list):
                    for grp in box_players:
                        if not isinstance(grp, dict):
                            continue
                        team = grp.get("team") or {}
                        code = _norm_abbrev(
                            team.get("abbreviation")
                            or team.get("shortDisplayName")
                            or team.get("displayName")
                            or team.get("name")
                        , fallback="").upper()
                        if not code:
                            continue
                        tid = str(team.get("id") or grp.get("id") or "").strip()
                        if tid:
                            team_id_to_code[tid] = code
                        stat_groups = grp.get("statistics") if isinstance(grp.get("statistics"), list) else []
                        for stat_group in stat_groups:
                            if not isinstance(stat_group, dict):
                                continue
                            athletes = stat_group.get("athletes") if isinstance(stat_group.get("athletes"), list) else []
                            for row in athletes:
                                if not isinstance(row, dict):
                                    continue
                                ath = row.get("athlete") or {}
                                aid = str(ath.get("id") or "").strip()
                                anm = str(ath.get("displayName") or ath.get("fullName") or "").strip().lower()
                                if aid:
                                    athlete_to_code[aid] = code
                                if anm:
                                    athlete_name_to_code[anm] = code

            comp = (((payload.get("header") or {}).get("competitions") or [{}])[0] or {})
            competitors = comp.get("competitors") if isinstance(comp.get("competitors"), list) else []
            for c in competitors:
                if not isinstance(c, dict):
                    continue
                team = c.get("team") or {}
                code = _norm_abbrev(
                    team.get("abbreviation")
                    or team.get("shortDisplayName")
                    or team.get("displayName")
                    or team.get("name")
                , fallback="").upper()
                if not code:
                    continue
                tid = str(team.get("id") or c.get("id") or "").strip()
                if tid:
                    team_id_to_code[tid] = code
                side = str(c.get("homeAway") or "").strip().lower()
                if side in {"away", "home"}:
                    side_map[side] = code
                shots = _summary_shots_from_stats(c.get("statistics"))
                scorers: list[dict[str, Any]] = []
                # For Olympic summaries, prefer scoring plays (with time) over leader-name lists.
                if not is_olympics_summary:
                    leaders = c.get("leaders") if isinstance(c.get("leaders"), list) else []
                    for ldr in leaders:
                        if not isinstance(ldr, dict):
                            continue
                        if str(ldr.get("name") or "").lower() != "goals":
                            continue
                        for item in ldr.get("leaders") or []:
                            if not isinstance(item, dict):
                                continue
                            ath = item.get("athlete") or {}
                            nm = str(ath.get("displayName") or ath.get("fullName") or item.get("displayValue") or "").strip()
                            if nm:
                                scorers.append({"name": nm})
                bucket = out.setdefault(code, {"shotsOnGoal": None, "goalScorers": []})
                if bucket.get("shotsOnGoal") is None and shots is not None:
                    bucket["shotsOnGoal"] = shots
                if not isinstance(bucket.get("goalScorers"), list) or not bucket.get("goalScorers"):
                    bucket["goalScorers"] = scorers
            if side_map:
                out["__side_map__"] = {"away": side_map.get("away", ""), "home": side_map.get("home", "")}
            comp_desc = str(comp.get("description") or comp.get("shortName") or comp.get("name") or "").strip()
            header_name = str((payload.get("header") or {}).get("name") or "").strip()
            if comp_desc or header_name:
                round_src = " | ".join([x for x in (comp_desc, header_name) if x])
                meta: dict[str, Any] = {}
                stage = _olympic_round_from_text(round_src, default="")
                if stage:
                    meta["displayStage"] = stage
                div = _olympic_division_from_text(round_src, default="")
                if div in {"Men's", "Women's"}:
                    meta["olympicsDivision"] = div
                if meta:
                    out["__game_meta__"] = meta
            comp_status = (((payload.get("header") or {}).get("competitions") or [{}])[0] or {}).get("status")
            if isinstance(comp_status, dict):
                status_type = comp_status.get("type") if isinstance(comp_status.get("type"), dict) else {}
                state_raw = str((status_type or {}).get("state") or "").lower().strip()
                completed = bool((status_type or {}).get("completed"))
                game_state = "FINAL" if completed or state_raw == "post" else ("LIVE" if state_raw in {"in", "inprogress", "live"} else "FUT")
                status_text = str(
                    (status_type or {}).get("shortDetail")
                    or (status_type or {}).get("detail")
                    or (status_type or {}).get("description")
                    or comp_status.get("type", {}).get("shortDetail", "")
                ).strip()
                period_num = _to_int(comp_status.get("period"), default=-1)
                pd: dict[str, Any] = {}
                if period_num > 0:
                    pd["number"] = period_num
                display_clock = str(comp_status.get("displayClock") or "").strip()
                in_intermission = "INTERMISSION" in status_text.upper() or status_text.upper().startswith("END ")
                clock_obj: dict[str, Any] = {}
                if display_clock:
                    clock_obj["timeRemaining"] = display_clock
                if in_intermission:
                    clock_obj["inIntermission"] = True
                out["__game_status__"] = {
                    "gameState": game_state,
                    "statusText": status_text,
                    "periodDescriptor": pd,
                    "clock": clock_obj,
                }

            scoring_plays = payload.get("scoringPlays")
            if not isinstance(scoring_plays, list):
                scoring_plays = payload.get("plays")
            if isinstance(scoring_plays, list):
                for play in scoring_plays:
                    if not isinstance(play, dict):
                        continue
                    if not bool(play.get("scoringPlay")):
                        continue
                    team = play.get("team") or {}
                    code = _norm_abbrev(
                        team.get("abbreviation")
                        or team.get("shortDisplayName")
                        or team.get("displayName")
                        or team.get("name")
                    , fallback="").upper()
                    if not code:
                        team_id = str(team.get("id") or "").strip()
                        if team_id:
                            code = team_id_to_code.get(team_id, "")
                    if not code:
                        side = str(play.get("homeAway") or "").strip().lower()
                        side_ref = out.get("__side_map__") if isinstance(out.get("__side_map__"), dict) else {}
                        if side in {"away", "home"}:
                            code = str((side_ref or {}).get(side) or "").upper()
                    scorer_name = ""
                    scorer_id = ""
                    assists: list[str] = []
                    parts = play.get("participants")
                    if isinstance(parts, list):
                        for p in parts:
                            if not isinstance(p, dict):
                                continue
                            ptype = str(p.get("type") or "").strip().lower()
                            pat = p.get("athlete") or {}
                            pid = str(pat.get("id") or "").strip()
                            nm = str(
                                pat.get("displayName")
                                or pat.get("fullName")
                                or p.get("displayName")
                                or ""
                            ).strip()
                            if ptype == "scorer" and nm and not scorer_name:
                                scorer_name = nm
                                scorer_id = pid
                            elif ptype == "assister" and nm:
                                assists.append(nm)
                    if not scorer_name:
                        ath = play.get("athlete")
                        if isinstance(ath, dict):
                            scorer_name = str(ath.get("displayName") or ath.get("fullName") or "").strip()
                            scorer_id = str(ath.get("id") or "").strip()
                    if not code and scorer_id:
                        code = athlete_to_code.get(scorer_id, "")
                    if not code and scorer_name:
                        code = athlete_name_to_code.get(str(scorer_name).strip().lower(), "")
                    if not code:
                        continue
                    bucket = out.setdefault(code, {"shotsOnGoal": None, "goalScorers": []})
                    if scorer_name:
                        goals = bucket.get("goalScorers")
                        if not isinstance(goals, list):
                            goals = []
                            bucket["goalScorers"] = goals
                        goal_time = ""
                        clk = play.get("clock")
                        if isinstance(clk, dict):
                            for k in ("displayValue", "shortDisplayValue", "value", "time"):
                                v = clk.get(k)
                                if isinstance(v, str) and v.strip():
                                    goal_time = v.strip()
                                    break
                        pd: dict[str, Any] = {}
                        period = play.get("period")
                        if isinstance(period, dict):
                            pnum = _to_int(period.get("number"), default=-1)
                            if pnum > 0:
                                pd["number"] = pnum
                            ptype = str(period.get("type") or period.get("abbreviation") or "").upper().strip()
                            if ptype in {"OT", "SO"}:
                                pd["periodType"] = ptype
                        entry: dict[str, Any] = {"name": scorer_name}
                        if pd:
                            entry["periodDescriptor"] = pd
                        if goal_time:
                            entry["timeRemaining"] = goal_time
                        if assists:
                            entry["assists"] = assists
                        key_now = (
                            str(entry.get("name") or "").strip(),
                            str(entry.get("timeRemaining") or "").strip(),
                            str((entry.get("periodDescriptor") or {}).get("number") if isinstance(entry.get("periodDescriptor"), dict) else ""),
                            str((entry.get("periodDescriptor") or {}).get("periodType") if isinstance(entry.get("periodDescriptor"), dict) else ""),
                        )
                        existing = set()
                        for x in goals:
                            if not isinstance(x, dict):
                                continue
                            existing.add(
                                (
                                    str(x.get("name") or "").strip(),
                                    str(x.get("timeRemaining") or "").strip(),
                                    str((x.get("periodDescriptor") or {}).get("number") if isinstance(x.get("periodDescriptor"), dict) else ""),
                                    str((x.get("periodDescriptor") or {}).get("periodType") if isinstance(x.get("periodDescriptor"), dict) else ""),
                                )
                            )
                        if key_now not in existing:
                            goals.append(entry)
            return out

        def _summary_league_candidates(game: dict[str, Any], league_hint: str) -> list[str]:
            hint = str(league_hint or "").upper().strip()
            cands: list[str]
            if hint == "PWHL":
                cands = [
                    "pwhl",
                    "pro-womens-hockey-league",
                    "professional-womens-hockey-league",
                ]
                cands.extend(
                    _pick_league_codes_from_discovery(
                        discovered,
                        include_words=("pwhl", "women", "womens"),
                    )
                )
            else:
                cands = [
                    "olympics-womens-ice-hockey",
                    "olympic-womens-hockey",
                    "olympics-womens-hockey",
                    "womens-olympics-hockey",
                    "olympics",
                    "olympics-hockey",
                    "olympic-hockey",
                    "mens-olympics-hockey",
                    "olympics-mens-hockey",
                    "olympic-mens-hockey",
                    "men-olympics",
                    "olympics-men",
                    "women-olympic-hockey",
                    "womens-olympic-hockey",
                    "olympics-women",
                    "women-olympics",
                ]
                cands.extend(
                    _pick_league_codes_from_discovery(
                        discovered,
                        include_words=("olympic",),
                        exclude_words=("field hockey",),
                    )
                )
            return list(dict.fromkeys([str(x).strip() for x in cands if str(x).strip()]))

        def _get_summary_payload(event_id: int, league_codes: list[str]) -> dict[str, Any]:
            if espn is None or event_id <= 0:
                return {}
            def _summary_has_timed_scoring(payload: Any) -> bool:
                if not isinstance(payload, dict):
                    return False
                plays = payload.get("scoringPlays")
                if not isinstance(plays, list):
                    plays = payload.get("plays")
                if not isinstance(plays, list):
                    return False
                for p in plays:
                    if not isinstance(p, dict) or not bool(p.get("scoringPlay")):
                        continue
                    clk = p.get("clock")
                    if isinstance(clk, dict):
                        for k in ("displayValue", "shortDisplayValue", "value", "time"):
                            v = clk.get(k)
                            if isinstance(v, str) and v.strip():
                                return True
                return False

            today_live = allow_network and d == today
            live_league_codes = league_codes[:8] if today_live else league_codes
            if today_live:
                # For today's live games, prefer fresh summary over stale cache.
                base = str(getattr(espn, "base_url", "https://site.api.espn.com/apis/site/v2")).rstrip("/")
                headers = cast(dict[str, str], getattr(espn, "headers", {}))
                timeout_s = int(getattr(espn, "timeout_s", 20))
                timeout_s = min(timeout_s, 6)
                best_raw: dict[str, Any] = {}
                for league_code in live_league_codes:
                    try:
                        url = f"{base}/sports/hockey/{league_code}/summary?event={int(event_id)}"
                        r = requests.get(url, headers=headers, timeout=timeout_s)
                        r.raise_for_status()
                        raw = r.json()
                        if isinstance(raw, dict) and raw:
                            espn.cache.set_json(_summary_key(league_code, event_id), raw)  # type: ignore[attr-defined]
                            if _summary_has_timed_scoring(raw):
                                return raw
                            if not best_raw:
                                best_raw = raw
                    except Exception:
                        continue
                try:
                    url = f"{base}/sports/hockey/summary?event={int(event_id)}"
                    r = requests.get(url, headers=headers, timeout=timeout_s)
                    r.raise_for_status()
                    raw = r.json()
                    if isinstance(raw, dict) and raw:
                        espn.cache.set_json(_summary_key("summary", event_id), raw)  # type: ignore[attr-defined]
                        if _summary_has_timed_scoring(raw):
                            return raw
                        if not best_raw:
                            best_raw = raw
                except Exception:
                    pass
                if best_raw:
                    return best_raw
            best_cached: dict[str, Any] = {}
            for league_code in live_league_codes:
                key = _summary_key(league_code, event_id)
                try:
                    ttl = int(getattr(espn, "live_ttl_s", 120)) if today_live else None
                    cached = espn.cache.get_json(key, ttl_s=ttl)  # type: ignore[attr-defined]
                    if isinstance(cached, dict) and cached:
                        if _summary_has_timed_scoring(cached):
                            return cached
                        if not best_cached:
                            best_cached = cached
                except Exception:
                    pass
            if best_cached:
                return best_cached
            if not allow_network:
                return {}
            base = str(getattr(espn, "base_url", "https://site.api.espn.com/apis/site/v2")).rstrip("/")
            headers = cast(dict[str, str], getattr(espn, "headers", {}))
            timeout_s = int(getattr(espn, "timeout_s", 20))
            timeout_s = min(timeout_s, 8)
            best_raw: dict[str, Any] = {}
            for league_code in live_league_codes:
                try:
                    url = f"{base}/sports/hockey/{league_code}/summary?event={int(event_id)}"
                    r = requests.get(url, headers=headers, timeout=timeout_s)
                    r.raise_for_status()
                    raw = r.json()
                    if isinstance(raw, dict) and raw:
                        espn.cache.set_json(_summary_key(league_code, event_id), raw)  # type: ignore[attr-defined]
                        if _summary_has_timed_scoring(raw):
                            return raw
                        if not best_raw:
                            best_raw = raw
                except Exception:
                    continue
            # Generic fallback endpoint (some Olympic feeds resolve here).
            try:
                url = f"{base}/sports/hockey/summary?event={int(event_id)}"
                r = requests.get(url, headers=headers, timeout=timeout_s)
                r.raise_for_status()
                raw = r.json()
                if isinstance(raw, dict) and raw:
                    espn.cache.set_json(_summary_key("summary", event_id), raw)  # type: ignore[attr-defined]
                    if _summary_has_timed_scoring(raw):
                        return raw
                    if not best_raw:
                        best_raw = raw
            except Exception:
                pass
            return best_raw

        def _enrich_games_with_summaries(games: list[dict[str, Any]], *, league_hint: str) -> list[dict[str, Any]]:
            out_games: list[dict[str, Any]] = []
            def _base_code(raw: str) -> str:
                t = re.sub(r"[^A-Z]", "", str(raw or "").upper())
                return t[:3] if len(t) > 3 else t
            def _has_timed_rows(rows: Any) -> bool:
                if not isinstance(rows, list):
                    return False
                for r in rows:
                    if not isinstance(r, dict):
                        continue
                    if str(r.get("timeRemaining") or "").strip():
                        return True
                    pd = r.get("periodDescriptor")
                    if isinstance(pd, dict) and (pd.get("number") is not None or str(pd.get("periodType") or "").strip()):
                        return True
                return False
            def _timed_rows_from_summary_for_game(summary: dict[str, Any], away_code: str, home_code: str) -> dict[str, list[dict[str, Any]]]:
                out_rows: dict[str, list[dict[str, Any]]] = {away_code: [], home_code: []}
                team_id_to_code: dict[str, str] = {}
                comp = (((summary.get("header") or {}).get("competitions") or [{}])[0] or {})
                for c in (comp.get("competitors") or []):
                    if not isinstance(c, dict):
                        continue
                    team = c.get("team") or {}
                    code = _norm_abbrev(
                        team.get("abbreviation")
                        or team.get("shortDisplayName")
                        or team.get("displayName")
                        or team.get("name")
                    , fallback="").upper()
                    tid = str(team.get("id") or c.get("id") or "").strip()
                    if code and tid:
                        team_id_to_code[tid] = code
                plays = summary.get("scoringPlays")
                if not isinstance(plays, list):
                    plays = summary.get("plays")
                if not isinstance(plays, list):
                    return out_rows
                for play in plays:
                    if not isinstance(play, dict) or not bool(play.get("scoringPlay")):
                        continue
                    team = play.get("team") or {}
                    code = _norm_abbrev(
                        team.get("abbreviation")
                        or team.get("shortDisplayName")
                        or team.get("displayName")
                        or team.get("name")
                    , fallback="").upper()
                    if not code:
                        tid = str(team.get("id") or "").strip()
                        if tid:
                            code = team_id_to_code.get(tid, "")
                    if code not in out_rows:
                        continue
                    scorer_name = ""
                    for p in (play.get("participants") or []):
                        if not isinstance(p, dict):
                            continue
                        if str(p.get("type") or "").strip().lower() != "scorer":
                            continue
                        ath = p.get("athlete") or {}
                        scorer_name = str(ath.get("displayName") or ath.get("fullName") or p.get("displayName") or "").strip()
                        if scorer_name:
                            break
                    if not scorer_name:
                        ath = play.get("athlete")
                        if isinstance(ath, dict):
                            scorer_name = str(ath.get("displayName") or ath.get("fullName") or "").strip()
                    if not scorer_name:
                        continue
                    goal_time = ""
                    clk = play.get("clock")
                    if isinstance(clk, dict):
                        for k in ("displayValue", "shortDisplayValue", "value", "time"):
                            v = clk.get(k)
                            if isinstance(v, str) and v.strip():
                                goal_time = v.strip()
                                break
                    pd: dict[str, Any] = {}
                    period = play.get("period")
                    if isinstance(period, dict):
                        pnum = _to_int(period.get("number"), default=-1)
                        if pnum > 0:
                            pd["number"] = pnum
                        ptype = str(period.get("type") or period.get("abbreviation") or "").upper().strip()
                        if ptype in {"OT", "SO"}:
                            pd["periodType"] = ptype
                    row: dict[str, Any] = {"name": scorer_name}
                    if goal_time:
                        row["timeRemaining"] = goal_time
                    if pd:
                        row["periodDescriptor"] = pd
                    out_rows[code].append(row)
                return out_rows
            for g in games:
                if not isinstance(g, dict):
                    continue
                gg = dict(g)
                gid = _to_int(gg.get("id"), default=0)
                if gid <= 0:
                    out_games.append(gg)
                    continue
                summary = _get_summary_payload(gid, _summary_league_candidates(gg, league_hint))
                enrich = _parse_summary_enrichment(summary, league_hint=league_hint) if isinstance(summary, dict) else {}
                side_ref = enrich.get("__side_map__") if isinstance(enrich.get("__side_map__"), dict) else {}
                status_ref = enrich.get("__game_status__") if isinstance(enrich.get("__game_status__"), dict) else {}
                meta_ref = enrich.get("__game_meta__") if isinstance(enrich.get("__game_meta__"), dict) else {}
                if status_ref:
                    st = str(status_ref.get("gameState") or "").upper().strip()
                    if st:
                        gg["gameState"] = st
                    stxt = str(status_ref.get("statusText") or "").strip()
                    if stxt:
                        gg["statusText"] = stxt
                    pd = status_ref.get("periodDescriptor")
                    if isinstance(pd, dict) and pd:
                        gg["periodDescriptor"] = pd
                    cobj = status_ref.get("clock")
                    if isinstance(cobj, dict) and cobj:
                        gg["clock"] = cobj
                if meta_ref:
                    if not str(gg.get("displayStage") or "").strip():
                        stg = str(meta_ref.get("displayStage") or "").strip()
                        if stg:
                            gg["displayStage"] = stg
                    if not str(gg.get("olympicsDivision") or "").strip():
                        divv = str(meta_ref.get("olympicsDivision") or "").strip()
                        if divv in {"Men's", "Women's"}:
                            gg["olympicsDivision"] = divv
                away_code = str(((gg.get("awayTeam") or {}).get("abbrev") or "").upper())
                home_code = str(((gg.get("homeTeam") or {}).get("abbrev") or "").upper())
                timed_rows_by_code = (
                    _timed_rows_from_summary_for_game(summary, away_code, home_code)
                    if isinstance(summary, dict) and away_code and home_code
                    else {}
                )
                for side_key in ("awayTeam", "homeTeam"):
                    team = gg.get(side_key) if isinstance(gg.get(side_key), dict) else None
                    if not isinstance(team, dict):
                        continue
                    code = str(team.get("abbrev") or team.get("abbreviation") or team.get("teamAbbrev") or "").upper()
                    if not code:
                        continue
                    src = enrich.get(code)
                    if not isinstance(src, dict):
                        src = enrich.get(_base_code(code))
                    if not isinstance(src, dict):
                        side = "away" if side_key == "awayTeam" else "home"
                        side_code = str((side_ref or {}).get(side) or "").upper()
                        if side_code:
                            src = enrich.get(side_code) or enrich.get(_base_code(side_code))
                            # For future Olympic cards, scoreboard often keeps TBD while
                            # summary already knows the matchup. Promote resolved code.
                            if code in {"", "TBD"} and side_code not in {"", "TBD"}:
                                team["abbrev"] = side_code
                                team["abbreviation"] = side_code
                                team["teamAbbrev"] = side_code
                    if not isinstance(src, dict):
                        continue
                    if src.get("shotsOnGoal") is not None:
                        team["shotsOnGoal"] = src.get("shotsOnGoal")
                    src_goals = src.get("goalScorers")
                    cur_goals = team.get("goalScorers")
                    if isinstance(src_goals, list) and src_goals:
                        if _has_timed_rows(src_goals) or not isinstance(cur_goals, list) or not cur_goals:
                            team["goalScorers"] = src_goals
                    timed_rows = timed_rows_by_code.get(code) if isinstance(timed_rows_by_code, dict) else None
                    if isinstance(timed_rows, list) and timed_rows:
                        if _has_timed_rows(timed_rows) and (not isinstance(team.get("goalScorers"), list) or not _has_timed_rows(team.get("goalScorers"))):
                            team["goalScorers"] = timed_rows
                out_games.append(gg)
            return out_games

        def _ext_day_key() -> str:
            return f"external/hockey/day/{d.strftime('%Y%m%d')}"

        def _read_merged_day_cache() -> tuple[list[dict[str, Any]], list[dict[str, Any]], Optional[float]]:
            if espn is None:
                return [], [], None
            try:
                payload, ts = espn.cache.get_json_with_meta(_ext_day_key(), ttl_s=None)  # type: ignore[attr-defined]
                if isinstance(payload, dict):
                    o = payload.get("olympics") or []
                    p = payload.get("pwhl") or []
                    if isinstance(o, list) and isinstance(p, list):
                        oo = [x for x in o if isinstance(x, dict)]
                        pp = [x for x in p if isinstance(x, dict)]
                        if oo or pp:
                            return oo, pp, ts
            except Exception:
                pass
            return [], [], None

        def _write_merged_day_cache(olympics: list[dict[str, Any]], pwhl: list[dict[str, Any]]) -> None:
            if espn is None:
                return
            try:
                espn.cache.set_json(_ext_day_key(), {"olympics": olympics, "pwhl": pwhl})  # type: ignore[attr-defined]
            except Exception:
                pass

        def _espn_cache_stamp() -> str:
            if espn is None:
                return day_external_stamp.get(d, f"Updated: {_fmt_updated_ts()}")
            merged_o, merged_p, merged_ts = _read_merged_day_cache()
            if (merged_o or merged_p) and isinstance(merged_ts, (int, float)) and merged_ts > 0:
                return f"Updated: {_fmt_updated_from_unix(float(merged_ts))}"
            cands: list[float] = []
            dstr = d.strftime("%Y%m%d")
            keys = [
                f"espn/hockey/all/scoreboard/{dstr}",
                f"espn/hockey/olympics/scoreboard/{dstr}",
                f"espn/hockey/olympics-hockey/scoreboard/{dstr}",
                f"espn/hockey/olympic-hockey/scoreboard/{dstr}",
                f"espn/hockey/olympic-womens-hockey/scoreboard/{dstr}",
                f"espn/hockey/olympics-womens-hockey/scoreboard/{dstr}",
                f"espn/hockey/womens-olympics-hockey/scoreboard/{dstr}",
                f"espn/hockey/olympics-womens-ice-hockey/scoreboard/{dstr}",
                f"espn/hockey/women-olympic-hockey/scoreboard/{dstr}",
                f"espn/hockey/womens-olympic-hockey/scoreboard/{dstr}",
                f"espn/hockey/olympics-women/scoreboard/{dstr}",
                f"espn/hockey/women-olympics/scoreboard/{dstr}",
                f"espn/hockey/pwhl/scoreboard/{dstr}",
                f"espn/hockey/pro-womens-hockey-league/scoreboard/{dstr}",
                f"espn/hockey/professional-womens-hockey-league/scoreboard/{dstr}",
            ]
            try:
                for key in keys:
                    _cached, ts = espn.cache.get_json_with_meta(key, ttl_s=None)  # type: ignore[attr-defined]
                    if isinstance(ts, (int, float)) and ts > 0:
                        cands.append(float(ts))
            except Exception:
                pass
            if cands:
                return f"Updated: {_fmt_updated_from_unix(max(cands))}"
            return day_external_stamp.get(d, f"Updated: {_fmt_updated_ts()}")

        prev_cached = day_external_cache.get(d)
        if prev_cached is not None and not allow_network:
            cached_o = _enrich_games_with_summaries(list(prev_cached[0]), league_hint="OLYMPICS")
            cached_p = _enrich_games_with_summaries(list(prev_cached[1]), league_hint="PWHL")
            day_external_cache[d] = (cached_o, cached_p)
            stamp = day_external_stamp.get(d) or _espn_cache_stamp()
            return cached_o, cached_p, stamp
        if d in day_external_empty_checked and not allow_network:
            return [], [], day_external_stamp.get(d) or _espn_cache_stamp()
        merged_o, merged_p, merged_ts = _read_merged_day_cache()
        if (merged_o or merged_p) and not allow_network:
            merged_o = _enrich_games_with_summaries(list(merged_o), league_hint="OLYMPICS")
            merged_p = _enrich_games_with_summaries(list(merged_p), league_hint="PWHL")
            day_external_cache[d] = (merged_o, merged_p)
            stamp = day_external_stamp.get(d) or (
                f"Updated: {_fmt_updated_from_unix(float(merged_ts))}"
                if isinstance(merged_ts, (int, float)) and merged_ts > 0
                else _espn_cache_stamp()
            )
            return merged_o, merged_p, stamp
        if not allow_network:
            # Strict cache-only fast path:
            # if nothing is in merged/day memory cache, do not scan many league keys.
            # This keeps Olympic date flips as fast as NHL-only dates.
            # But recover from cached ESPN scoreboards when available so "today"
            # does not show empty after a failed/partial merged-day write.
            if espn is not None:
                recovered_o: list[dict[str, Any]] = []
                recovered_p: list[dict[str, Any]] = []
                recovery_leagues: list[tuple[str, str, bool]] = [
                    ("hockey", "olympics-womens-ice-hockey", True),
                    ("hockey", "olympics-womens-hockey", True),
                    ("hockey", "olympics", True),
                    ("hockey", "pwhl", False),
                ]
                for sport, league_code, is_olympics in recovery_leagues:
                    try:
                        payload = espn.scoreboard(  # type: ignore[attr-defined]
                            sport,
                            league_code,
                            d,
                            allow_network=False,
                            force_network=False,
                        )
                    except Exception:
                        payload = {}
                    if not isinstance(payload, dict) or not payload.get("events"):
                        continue
                    conv = _convert_espn_events(
                        payload,
                        league_label="Olympics" if is_olympics else "PWHL",
                        include_round_text=is_olympics,
                    )
                    if conv:
                        if is_olympics:
                            recovered_o.extend(conv)
                        else:
                            recovered_p.extend(conv)
                if recovered_o or recovered_p:
                    ro = _enrich_games_with_summaries(_dedupe_games(recovered_o), league_hint="OLYMPICS") if recovered_o else []
                    rp = _enrich_games_with_summaries(_dedupe_games(recovered_p), league_hint="PWHL") if recovered_p else []
                    day_external_cache[d] = (ro, rp)
                    stamp = day_external_stamp.get(d) or _espn_cache_stamp()
                    day_external_stamp[d] = stamp
                    return ro, rp, stamp
            stamp = day_external_stamp.get(d) or f"Updated: {_fmt_updated_ts()}"
            day_external_stamp[d] = stamp
            day_external_empty_checked.add(d)
            return [], [], stamp
        if d != today and prev_cached is not None and not allow_network:
            stamp = day_external_stamp.get(d) or _espn_cache_stamp()
            return prev_cached[0], prev_cached[1], stamp
        olympics: list[dict[str, Any]] = []
        pwhl: list[dict[str, Any]] = []
        if espn is None:
            if prev_cached is not None:
                stamp = day_external_stamp.get(d, f"Updated: {_fmt_updated_ts()}")
                return prev_cached[0], prev_cached[1], stamp
            return olympics, pwhl, day_external_stamp.get(d, f"Updated: {_fmt_updated_ts()}")

        # First try "all hockey" board; this is often more stable than guessed league slugs.
        try:
            all_payload = espn.scoreboard_all_hockey(
                d, allow_network=allow_network, force_network=force_network
            )
            o2, p2 = _split_all_hockey_espn_events(all_payload if isinstance(all_payload, dict) else {})
            olympics.extend(o2)
            pwhl.extend(p2)
        except Exception:
            pass

        if allow_network:
            try:
                discover_fn = getattr(espn, "discover_hockey_leagues", None)
                if callable(discover_fn):
                    raw_discovered = discover_fn() or []
                    if isinstance(raw_discovered, list):
                        discovered = [cast(dict[str, str], x) for x in raw_discovered if isinstance(x, dict)]
            except Exception:
                discovered = []

        olympics_candidates = [
            "olympics",
            "olympics-hockey",
            "olympic-hockey",
            "mens-olympics-hockey",
            "olympics-mens-hockey",
            "olympic-mens-hockey",
            "men-olympics",
            "olympics-men",
            "olympic-womens-hockey",
            "olympics-womens-hockey",
            "womens-olympics-hockey",
            "olympics-womens-ice-hockey",
            "women-olympic-hockey",
            "womens-olympic-hockey",
            "olympics-women",
            "women-olympics",
        ]
        olympics_candidates.extend(
            _pick_league_codes_from_discovery(
                discovered,
                include_words=("olympic",),
                exclude_words=("field hockey",),
            )
        )
        olympics_candidates = list(dict.fromkeys(olympics_candidates))
        olympics_probe = olympics_candidates
        if allow_network and (olympics or d == today):
            # Keep Olympic probing tight for live days; all-hockey already covers most cases.
            olympics_probe = olympics_candidates[:4]

        # Olympics: always run explicit league candidates and merge with all-hockey
        # so partial all-hockey payloads cannot hide other games on the same date.
        for league_code in olympics_probe:
            try:
                payload = espn.scoreboard(
                    "hockey",
                    league_code,
                    d,
                    allow_network=allow_network,
                    force_network=force_network,
                )
            except Exception:
                continue
            got = _convert_espn_events(payload, league_label="Olympics", include_round_text=True)
            if got:
                olympics.extend(got)
                if d == today:
                    break

        pwhl_candidates = [
            "pwhl",
            "pro-womens-hockey-league",
            "professional-womens-hockey-league",
        ]
        pwhl_candidates.extend(
            _pick_league_codes_from_discovery(
                discovered,
                include_words=("pwhl", "women", "womens"),
            )
        )
        pwhl_candidates = list(dict.fromkeys(pwhl_candidates))

        if not pwhl:
            for league_code in pwhl_candidates:
                try:
                    payload = espn.scoreboard(
                        "hockey",
                        league_code,
                        d,
                        allow_network=allow_network,
                        force_network=force_network,
                    )
                except Exception:
                    continue
                got = _convert_espn_events(payload, league_label="PWHL", include_round_text=False)
                if got:
                    pwhl.extend(got)
                    break

        # Fallback: if live scoreboard probing yields no Olympics rows, keep the
        # known game list and force-refresh by per-event summary.
        if allow_network and not olympics:
            seed_o: list[dict[str, Any]] = []
            if prev_cached is not None and isinstance(prev_cached, tuple) and prev_cached:
                pc0 = prev_cached[0] if len(prev_cached) >= 1 else []
                if isinstance(pc0, list):
                    seed_o.extend([x for x in pc0 if isinstance(x, dict)])
            if not seed_o:
                mo, _mp, _mts = _read_merged_day_cache()
                if isinstance(mo, list):
                    seed_o.extend([x for x in mo if isinstance(x, dict)])
            if seed_o:
                olympics = _enrich_games_with_summaries(_dedupe_games(seed_o), league_hint="OLYMPICS")

        if olympics:
            olympics = _enrich_games_with_summaries(olympics, league_hint="OLYMPICS")
        if pwhl:
            pwhl = _enrich_games_with_summaries(pwhl, league_hint="PWHL")

        out = (_dedupe_games(olympics), _dedupe_games(pwhl))
        if not out[0] and not out[1] and prev_cached is not None:
            # Never replace good cached data with an empty transient response.
            stamp = day_external_stamp.get(d) or _espn_cache_stamp()
            return prev_cached[0], prev_cached[1], stamp
        stamp = day_external_stamp.get(d) or _espn_cache_stamp()
        if allow_network:
            stamp = _espn_cache_stamp()
            day_external_stamp[d] = stamp
        if out[0] or out[1]:
            # Keep today's external result in memory too, so we don't repeatedly
            # re-seed from network while browsing the same date.
            day_external_cache[d] = out
            _write_merged_day_cache(out[0], out[1])
            day_external_empty_checked.discard(d)
            if d not in day_external_stamp:
                day_external_stamp[d] = stamp
        elif not allow_network:
            day_external_empty_checked.add(d)
        return out[0], out[1], stamp

    def _fetch_pwhl_games(
        d: dt.date,
        *,
        allow_network: bool,
        force_network: bool = False,
    ) -> tuple[list[dict[str, Any]], str]:
        mem = day_pwhl_cache.get(d)
        prev_mem = [g for g in mem] if isinstance(mem, list) else []
        if mem is not None and not allow_network:
            return mem, day_pwhl_stamp.get(d, f"Updated: {_fmt_updated_ts()}")
        prev_external = day_external_cache.get(d, ([], []))[1]
        prev_cached = prev_mem if prev_mem else prev_external
        def _pwhl_cache_stamp() -> str:
            if pwhl_api is None:
                return day_pwhl_stamp.get(d, f"Updated: {_fmt_updated_ts()}")
            try:
                fnm = getattr(pwhl_api, "get_games_for_date_with_meta", None)
                if callable(fnm):
                    result = fnm(d, allow_network=False, force_network=False)
                    if (
                        isinstance(result, tuple)
                        and len(result) >= 2
                        and isinstance(result[1], (int, float))
                        and float(result[1]) > 0
                    ):
                        return f"Updated: {_fmt_updated_from_unix(float(result[1]))}"
            except Exception:
                pass
            return day_pwhl_stamp.get(d, f"Updated: {_fmt_updated_ts()}")

        if pwhl_api is None:
            if prev_cached:
                day_pwhl_cache[d] = prev_cached
                return prev_cached, day_pwhl_stamp.get(d, f"Updated: {_fmt_updated_ts()}")
            day_pwhl_cache[d] = []
            return [], day_pwhl_stamp.get(d, f"Updated: {_fmt_updated_ts()}")
        try:
            fn_with_meta = getattr(pwhl_api, "get_games_for_date_with_meta", None)
            fn = getattr(pwhl_api, "get_games_for_date", None)
            data: Any
            ts: Optional[float] = None
            if callable(fn_with_meta):
                result = fn_with_meta(d, allow_network=allow_network, force_network=force_network)
                if isinstance(result, tuple) and len(result) >= 1:
                    data = result[0]
                    ts_raw = result[1] if len(result) >= 2 else None
                    ts = float(ts_raw) if isinstance(ts_raw, (int, float)) else None
                else:
                    data = []
            elif callable(fn):
                data = fn(d, allow_network=allow_network, force_network=force_network)
            else:
                if prev_cached:
                    day_pwhl_cache[d] = prev_cached
                    return prev_cached, day_pwhl_stamp.get(d, f"Updated: {_fmt_updated_ts()}")
                day_pwhl_cache[d] = []
                return [], day_pwhl_stamp.get(d, f"Updated: {_fmt_updated_ts()}")
            if not isinstance(data, list):
                if prev_cached:
                    day_pwhl_cache[d] = prev_cached
                    return prev_cached, day_pwhl_stamp.get(d, f"Updated: {_fmt_updated_ts()}")
                day_pwhl_cache[d] = []
                return [], day_pwhl_stamp.get(d, f"Updated: {_fmt_updated_ts()}")
            out = _dedupe_games([g for g in data if isinstance(g, dict)])
            if not out and prev_cached:
                day_pwhl_cache[d] = prev_cached
                return prev_cached, day_pwhl_stamp.get(d, f"Updated: {_fmt_updated_ts()}")
            stamp = day_pwhl_stamp.get(d) or _pwhl_cache_stamp()
            if allow_network:
                if isinstance(ts, (int, float)) and ts > 0:
                    stamp = f"Updated: {_fmt_updated_from_unix(float(ts))}"
                else:
                    stamp = _pwhl_cache_stamp()
                day_pwhl_stamp[d] = stamp
            day_pwhl_cache[d] = out
            if d not in day_pwhl_stamp:
                day_pwhl_stamp[d] = stamp
            return out, stamp
        except Exception:
            if prev_cached:
                day_pwhl_cache[d] = prev_cached
                return prev_cached, day_pwhl_stamp.get(d, f"Updated: {_fmt_updated_ts()}")
            day_pwhl_cache[d] = []
            return [], day_pwhl_stamp.get(d, f"Updated: {_fmt_updated_ts()}")

    def _render_day(force_rebuild: bool = False) -> None:
        nonlocal cards, refresh_after_id, last_rendered_date, auto_refresh_has_active_games

        d = _selected_date()
        # Track date changes for layout/state transitions.
        if d != last_rendered_date:
            last_rendered_date = d
        date_lbl.configure(text=_fmt_big_date(d))

        # XML fast-path fallback (used only when API/cache yields no rows).
        xml_games = read_games_day_xml(season=season, day=d) if season else []

        # Cache-only render path; API calls are manual via Refresh button.
        raw, err_msg, nhl_stamp = _get_score_payload(d, prefer_cached=True, allow_network=False)
        raw = _apply_schedule_start_overrides(d, raw, allow_network=False)
        nhl_games = list(raw.get("games") or [])
        _remember_game_win_probs([g for g in nhl_games if isinstance(g, dict)])

        # NHL feed may include Olympics; if we can load Olympics from ESPN, prefer that source.
        nhl_olympic = [g for g in nhl_games if _is_olympic_game(g)]
        nhl_regular = [g for g in nhl_games if not _is_olympic_game(g)]
        for g in nhl_regular:
            g["league"] = "NHL"
            g["_fetched_at"] = nhl_stamp

        # External refresh policy:
        # - today: refresh only if cached games include started + non-final
        # - non-today: cache-first, with one network seed when missing
        ext_cached_olympics, ext_cached_pwhl, ext_cached_stamp = _fetch_espn_games(d, allow_network=False)
        olympics_ext, pwhl_ext, ext_stamp = ext_cached_olympics, ext_cached_pwhl, ext_cached_stamp

        pwhl_cached, pwhl_cached_stamp = _fetch_pwhl_games(d, allow_network=False)
        pwhl_direct, pwhl_stamp = _fetch_pwhl_games(d, allow_network=False)
        if not pwhl_direct:
            pwhl_direct = pwhl_cached
            pwhl_stamp = pwhl_cached_stamp
        # Combine ESPN/PWHL variants for same game id so card logic is uniform
        # across leagues even when one source omits shots/scorer details.
        if pwhl_ext and pwhl_direct:
            pwhl_ext = _merge_games_by_id(pwhl_ext, pwhl_direct)
            pwhl_direct = _merge_games_by_id(pwhl_direct, pwhl_ext)
        # Merge ESPN + NHL-fallback Olympics so partial external payloads do not
        # suppress games already present in NHL feed for this date.
        if olympics_ext and nhl_olympic:
            olympics_ext = _merge_games_by_id(olympics_ext, nhl_olympic)
        olympics_games = _dedupe_games((olympics_ext or []) + nhl_olympic)
        def _seed_known_olympic_mens_qf_homes(games_in: list[dict[str, Any]]) -> None:
            # Generic fallback for unresolved Olympic men's quarterfinal cards:
            # when feeds still return TBD on both sides, seed known home teams
            # by bracket slot order so cards stop rendering TBD@TBD.
            candidates: list[tuple[dt.datetime, dict[str, Any]]] = []
            for gg in games_in:
                if not isinstance(gg, dict) or not _is_olympic_game(gg):
                    continue
                stage_txt = str(gg.get("displayStage") or _game_middle_label(gg, d) or "").lower()
                if "quarter" not in stage_txt and "quarters" not in stage_txt:
                    continue
                start_local = _parse_start_local(gg, tz)
                if start_local is None:
                    continue
                candidates.append((start_local, gg))
            if len(candidates) < 4:
                return
            candidates.sort(key=lambda x: x[0])
            known_home_codes = ["SVK", "CAN", "FIN", "USA"]
            for idx, (_st, gg) in enumerate(candidates[:4]):
                home = gg.get("homeTeam") if isinstance(gg.get("homeTeam"), dict) else None
                if not isinstance(home, dict):
                    continue
                cur = str(home.get("abbrev") or home.get("abbreviation") or home.get("teamAbbrev") or "").upper()
                if cur and cur != "TBD":
                    continue
                code = known_home_codes[idx]
                home["abbrev"] = code
                home["abbreviation"] = code
                home["teamAbbrev"] = code
                # Keep a simple display name so hover/details have non-empty text.
                home_name_map = {
                    "SVK": "Slovakia",
                    "CAN": "Canada",
                    "FIN": "Finland",
                    "USA": "United States",
                }
                hname = home_name_map.get(code, code)
                nm = home.get("name")
                if isinstance(nm, dict):
                    if not str(nm.get("default") or "").strip():
                        nm["default"] = hname
                elif nm in (None, "", {}):
                    home["name"] = {"default": hname}
        _seed_known_olympic_mens_qf_homes(olympics_games)
        for g in olympics_games:
            g["league"] = "Olympics"
            if not str(g.get("displayStage") or "").strip():
                g["displayStage"] = _game_middle_label(g, d)
            if g in (olympics_ext or []):
                g["_fetched_at"] = ext_stamp
            else:
                g["_fetched_at"] = nhl_stamp

        for g in pwhl_ext:
            g["_fetched_at"] = ext_stamp
        for g in pwhl_direct:
            g["_fetched_at"] = pwhl_stamp

        all_games: list[dict[str, Any]] = []
        all_games.extend(nhl_regular)
        all_games.extend(olympics_games)
        all_games.extend(pwhl_ext)
        all_games.extend(pwhl_direct)
        _remember_game_win_probs([g for g in all_games if isinstance(g, dict)])
        if not all_games and xml_games:
            all_games = _dedupe_games([g for g in xml_games if isinstance(g, dict)])
            for g in all_games:
                if not str(g.get("_fetched_at") or "").strip():
                    g["_fetched_at"] = f"Updated: {_fmt_updated_ts()}"
        if season:
            try:
                write_games_day_xml(
                    season=season,
                    day=d,
                    games=_dedupe_games([g for g in all_games if isinstance(g, dict)]),
                )
            except Exception:
                pass
        def _has_tbd_matchup(game: dict[str, Any]) -> bool:
            if not isinstance(game, dict):
                return False
            away = game.get("awayTeam") if isinstance(game.get("awayTeam"), dict) else {}
            home = game.get("homeTeam") if isinstance(game.get("homeTeam"), dict) else {}
            ac = str(away.get("abbrev") or away.get("abbreviation") or away.get("teamAbbrev") or "").strip().upper()
            hc = str(home.get("abbrev") or home.get("abbreviation") or home.get("teamAbbrev") or "").strip().upper()
            return ac == "TBD" or hc == "TBD"

        def _maybe_autofetch_tbd_for_date(date_sel: dt.date, games_now: list[dict[str, Any]]) -> None:
            retry_s = 20.0
            tbd_count = sum(1 for gg in games_now if _has_tbd_matchup(gg))
            if date_sel < today:
                return
            if tbd_count <= 0:
                return
            if refresh_inflight:
                return
            now_s = time.time()
            last_try = float(day_tbd_refresh_try_s.get(date_sel, 0.0) or 0.0)
            if (now_s - last_try) < retry_s:
                return
            day_tbd_refresh_try_s[date_sel] = now_s
            _run_refresh_async(date_sel, force_manual=True, reason="Resolving TBD")

        def _maybe_autorefresh_nonfinal_past_date(date_sel: dt.date, games_now: list[dict[str, Any]]) -> None:
            if date_sel >= today:
                return
            if refresh_inflight:
                return
            if not games_now:
                return
            if _is_day_finalized(date_sel):
                return
            all_final = all(
                (_game_state(gg) in {"FINAL", "OFF"} or _game_state(gg).startswith("FINAL"))
                for gg in games_now
                if isinstance(gg, dict)
            )
            if all_final:
                _set_day_finalized(date_sel, True)
                return
            retry_s = 25.0
            now_s = time.time()
            last_try = float(day_external_last_try_s.get(date_sel, 0.0) or 0.0)
            if (now_s - last_try) < retry_s:
                return
            day_external_last_try_s[date_sel] = now_s
            _run_refresh_async(date_sel, force_manual=False, reason="Checking non-final day")

        _maybe_autofetch_tbd_for_date(d, all_games)
        # MoneyPuck gameData now refreshes during normal refresh cycles for
        # active NHL clocks, so avoid a second dedicated "Loading projections"
        # loop that can create long-running back-to-back refreshes.
        _maybe_autorefresh_nonfinal_past_date(d, all_games)
        auto_refresh_has_active_games = any(
            _game_started_and_not_final(gg, assume_started_if_unknown=True)
            for gg in all_games
            if isinstance(gg, dict)
        )
        grouped = _group_by_league(all_games, selected_date=d, tz=tz)

        stage_lbl.configure(text="")

        if not all_games:
            auto_refresh_has_active_games = False
            _schedule_auto_refresh()
            _clear_cards()
            _clear_section_labels()
            empty_lbl.configure(text=err_msg or "No games")
            empty_lbl.lift()
            return

        empty_lbl.configure(text="")
        empty_lbl.lower()

        ordered_games: list[dict[str, Any]]
        if force_rebuild or len(cards) != len(all_games):
            _clear_cards()
            for _ in range(len(all_games)):
                cards.append(_make_card())
            # Position/update after geometry settles to avoid rare blank states.
            def _late_layout() -> None:
                gw = int(grid_host.winfo_width() or 0)
                gh = int(grid_host.winfo_height() or 0)
                if gw < 80 or gh < 80:
                    bgroot.after(60, _late_layout)
                    return
                og = _position_cards_grouped(grouped, d)
                _update_cards(og, d)
            bgroot.after_idle(_late_layout)
        else:
            ordered_games = _position_cards_grouped(grouped, d)
            _update_cards(ordered_games, d)

        _schedule_auto_refresh()

    def _refresh_live_gamecenter_for_games(
        d: dt.date,
        games_now: list[dict[str, Any]],
        *,
        force_network: bool,
    ) -> None:
        if not games_now:
            return
        assume_started_if_unknown = (d == today)
        for gg in games_now:
            if not isinstance(gg, dict):
                continue
            if str(gg.get("league") or "").upper() != "NHL":
                continue
            if _is_olympic_game(gg):
                continue
            game_is_live = _game_started_and_not_final(
                gg,
                assume_started_if_unknown=assume_started_if_unknown,
            )
            pregame_goalie_watch = False
            if (not game_is_live) and d == today:
                state = _game_state(gg)
                is_final_state = state in {"FINAL", "OFF"} or state.startswith("FINAL")
                if (not is_final_state) and state in {"FUT", "PRE"}:
                    start_local = _parse_start_local(gg, tz)
                    if start_local is None:
                        pregame_goalie_watch = True
                    else:
                        minutes_to_start = (start_local - dt.datetime.now(tz)).total_seconds() / 60.0
                        pregame_goalie_watch = (-15.0 <= minutes_to_start <= 120.0)
            if not game_is_live and not pregame_goalie_watch:
                continue
            gid = _to_int(gg.get("id") or gg.get("gameId") or 0, default=0)
            if gid <= 0:
                continue
            if game_is_live:
                try:
                    _load_pbp(
                        gid,
                        allow_network=True,
                        force_network=force_network and _is_live_clock_running(gg),
                    )
                except Exception:
                    pass
                try:
                    _load_boxscore(
                        gid,
                        allow_network=True,
                        force_network=force_network,
                    )
                except Exception:
                    pass
            elif pregame_goalie_watch:
                cached_boxscore = _load_boxscore(
                    gid,
                    allow_network=False,
                    force_network=False,
                )
                away_confirmed = _boxscore_has_confirmed_goalie(cached_boxscore, "awayTeam")
                home_confirmed = _boxscore_has_confirmed_goalie(cached_boxscore, "homeTeam")
                if away_confirmed and home_confirmed:
                    continue
                try:
                    _load_boxscore(
                        gid,
                        allow_network=True,
                        force_network=True,
                    )
                except Exception:
                    pass

    def _refresh_sources_for_date(
        d: dt.date,
        *,
        refresh_nhl: bool,
        refresh_olympics: bool,
        refresh_pwhl: bool,
        refresh_moneypuck: bool = False,
    ) -> tuple[int, int, int]:
        nhl_regular_n = 0
        nhl_olympic_n = 0
        nhl_games_for_probs: list[dict[str, Any]] = []
        live_clock_nhl_running = False
        if refresh_nhl or refresh_olympics:
            if refresh_nhl:
                day_points_pct_cache.clear()
                day_standings_context_cache.pop(d, None)
            try:
                raw, _err, _stamp = _get_score_payload(
                    d, prefer_cached=False, allow_network=True, force_network=True
                )
                raw = _apply_schedule_start_overrides(
                    d,
                    raw,
                    allow_network=True,
                    force_network=True,
                )
                nhl_games = [g for g in list(raw.get("games") or []) if isinstance(g, dict)]
                _remember_game_win_probs(nhl_games)
                nhl_olympic_n = len([g for g in nhl_games if _is_olympic_game(g)])
                nhl_regular_n = len(nhl_games) - nhl_olympic_n
                nhl_games_for_probs = [g for g in nhl_games if not _is_olympic_game(g)]
                live_clock_nhl_running = any(
                    _is_live_clock_running(g) for g in nhl_games_for_probs if isinstance(g, dict)
                )
                if refresh_nhl:
                    try:
                        _standings_context_by_date(
                            d,
                            allow_network=True,
                            force_network=True,
                        )
                    except Exception:
                        pass
            except Exception:
                nhl_regular_n = 0
                nhl_olympic_n = 0
        if refresh_nhl or refresh_moneypuck:
            if not nhl_games_for_probs:
                try:
                    raw_cached, _err_cached, _st_cached = _get_score_payload(
                        d, prefer_cached=True, allow_network=False
                    )
                    nhl_games_cached = [
                        g for g in list(raw_cached.get("games") or []) if isinstance(g, dict)
                    ]
                    nhl_games_for_probs = [g for g in nhl_games_cached if not _is_olympic_game(g)]
                    live_clock_nhl_running = any(
                        _is_live_clock_running(g) for g in nhl_games_for_probs if isinstance(g, dict)
                    )
                except Exception:
                    nhl_games_for_probs = []
                    live_clock_nhl_running = False
            # When a game clock is actively running, force fresh MoneyPuck gameData
            # on every refresh tick (no intermissions, no stale cache reuse).
            force_live_game_data = bool(live_clock_nhl_running and nhl_games_for_probs)
            try:
                _refresh_live_gamecenter_for_games(
                    d,
                    nhl_games_for_probs,
                    force_network=force_live_game_data,
                )
            except Exception:
                pass
            games_for_moneypuck: list[dict[str, Any]] = []
            if nhl_games_for_probs:
                started_not_final_games = [
                    g
                    for g in nhl_games_for_probs
                    if isinstance(g, dict)
                    and _game_started_and_not_final(g, assume_started_if_unknown=(d == today))
                ]
                if force_live_game_data:
                    games_for_moneypuck = [g for g in started_not_final_games if _is_live_clock_running(g)]
                elif refresh_moneypuck:
                    # Manual/day refresh only needs active games; future games use
                    # day-level percentages from the predictions page refresh below.
                    games_for_moneypuck = started_not_final_games
            if games_for_moneypuck:
                try:
                    _prefetch_moneypuck_game_probs_for_day(
                        d,
                        games_for_moneypuck,
                        allow_network=bool(refresh_moneypuck or force_live_game_data),
                        force_network=bool(refresh_moneypuck or force_live_game_data),
                    )
                except Exception:
                    pass
        # The day-level predictions page is useful for future games, but can be slow.
        # Skip it during active-clock refresh cycles where per-game CSV is authoritative.
        if refresh_moneypuck and not live_clock_nhl_running:
            try:
                _get_moneypuck_probs_for_date(d, allow_network=True, force_network=True)
            except Exception:
                pass

        espn_olympic_n = 0
        if refresh_olympics:
            try:
                day_external_empty_checked.discard(d)
                o, _p, _estamp = _fetch_espn_games(d, allow_network=True, force_network=True)
                espn_olympic_n = len(o)
            except Exception:
                espn_olympic_n = 0
        olympics_effective_n = espn_olympic_n if espn_olympic_n > 0 else (nhl_olympic_n if refresh_olympics else 0)

        pwhl_direct_n = 0
        if refresh_pwhl:
            try:
                p2, _pstamp = _fetch_pwhl_games(d, allow_network=True, force_network=True)
                pwhl_direct_n = len(p2)
            except Exception:
                pwhl_direct_n = 0
        return nhl_regular_n, olympics_effective_n, pwhl_direct_n

    def _force_refresh_for_date(d: dt.date) -> str:
        # Manual action: force a network refresh for selected date.
        t0 = time.perf_counter()
        # Keep league caches in memory so transient misses do not blank cards.
        day_payload_cache.pop(d, None)
        day_external_empty_checked.discard(d)
        day_source_plan.pop(d, None)
        nhl_n, olympics_n, pwhl_n = _refresh_sources_for_date(
            d,
            refresh_nhl=True,
            refresh_olympics=True,
            refresh_pwhl=True,
            refresh_moneypuck=True,
        )
        # Re-plan next time from fresh cache after this refresh pass.
        day_source_plan.pop(d, None)
        return _format_refresh_status(
            "Refreshed",
            nhl_n=nhl_n,
            olympics_n=olympics_n,
            pwhl_n=pwhl_n,
            elapsed_s=(time.perf_counter() - t0),
            target_date=d,
        )

    def _startup_refresh_with_backfill(d: dt.date) -> str:
        # Startup does a normal refresh for selected day, then walks backward
        # to reconcile stale non-final days until it finds a fully final day.
        first_msg = _force_refresh_for_date(d)
        checked_days = 0
        refreshed_days = 0
        max_backfill_days = 21
        cur = d - dt.timedelta(days=1)

        def _all_final(games: list[dict[str, Any]]) -> bool:
            return bool(games) and all((_game_state(g) in {"FINAL", "OFF"} or _game_state(g).startswith("FINAL")) for g in games)

        while cur >= dmin and checked_days < max_backfill_days:
            checked_days += 1
            raw, _msg, _stamp = _get_score_payload(cur, prefer_cached=True, allow_network=False)
            games = [g for g in list(raw.get("games") or []) if isinstance(g, dict)]
            if _all_final(games):
                break

            plan_nhl, plan_olympics, plan_pwhl = _planned_sources_for_date(cur)
            _refresh_sources_for_date(
                cur,
                refresh_nhl=True if (plan_nhl or games) else False,
                refresh_olympics=plan_olympics,
                refresh_pwhl=plan_pwhl,
            )
            refreshed_days += 1
            day_source_plan.pop(cur, None)

            raw2, _msg2, _stamp2 = _get_score_payload(cur, prefer_cached=True, allow_network=False)
            games2 = [g for g in list(raw2.get("games") or []) if isinstance(g, dict)]
            if _all_final(games2):
                break
            cur -= dt.timedelta(days=1)

        return (
            f"{first_msg}  |  "
            f"Backfill checked {checked_days} day(s), refreshed {refreshed_days} day(s)"
        )

    def _run_refresh_async(d: dt.date, *, force_manual: bool, reason: str, startup_backfill: bool = False) -> None:
        nonlocal refresh_inflight
        if refresh_inflight:
            refresh_status_var.set("Refresh already running...")
            return
        _cancel_refresh()
        refresh_inflight = True
        refresh_status_var.set(f"{reason}...")

        def _worker() -> None:
            msg = ""
            try:
                if startup_backfill:
                    msg = _startup_refresh_with_backfill(d)
                elif force_manual:
                    msg = _force_refresh_for_date(d)
                else:
                    msg = _selective_refresh_for_date(d, manual_trigger=(reason == "Refreshing"))
            except Exception as e:
                msg = f"Refresh failed: {e}"

            def _done() -> None:
                nonlocal refresh_inflight
                refresh_inflight = False
                refresh_status_var.set(msg)
                _render_day(force_rebuild=False)

            try:
                bgroot.after(0, _done)
            except Exception:
                pass

        threading.Thread(target=_worker, daemon=True).start()

    def _manual_refresh() -> None:
        d = _selected_date()
        _run_refresh_async(d, force_manual=True, reason="Refreshing")

    def _selective_refresh_for_date(d: dt.date, *, manual_trigger: bool = False) -> str:
        t0 = time.perf_counter()
        # Refresh only when cached games indicate we should:
        # 1) active in cache, or
        # 2) FUT where start time is already in the past.
        if _is_day_finalized(d):
            return _format_refresh_status(
                "Checked",
                nhl_n=0,
                olympics_n=0,
                pwhl_n=0,
                elapsed_s=(time.perf_counter() - t0),
                target_date=d,
            )
        plan_nhl, plan_olympics, plan_pwhl = _planned_sources_for_date(d)
        try:
            raw_cached, _err_msg, _nhl_stamp = _get_score_payload(d, prefer_cached=True, allow_network=False)
            raw_cached = _apply_schedule_start_overrides(d, raw_cached, allow_network=False)
            nhl_games_all = [g for g in list(raw_cached.get("games") or []) if isinstance(g, dict)]
        except Exception:
            nhl_games_all = []

        # For "today", force a live pull when cache is empty so new starts appear.
        if d == today and not nhl_games_all:
            _get_score_payload(d, prefer_cached=False, allow_network=True, force_network=True)
            try:
                raw_cached, _err_msg, _nhl_stamp = _get_score_payload(d, prefer_cached=True, allow_network=False)
                raw_cached = _apply_schedule_start_overrides(d, raw_cached, allow_network=False)
                nhl_games_all = [g for g in list(raw_cached.get("games") or []) if isinstance(g, dict)]
            except Exception:
                nhl_games_all = []

        nhl_olympic = [g for g in nhl_games_all if _is_olympic_game(g)]
        nhl_regular = [g for g in nhl_games_all if not _is_olympic_game(g)]

        try:
            ext_olympics_cached, _ext_pwhl_cached, _ext_stamp = _fetch_espn_games(d, allow_network=False)
        except Exception:
            ext_olympics_cached = []
        try:
            pwhl_direct_cached, _pwhl_stamp = _fetch_pwhl_games(d, allow_network=False)
        except Exception:
            pwhl_direct_cached = []

        olympics_from_nhl_fallback = bool(nhl_olympic) and not bool(ext_olympics_cached)
        olympics_cached = ext_olympics_cached if ext_olympics_cached else nhl_olympic
        pwhl_cached = pwhl_direct_cached

        assume_unknown_started = (d == today)
        nhl_needs = _needs_live_refresh(
            nhl_regular, assume_started_if_unknown=assume_unknown_started
        )
        olympics_needs = _needs_live_refresh(
            olympics_cached, assume_started_if_unknown=assume_unknown_started
        )
        pwhl_needs = _needs_live_refresh(
            pwhl_cached, assume_started_if_unknown=assume_unknown_started
        )

        if d < today:
            # Past-day checks should only touch sources that still have non-final rows.
            assume_unknown_started = True
            nhl_needs = _needs_live_refresh(
                nhl_regular, assume_started_if_unknown=assume_unknown_started
            )
            olympics_needs = _needs_live_refresh(
                olympics_cached, assume_started_if_unknown=assume_unknown_started
            )
            pwhl_needs = _needs_live_refresh(
                pwhl_cached, assume_started_if_unknown=assume_unknown_started
            )
            if (nhl_regular or nhl_olympic or olympics_cached or pwhl_cached) and not (
                nhl_needs or olympics_needs or pwhl_needs
            ):
                _set_day_finalized(d, True)
                day_source_plan.pop(d, None)
                return _format_refresh_status(
                    "Checked",
                    nhl_n=0,
                    olympics_n=0,
                    pwhl_n=0,
                    elapsed_s=(time.perf_counter() - t0),
                    target_date=d,
                )
            refresh_nhl = (plan_nhl and nhl_needs) or (plan_olympics and olympics_needs and olympics_from_nhl_fallback)
            refresh_olympics = plan_olympics and olympics_needs
            refresh_pwhl = plan_pwhl and pwhl_needs
            refresh_moneypuck = bool(manual_trigger and plan_nhl and nhl_regular)
        else:
            # Auto-refresh follows the same source refresh flow as manual refresh,
            # but only for sources that are active (or should now be active).
            refresh_nhl = (plan_nhl and nhl_needs) or (plan_olympics and olympics_needs and olympics_from_nhl_fallback)
            refresh_olympics = plan_olympics and olympics_needs
            refresh_pwhl = plan_pwhl and pwhl_needs
            has_live_clock_nhl = any(_is_live_clock_running(g) for g in nhl_regular if isinstance(g, dict))
            refresh_moneypuck = (
                plan_nhl
                and bool(nhl_regular)
                and (manual_trigger or has_live_clock_nhl)
            )

        nhl_n, olympics_n, pwhl_n = _refresh_sources_for_date(
            d,
            refresh_nhl=refresh_nhl,
            refresh_olympics=refresh_olympics,
            refresh_pwhl=refresh_pwhl,
            refresh_moneypuck=refresh_moneypuck,
        )
        day_source_plan.pop(d, None)
        if manual_trigger:
            prefix = "Refreshed"
        else:
            prefix = "Auto refreshed" if d == today else "Checked"
        return _format_refresh_status(
            prefix,
            nhl_n=nhl_n,
            olympics_n=olympics_n,
            pwhl_n=pwhl_n,
            elapsed_s=(time.perf_counter() - t0),
            target_date=d,
        )

    def _startup_render_or_refresh() -> None:
        # Render cache immediately for fast startup.
        d = _selected_date()
        _render_day(force_rebuild=True)
        # One-shot startup prefetch for tomorrow when cached matchups still show TBD.
        # This resolves late-set Olympic bracket slots without waiting for manual refresh.
        def _startup_prefetch_tomorrow_tbd() -> None:
            td = today + dt.timedelta(days=1)
            try:
                if td < dmin or td > dmax:
                    return
                has_tbd = False
                try:
                    raw_td, _msg, _st = _get_score_payload(td, prefer_cached=True, allow_network=False)
                    for gg in list(raw_td.get("games") or []):
                        if not isinstance(gg, dict):
                            continue
                        a = str(((gg.get("awayTeam") or {}).get("abbrev") or "")).upper()
                        h = str(((gg.get("homeTeam") or {}).get("abbrev") or "")).upper()
                        if a == "TBD" or h == "TBD":
                            has_tbd = True
                            break
                except Exception:
                    pass
                if not has_tbd:
                    try:
                        eo, _ep, _est = _fetch_espn_games(td, allow_network=False)
                        for gg in eo:
                            if not isinstance(gg, dict):
                                continue
                            a = str(((gg.get("awayTeam") or {}).get("abbrev") or "")).upper()
                            h = str(((gg.get("homeTeam") or {}).get("abbrev") or "")).upper()
                            if a == "TBD" or h == "TBD":
                                has_tbd = True
                                break
                    except Exception:
                        pass
                if has_tbd:
                    _refresh_sources_for_date(
                        td,
                        refresh_nhl=True,
                        refresh_olympics=True,
                        refresh_pwhl=True,
                        refresh_moneypuck=True,
                    )
                    try:
                        bgroot.after(0, lambda: _render_day(force_rebuild=False))
                    except Exception:
                        pass
            except Exception:
                return
        threading.Thread(target=_startup_prefetch_tomorrow_tbd, daemon=True).start()
        # Then do a non-blocking startup refresh for today (if not finalized).
        # Use the same path as manual refresh so startup behavior matches what
        # users see when pressing Refresh.
        if d == today and not _is_day_finalized(d):
            _run_refresh_async(d, force_manual=True, reason="Startup refresh", startup_backfill=True)

    def _on_scale(_v: str = "") -> None:
        nonlocal scale_after_id
        v = int(float(scale.get()))
        if v != day_var.get():
            day_var.set(v)
        if scale_after_id is not None:
            try:
                bgroot.after_cancel(scale_after_id)
            except Exception:
                pass
        # Debounce slider drags so we don't repaint dozens of times per second.
        scale_after_id = bgroot.after(90, lambda: _render_day(force_rebuild=False))

    def _step(delta: int) -> None:
        v = int(day_var.get()) + delta
        v = max(0, min(total_days, v))
        day_var.set(v)
        scale.set(v)
        _render_day(force_rebuild=False)

    def _go_today() -> None:
        v = max(0, min(total_days, (active_today - dmin).days))
        day_var.set(v)
        scale.set(v)
        _render_day(force_rebuild=False)

    def _on_resize(_evt: Optional[object] = None) -> None:
        nonlocal resize_after_id
        if resize_after_id is not None:
            try:
                bgroot.after_cancel(resize_after_id)
            except Exception:
                pass
        resize_after_id = bgroot.after(120, lambda: _render_day(force_rebuild=False))

    # Wire events
    scale.configure(command=_on_scale)
    grid_host.bind("<Configure>", _on_resize)

    today_btn = _make_step_button(bgroot, "Today", _go_today)
    today_btn.configure(width=6, padx=10, pady=6)
    today_btn.place(x=10, y=8, anchor="nw")
    refresh_btn = _make_step_button(bgroot, "Refresh", _manual_refresh)
    refresh_btn.configure(width=7, padx=10, pady=6)
    refresh_btn.place(x=84, y=8, anchor="nw")
    auto_btn = _make_step_button(bgroot, "Auto: On", lambda: None)
    auto_btn.configure(width=8, padx=10, pady=6)
    auto_btn.place(x=163, y=8, anchor="nw")
    refresh_status_var = tk.StringVar(value="")
    refresh_status_lbl = tk.Label(
        bgroot,
        textvariable=refresh_status_var,
        bg=BG,
        fg=MUTED,
        font=("TkDefaultFont", 9),
        anchor="w",
    )
    refresh_status_lbl.place(x=255, y=12, anchor="nw")

    def _toggle_auto_refresh() -> None:
        nonlocal auto_refresh_enabled
        auto_refresh_enabled = not auto_refresh_enabled
        auto_btn.configure(text=f"Auto: {'On' if auto_refresh_enabled else 'Off'}")
        if auto_refresh_enabled:
            refresh_status_var.set(
                f"Auto refresh on ({auto_refresh_s}s live / :00 idle)"
            )
            _schedule_auto_refresh()
        else:
            refresh_status_var.set("Auto refresh off")
            _cancel_refresh()

    auto_btn.bind("<Button-1>", lambda _e: _toggle_auto_refresh(), add="+")

    def _on_destroy(_evt=None):
        _cancel_refresh()
        for c in cards:
            if c.scorer_popup is not None:
                try:
                    c.scorer_popup.destroy()
                except Exception:
                    pass
                c.scorer_popup = None
        _clear_section_labels()

    bgroot.bind("<Destroy>", _on_destroy)

    # Initial render
    bgroot.after(0, _startup_render_or_refresh)

    return root