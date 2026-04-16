import datetime as dt
import csv
import os
import re
import requests
from pathlib import Path
from typing import Dict, List, Tuple
from hockey_app.data.paths import cache_dir
from hockey_app.data.xml_cache import ensure_season_xml_scaffold

# ----------------------------
# Season / dates
# ----------------------------
def _default_season_for_today(today: dt.date | None = None) -> str:
    d = today or dt.date.today()
    # NHL season typically starts in October.
    # Jul-Sep uses the most recently completed season rather than the upcoming one.
    if d.month >= 10:
        y0 = d.year
    else:
        y0 = d.year - 1
    return f"{y0}-{y0 + 1}"


def _normalize_season_text(value: str) -> str | None:
    s = str(value or "").strip()
    m = re.fullmatch(r"(\d{4})-(\d{2}|\d{4})", s)
    if not m:
        return None
    y0 = int(m.group(1))
    y1_raw = m.group(2)
    if len(y1_raw) == 2:
        yy = int(y1_raw)
        century = (y0 // 100) * 100
        y1 = century + yy
        if y1 < y0:
            y1 += 100
    else:
        y1 = int(y1_raw)
    if y1 < y0:
        return None
    return f"{y0}-{y1}"


def _season_from_env_or_default() -> str:
    raw = os.environ.get("HOCKEY_SEASON", "")
    norm = _normalize_season_text(raw)
    if norm:
        return norm
    return _default_season_for_today()


def _project_season_dates_csv() -> Path:
    p = Path(__file__).resolve().parents[1] / "cache" / "season_dates.csv"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _read_season_dates_rows() -> dict[str, dict[str, str]]:
    path = _project_season_dates_csv()
    if not path.exists():
        return {}
    out: dict[str, dict[str, str]] = {}
    try:
        with path.open("r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                season_key = str(row.get("season") or "").strip()
                if season_key:
                    out[season_key] = {str(k): str(v or "") for k, v in row.items()}
    except Exception:
        return {}
    return out


def _write_season_dates_rows(rows: dict[str, dict[str, str]]) -> None:
    path = _project_season_dates_csv()
    fields = [
        "season",
        "start_date",
        "regular_season_start",
        "regular_season_end",
        "playoffs_start",
        "cup_final_start",
        "source",
        "updated_at",
    ]
    try:
        with path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            for season_key in sorted(rows.keys()):
                row = dict(rows[season_key])
                row["season"] = season_key
                writer.writerow({k: row.get(k, "") for k in fields})
    except Exception:
        pass


def _season_start_from_csv(season: str) -> dt.date | None:
    rows = _read_season_dates_rows()
    row = rows.get(str(season).strip())
    if not row:
        return None
    for key in ("start_date", "regular_season_start"):
        d = _parse_iso_date(row.get(key))
        if d is not None:
            return d
    return None


def _upsert_season_start_csv(season: str, start_date: dt.date, *, source: str) -> None:
    rows = _read_season_dates_rows()
    key = str(season).strip()
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    row = rows.get(key, {})
    row["start_date"] = start_date.isoformat()
    if not str(row.get("regular_season_start") or "").strip():
        row["regular_season_start"] = start_date.isoformat()
    row["source"] = source
    row["updated_at"] = now
    rows[key] = row
    _write_season_dates_rows(rows)


SEASON = _season_from_env_or_default()
try:
    ensure_season_xml_scaffold(SEASON)
except Exception:
    pass
def _parse_iso_date(value: object) -> dt.date | None:
    if not isinstance(value, str):
        return None
    s = value.strip()
    if len(s) >= 10:
        s = s[:10]
    try:
        return dt.date.fromisoformat(s)
    except Exception:
        return None


def _pick_date_deep(obj: object, keys: tuple[str, ...], *, prefer: str = "min") -> dt.date | None:
    found: list[dt.date] = []

    def _walk(v: object) -> None:
        if isinstance(v, dict):
            for k in keys:
                if k in v:
                    d = _parse_iso_date(v.get(k))
                    if d is not None:
                        found.append(d)
            for vv in v.values():
                _walk(vv)
        elif isinstance(v, list):
            for vv in v:
                _walk(vv)

    _walk(obj)
    if not found:
        return None
    return min(found) if prefer == "min" else max(found)


def _season_years(season: str) -> tuple[int | None, int | None]:
    norm = _normalize_season_text(str(season))
    if norm is None:
        return (None, None)
    parts = [p for p in norm.split("-") if p.strip()]
    if len(parts) != 2:
        return (None, None)
    try:
        return (int(parts[0]), int(parts[1]))
    except Exception:
        return (None, None)


def _season_probe_date(season: str) -> dt.date:
    _y0, y1 = _season_years(season)
    if isinstance(y1, int):
        return dt.date(y1, 1, 15)
    d = dt.date.today()
    return dt.date(d.year, 1, 15)


def _resolve_season_bounds_cached(
    season: str,
    *,
    fallback_start: dt.date,
    fallback_end: dt.date,
) -> tuple[dt.date, dt.date]:
    today = dt.date.today()
    historical_season = fallback_end < today

    key = str(season).strip() or "season"
    start_cache_file = cache_dir() / "meta" / f"season_start_{key}.txt"
    end_cache_file = cache_dir() / "meta" / f"season_end_{key}.txt"
    cached_start: dt.date | None = None
    cached_end: dt.date | None = None
    try:
        if start_cache_file.exists():
            cached_start = _parse_iso_date(start_cache_file.read_text(encoding="utf-8").strip())
    except Exception:
        cached_start = None
    try:
        if end_cache_file.exists():
            cached_end = _parse_iso_date(end_cache_file.read_text(encoding="utf-8").strip())
    except Exception:
        pass
    if cached_start is not None and cached_end is not None:
        # Historical seasons should include full postseason range.
        if historical_season and cached_end < fallback_end:
            cached_end = fallback_end
        if cached_end < cached_start:
            return cached_start, cached_start
        return cached_start, cached_end

    probe = _season_probe_date(season)
    base_url = "https://api-web.nhle.com"
    endpoints = (
        f"{base_url}/v1/schedule/{probe.isoformat()}",
        f"{base_url}/v1/schedule-calendar/{probe.isoformat()}",
    )
    resolved_start = cached_start
    resolved_end = cached_end
    try:
        payloads: list[object] = []
        for url in endpoints:
            r = requests.get(
                url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; HockeyApp/1.0)"},
                timeout=8,
            )
            if r.ok:
                payloads.append(r.json())
        pre_start = _pick_date_deep(
            payloads,
            ("preSeasonStartDate", "preseasonStartDate", "exhibitionStartDate"),
            prefer="min",
        )
        reg_start = _pick_date_deep(
            payloads,
            ("regularSeasonStartDate", "regSeasonStartDate", "regularStartDate"),
            prefer="min",
        )
        season_start = _pick_date_deep(payloads, ("seasonStartDate", "startDate"), prefer="min")
        playoff_end = _pick_date_deep(
            payloads,
            ("playoffEndDate", "playoffsEndDate", "postSeasonEndDate", "stanleyCupFinalEndDate"),
            prefer="max",
        )
        season_end = _pick_date_deep(
            payloads,
            (
                "seasonEndDate",
                "endDate",
                "lastGameDate",
                "regularSeasonEndDate",
                "regSeasonEndDate",
            ),
            prefer="max",
        )
        if resolved_start is None:
            resolved_start = pre_start or reg_start or season_start
        if resolved_end is None:
            resolved_end = playoff_end or season_end
    except Exception:
        pass

    if resolved_start is None:
        resolved_start = fallback_start
    if resolved_end is None:
        resolved_end = fallback_end
    if historical_season and resolved_end < fallback_end:
        resolved_end = fallback_end
    if resolved_end < resolved_start:
        resolved_end = resolved_start

    try:
        start_cache_file.parent.mkdir(parents=True, exist_ok=True)
        start_cache_file.write_text(resolved_start.isoformat(), encoding="utf-8")
        end_cache_file.write_text(resolved_end.isoformat(), encoding="utf-8")
    except Exception:
        pass
    return resolved_start, resolved_end


def _season_start_fallback(season: str) -> dt.date:
    y0, _y1 = _season_years(season)
    if isinstance(y0, int):
        return dt.date(y0, 10, 1)
    d = dt.date.today()
    return dt.date(d.year, 10, 1)


def _season_end_fallback(season: str) -> dt.date:
    _y0, y1 = _season_years(season)
    if isinstance(y1, int):
        return dt.date(y1, 6, 30)
    return dt.date.today()


_csv_start = _season_start_from_csv(SEASON)
START_DATE, SEASON_END_DATE = _resolve_season_bounds_cached(
    SEASON,
    fallback_start=_csv_start or _season_start_fallback(SEASON),
    fallback_end=_season_end_fallback(SEASON),
)
_upsert_season_start_csv(SEASON, START_DATE, source="resolved")
TODAY = dt.date.today()
END_DATE = min(TODAY, SEASON_END_DATE)
if END_DATE < START_DATE:
    END_DATE = START_DATE
SEASON_PROBE_DATE = _season_probe_date(SEASON)

# ----------------------------
# MoneyPuck
# ----------------------------
URL_SIMULATIONS = "https://moneypuck.com/moneypuck/simulations/"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; HockeyApp/1.0)"}

