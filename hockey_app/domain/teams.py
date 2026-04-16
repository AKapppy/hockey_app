from __future__ import annotations

TEAM_NAMES: dict[str, str] = {
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

TEAM_CODE_ALIASES: dict[str, str] = {
    "ARI": "UTA",
}


def canon_team_code(code: str) -> str:
    c = str(code).upper()
    return TEAM_CODE_ALIASES.get(c, c)


DIVS_MASTER: dict[str, list[str]] = {
    "Pacific": ["ANA", "CGY", "EDM", "LAK", "SEA", "SJS", "VAN", "VGK"],
    "Central": ["CHI", "COL", "DAL", "MIN", "NSH", "STL", "WPG", "UTA"],
    "Atlantic": ["BOS", "BUF", "DET", "FLA", "MTL", "OTT", "TBL", "TOR"],
    "Metro": ["CAR", "CBJ", "NJD", "NYI", "NYR", "PHI", "PIT", "WSH"],
}
WEST_DIVS = {"Pacific", "Central"}

TEAM_TO_DIV: dict[str, str] = {}
TEAM_TO_CONF: dict[str, str] = {}
for div, lst in DIVS_MASTER.items():
    for c in lst:
        TEAM_TO_DIV[c] = div
        TEAM_TO_CONF[c] = "West" if div in WEST_DIVS else "East"


def division_columns_for_codes(codes: set[str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for div, lst in DIVS_MASTER.items():
        present = [c for c in lst if c in codes]
        present.sort(key=lambda c: (TEAM_NAMES.get(c, c), c))
        out[div] = present
    return out
