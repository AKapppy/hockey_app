from __future__ import annotations

from .teams import canon_team_code

TEAM_PRIMARY_COLOR_DEFAULTS: dict[str, str] = {
    "ANA": "#F47A38",
    "BOS": "#FFB81C",
    "BUF": "#003087",
    "CGY": "#C8102E",
    "CAR": "#CC0000",
    "CHI": "#C8102E",
    "COL": "#6F263D",
    "CBJ": "#002654",
    "DAL": "#006847",
    "DET": "#CE1126",
    "EDM": "#041E42",
    "FLA": "#041E42",
    "LAK": "#111111",
    "MIN": "#154734",
    "MTL": "#AF1E2D",
    "NSH": "#FFB81C",
    "NJD": "#CE1126",
    "NYI": "#00539B",
    "NYR": "#0038A8",
    "OTT": "#C52032",
    "PHI": "#F74902",
    "PIT": "#FFB81C",
    "SJS": "#006D75",
    "SEA": "#001628",
    "STL": "#002F87",
    "TBL": "#002868",
    "TOR": "#00205B",
    "UTA": "#6CACE4",
    "VAN": "#00205B",
    "VGK": "#B9975B",
    "WSH": "#C8102E",
    "WPG": "#041E42",
}

TEAM_ALT_FOR_DARKMODE: dict[str, str] = {
    "LAK": "#A2AAAD",
    "SEA": "#99D9D9",
    "TOR": "#A2AAAD",
    "TBL": "#A2AAAD",
    "EDM": "#FF4C00",
    "WPG": "#AC162C",
}

TEAM_BAR_DARK_COLOR_DEFAULTS: dict[str, str] = {
    "ANA": "#89734C",
    "BOS": "#010101",
    "BUF": "#003087",
    "CAR": "#010101",
    "CBJ": "#041E42",
    "CGY": "#C8102E",
    "CHI": "#010101",
    "COL": "#8A2432",
    "DAL": "#000000",
    "DET": "#C8102E",
    "EDM": "#00205B",
    "FLA": "#041E42",
    "LAK": "#010101",
    "MIN": "#0E4431",
    "MTL": "#001E62",
    "NJD": "#000000",
    "NSH": "#041E42",
    "NYI": "#00468B",
    "NYR": "#154B94",
    "OTT": "#010101",
    "PHI": "#000000",
    "PIT": "#000000",
    "SEA": "#001425",
    "SJS": "#010101",
    "STL": "#004986",
    "TBL": "#00205B",
    "TOR": "#00205B",
    "UTA": "#010101",
    "VAN": "#00205B",
    "VGK": "#333F48",
    "WSH": "#041E42",
    "WPG": "#041E42",
}

TEAM_BAR_LIGHT_COLOR_DEFAULTS: dict[str, str] = {
    "ANA": "#CF4520",
    "BOS": "#FFB81C",
    "BUF": "#FFB81C",
    "CAR": "#C8102E",
    "CBJ": "#C8102E",
    "CGY": "#F1BE48",
    "CHI": "#CE1126",
    "COL": "#236093",
    "DAL": "#00823E",
    "DET": "#FFFFFF",
    "EDM": "#D14520",
    "FLA": "#C8102E",
    "LAK": "#A2AAAD",
    "MIN": "#AC1A2E",
    "MTL": "#A6192E",
    "NJD": "#CC0000",
    "NSH": "#FFB81C",
    "NYI": "#F26924",
    "NYR": "#C32032",
    "OTT": "#C8102E",
    "PHI": "#D24303",
    "PIT": "#FFB81C",
    "SEA": "#96D8D8",
    "SJS": "#00778B",
    "STL": "#FFB81C",
    "TBL": "#FFFFFF",
    "TOR": "#FFFFFF",
    "UTA": "#7AB2E0",
    "VAN": "#046A38",
    "VGK": "#B9975B",
    "WSH": "#C8102E",
    "WPG": "#004A98",
}


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{r:02x}{g:02x}{b:02x}"


def _blend(hex_a: str, hex_b: str, t: float) -> str:
    t = max(0.0, min(1.0, t))
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


def build_team_color_map(extra_codes: set[str] | None = None) -> dict[str, str]:
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


def bar_gradient_pair(team_code: str, primary_map: dict[str, str]) -> tuple[str, str]:
    c = canon_team_code(str(team_code).upper())

    left = TEAM_BAR_DARK_COLOR_DEFAULTS.get(c)
    right = TEAM_BAR_LIGHT_COLOR_DEFAULTS.get(c)
    base = primary_map.get(c, _hex_from_hash(c))

    if left or right:
        if not left:
            left = base
        if not right:
            right = TEAM_ALT_FOR_DARKMODE.get(c)
            if not right:
                right = _blend(left, "#ffffff", 0.55) if _rel_luminance(left) < 0.45 else _blend(left, "#000000", 0.35)

        if _rel_luminance(left) > _rel_luminance(right):
            left, right = right, left

        if abs(_rel_luminance(left) - _rel_luminance(right)) < 0.08:
            left2 = _blend(left, "#000000", 0.25)
            right2 = _blend(right, "#ffffff", 0.25)
            if _rel_luminance(left2) > _rel_luminance(right2):
                left2, right2 = right2, left2
            return left2, right2

        return left, right

    left = base
    right = TEAM_ALT_FOR_DARKMODE.get(c)
    if not right:
        right = _blend(base, "#ffffff", 0.55) if _rel_luminance(base) < 0.45 else _blend(base, "#000000", 0.42)

    if _rel_luminance(left) > _rel_luminance(right):
        left, right = right, left

    if abs(_rel_luminance(left) - _rel_luminance(right)) < 0.10:
        left = _blend(base, "#000000", 0.38)
        right = _blend(base, "#ffffff", 0.38)
        if _rel_luminance(left) > _rel_luminance(right):
            left, right = right, left

    return left, right