# Logos (3-letter code PNGs)
URL_LOGOS_BASE = "https://peter-tanner.com/moneypuck/logos/"

# ----------------------------
# UI theme
# ----------------------------
# Used by multiple UI modules (widgets, and legacy MoneyPuck renderer)
DARK_WINDOW_BG = "#2c2c2c"
DARK_CANVAS_BG = "#262626"

# ----------------------------
# NHL API (nhle.com)
# ----------------------------
# This is the public JSON API used by the modern NHL site.
# Keep NHL_API_BASE (legacy) AND add NHL_API_BASE_URL (used by nhl_api.py).
NHL_API_BASE = "https://api-web.nhle.com/v1"
NHL_API_BASE_URL = "https://api-web.nhle.com"
TIMEZONE = "America/New_York"
REQUEST_TIMEOUT_S = 20
ESPN_API_BASE_URL = "https://site.api.espn.com/apis/site/v2"
ESPN_SCOREBOARD_LIVE_TTL_S = 120
NHL_SCORE_LIVE_TTL_S = 20

# ----------------------------
# Predictions metrics (MoneyPuck CSV columns)
# ----------------------------
METRICS: Dict[str, str] = {
    "madeplayoffs": "madePlayoffs",
    "round2": "round2",
    "round3": "round3",
    "round4": "round4",
    "woncup": "wonCup",
}

TAB_ORDER: List[str] = ["madeplayoffs", "round2", "round3", "round4", "woncup"]

TAB_LABELS: Dict[str, str] = {
    "madeplayoffs": "Make Playoffs",
    "round2": "Make Round 2",
    "round3": "Make Conference Final",
    "round4": "Make Cup Final",
    "woncup": "Win Cup",
}

TAB_TITLES: Dict[str, str] = {
    "madeplayoffs": "Playoff Race",
    "round2": "Win First Round",
    "round3": "Win Second Round",
    "round4": "Win Conference Finals",
    "woncup": "Win Stanley Cup",
}

# ----------------------------
# Team metadata
# ----------------------------
TEAM_NAMES: Dict[str, str] = {
    "ANA": "Anaheim Ducks",
    "BOS": "Boston Bruins",
    "BUF": "Buffalo Sabres",
    "CAR": "Carolina Hurricanes",
    "CBJ": "Columbus Blue Jackets",
    "CGY": "Calgary Flames",
    "CHI": "Chicago Blackhawks",
    "COL": "Colorado Avalanche",
    "DAL": "Dallas Stars",
    "DET": "Detroit Red Wings",
    "EDM": "Edmonton Oilers",
    "FLA": "Florida Panthers",
    "LAK": "Los Angeles Kings",
    "MIN": "Minnesota Wild",
    "MTL": "Montreal Canadiens",
    "NJD": "New Jersey Devils",
    "NSH": "Nashville Predators",
    "NYI": "New York Islanders",
    "NYR": "New York Rangers",
    "OTT": "Ottawa Senators",
    "PHI": "Philadelphia Flyers",
    "PIT": "Pittsburgh Penguins",
    "SEA": "Seattle Kraken",
    "SJS": "San Jose Sharks",
    "STL": "St. Louis Blues",
    "TBL": "Tampa Bay Lightning",
    "TOR": "Toronto Maple Leafs",
    "UTA": "Utah Mammoth",
    "VAN": "Vancouver Canucks",
    "VGK": "Vegas Golden Knights",
    "WSH": "Washington Capitals",
    "WPG": "Winnipeg Jets",
}

TEAM_CODE_ALIASES: Dict[str, str] = {
    "ARI": "UTA",
}


def canon_team_code(code: str) -> str:
    c = str(code).upper()
    return TEAM_CODE_ALIASES.get(c, c)


DIVS_MASTER: Dict[str, List[str]] = {
    "Pacific":  ["ANA", "CGY", "EDM", "LAK", "SEA", "SJS", "VAN", "VGK"],
    "Central":  ["CHI", "COL", "DAL", "MIN", "NSH", "STL", "WPG", "UTA"],
    "Atlantic": ["BOS", "BUF", "DET", "FLA", "MTL", "OTT", "TBL", "TOR"],
    "Metro":    ["CAR", "CBJ", "NJD", "NYI", "NYR", "PHI", "PIT", "WSH"],
}
WEST_DIVS = {"Pacific", "Central"}

TEAM_TO_DIV: Dict[str, str] = {}
TEAM_TO_CONF: Dict[str, str] = {}
for div, lst in DIVS_MASTER.items():
    for c in lst:
        TEAM_TO_DIV[c] = div
        TEAM_TO_CONF[c] = "West" if div in WEST_DIVS else "East"


def division_columns_for_codes(codes: set[str]) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for div, lst in DIVS_MASTER.items():
        present = [c for c in lst if c in codes]
        present.sort(key=lambda c: (TEAM_NAMES.get(c, c), c))
        out[div] = present
    return out


# ----------------------------
# Color helpers (used across UI)
# ----------------------------
TEAM_PRIMARY_COLOR_DEFAULTS: Dict[str, str] = {
    "ANA": "#F47A38", "BOS": "#FFB81C", "BUF": "#003087", "CAR": "#CC0000",
    "CBJ": "#002654", "CGY": "#C8102E", "CHI": "#C8102E", "COL": "#6F263D",
    "DAL": "#006847", "DET": "#CE1126", "EDM": "#041E42", "FLA": "#041E42",
    "LAK": "#111111", "MIN": "#154734", "MTL": "#AF1E2D", "NSH": "#FFB81C",
    "NJD": "#CE1126", "NYI": "#00539B", "NYR": "#0038A8", "OTT": "#C52032",
    "PHI": "#F74902", "PIT": "#FFB81C", "SEA": "#001628", "SJS": "#006D75",
    "STL": "#002F87", "TBL": "#002868", "TOR": "#00205B", "UTA": "#6CACE4",
    "VAN": "#00205B", "VGK": "#B9975B", "WSH": "#C8102E", "WPG": "#041E42",
}

TEAM_ALT_FOR_DARKMODE: Dict[str, str] = {
    "LAK": "#A2AAAD", "SEA": "#99D9D9", "TOR": "#A2AAAD", "TBL": "#A2AAAD",
    "EDM": "#FF4C00", "WPG": "#AC162C",
}

TEAM_BAR_DARK_COLOR_DEFAULTS: Dict[str, str] = {
    "ANA": "#89734C", "BOS": "#010101", "BUF": "#003087", "CAR": "#010101",
    "CBJ": "#041E42", "CGY": "#C8102E", "CHI": "#010101", "COL": "#8A2432",
    "DAL": "#000000", "DET": "#C8102E", "EDM": "#00205B", "FLA": "#041E42",
    "LAK": "#010101", "MIN": "#0E4431", "MTL": "#001E62", "NJD": "#000000",
    "NSH": "#041E42", "NYI": "#00468B", "NYR": "#154B94", "OTT": "#010101",
    "PHI": "#000000", "PIT": "#000000", "SEA": "#001425", "SJS": "#010101",
    "STL": "#004986", "TBL": "#00205B", "TOR": "#00205B", "UTA": "#010101",
    "VAN": "#00205B", "VGK": "#333F48", "WSH": "#041E42", "WPG": "#041E42",
}

TEAM_BAR_LIGHT_COLOR_DEFAULTS: Dict[str, str] = {
    "ANA": "#CF4520", "BOS": "#FFB81C", "BUF": "#FFB81C", "CAR": "#C8102E",
    "CBJ": "#C8102E", "CGY": "#F1BE48", "CHI": "#CE1126", "COL": "#236093",
    "DAL": "#00823E", "DET": "#FFFFFF", "EDM": "#D14520", "FLA": "#C8102E",
    "LAK": "#A2AAAD", "MIN": "#AC1A2E", "MTL": "#A6192E", "NJD": "#CC0000",
    "NSH": "#FFB81C", "NYI": "#F26924", "NYR": "#C32032", "OTT": "#C8102E",
    "PHI": "#D24303", "PIT": "#FFB81C", "SEA": "#96D8D8", "SJS": "#00778B",
    "STL": "#FFB81C", "TBL": "#FFFFFF", "TOR": "#FFFFFF", "UTA": "#7AB2E0",
    "VAN": "#046A38", "VGK": "#B9975B", "WSH": "#C8102E", "WPG": "#004A98",
}


def _hex_to_rgb(h: str) -> Tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{r:02x}{g:02x}{b:02x}"


def _blend(hex_a: str, hex_b: str, t: float) -> str:
    t = max(0.0, min(1.0, float(t)))
    ar, ag, ab = _hex_to_rgb(hex_a)
    br, bg, bb = _hex_to_rgb(hex_b)
    return _rgb_to_hex(
        int(ar + (br - ar) * t),
        int(ag + (bg - ag) * t),
        int(ab + (bb - ab) * t),
    )


def _rel_luminance(hex_color: str) -> float:
    r, g, b = _hex_to_rgb(hex_color)

    def f(c: float) -> float:
        c = c / 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    rl, gl, bl = f(r), f(g), f(b)
    return 0.2126 * rl + 0.7152 * gl + 0.0722 * bl


def _hex_from_hash(code: str) -> str:
    h = 0
    for ch in code.upper():
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    r, g, b = (h >> 16) & 0xFF, (h >> 8) & 0xFF, h & 0xFF
    lo, hi = 95, 235
    r, g, b = max(lo, min(hi, r)), max(lo, min(hi, g)), max(lo, min(hi, b))
    return _rgb_to_hex(r, g, b)


def build_team_color_map(extra_codes: set[str] | None = None) -> Dict[str, str]:
    codes = set(TEAM_PRIMARY_COLOR_DEFAULTS)
    if extra_codes:
        codes |= set(extra_codes)
    return {c: TEAM_PRIMARY_COLOR_DEFAULTS.get(c, _hex_from_hash(c)) for c in codes}


def theme_adjusted_line_color(team_code: str, base_color: str) -> str:
    code = str(team_code).upper()
    lum = _rel_luminance(base_color)
    if lum < 0.030:
        return TEAM_ALT_FOR_DARKMODE.get(code, _blend(base_color, "#FFFFFF", 0.58))
    return base_color


def bar_gradient_pair(team_code: str, primary_map: Dict[str, str]) -> Tuple[str, str]:
    c = canon_team_code(str(team_code).upper())

    left = TEAM_BAR_DARK_COLOR_DEFAULTS.get(c)
    right = TEAM_BAR_LIGHT_COLOR_DEFAULTS.get(c)
    base = primary_map.get(c, _hex_from_hash(c))

    if left or right:
        if not left:
            left = base
        if not right:
            right = TEAM_ALT_FOR_DARKMODE.get(c) or _blend(left, "#ffffff", 0.55)

        if _rel_luminance(left) > _rel_luminance(right):
            left, right = right, left
        return left, right

    left = base
    right = TEAM_ALT_FOR_DARKMODE.get(c) or _blend(base, "#ffffff", 0.55)
    if _rel_luminance(left) > _rel_luminance(right):
        left, right = right, left
    return left, right

# ---------------------------------------------------------------------------
# Theme aliases (used by legacy Games-tab helper)
# ---------------------------------------------------------------------------
# These aliases keep the new Games tab consistent with the existing dark UI.

APP_BG = DARK_WINDOW_BG
CARD_BG = DARK_CANVAS_BG
TEXT = "#f0f0f0"
MUTED_TEXT = "#bfbfbf"
ACCENT = "#9ecbff"
