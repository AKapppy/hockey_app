from __future__ import annotations

import datetime as dt
import tkinter as tk
import tkinter.font as tkfont
import xml.etree.ElementTree as ET
from tkinter import ttk
from pathlib import Path
from typing import Any, Callable

from hockey_app.config import END_DATE, SEASON, SEASON_PROBE_DATE, TEAM_NAMES, canon_team_code
from hockey_app.data.cache import DiskCache
from hockey_app.data.nhl_api import NHLApi
from hockey_app.data.paths import cache_dir, nhl_dir, pwhl_dir
from hockey_app.data.pwhl_api import PWHLApi
from hockey_app.data.xml_cache import read_team_stats_xml, write_team_stats_xml

PHASES = ["preseason", "regular", "postseason"]
PHASE_LABEL = {
    "preseason": "Preseason",
    "regular": "Regular Season",
    "postseason": "Postseason",
}

PWHL_NAMES: dict[str, str] = {
    "BOS": "Boston Fleet",
    "MIN": "Minnesota Frost",
    "MTL": "Montreal Victoire",
    "NY": "New York Sirens",
    "OTT": "Ottawa Charge",
    "TOR": "Toronto Sceptres",
    "VAN": "Vancouver",
    "SEA": "Seattle",
}

PWHL_LOGOS_DIR = Path(__file__).resolve().parents[2] / "assets" / "pwhl_logos"
PWHL_CODE_ALIASES: dict[str, str] = {"MON": "MTL", "NYC": "NY"}
_PWHL_IMG_CACHE: dict[tuple[str, int], Any] = {}

TEAM_STATS_COLS: list[tuple[str, str]] = [
    ("record", "RECORD"),
    ("gp", "GP"),
    ("w", "W"),
    ("l", "L"),
    ("pts", "PTS"),
    ("gf", "GF"),
    ("ga", "GA"),
    ("gd", "GD"),
    ("p_pct", "P%"),
    ("w_pct", "W%"),
]
INVERSE_HEAT_COLS: set[str] = {"l", "ga"}

HEADER_HELP: dict[str, str] = {
    "GP": "Games Played",
    "W": "Wins",
    "L": "Losses",
    "PTS": "Points",
    "GF": "Goals For",
    "GA": "Goals Against",
    "GD": "Goal Differential",
    "P/G": "Points Per Game",
    "P%": "Points Percentage",
    "W%": "Win Percentage",
}


def _is_final_state(state: str) -> bool:
    s = str(state or "").upper()
    return s in {"FINAL", "OFF"} or s.startswith("FINAL")


def _is_nhl_extra(g: dict[str, Any]) -> bool:
    pdx = g.get("periodDescriptor") or {}
    ptype = str(pdx.get("periodType") or "").upper()
    if ptype in {"OT", "SO"}:
        return True
    go = g.get("gameOutcome") or {}
    lp = str(go.get("lastPeriodType") or "").upper()
    return lp in {"OT", "SO"}


def _team_order(league: str) -> list[str]:
    league_u = str(league).upper()
    if league_u == "PWHL":
        return sorted(PWHL_NAMES.keys(), key=lambda c: (PWHL_NAMES.get(c, c), c))
    teams = [canon_team_code(c) for c in TEAM_NAMES.keys()]
    return sorted(set(teams), key=lambda c: (TEAM_NAMES.get(c, c), c))


def _norm_pwhl_code(code: str) -> str:
    c = str(code or "").strip().upper()
    return PWHL_CODE_ALIASES.get(c, c)


def _pwhl_logo_paths(code: str) -> list[Path]:
    c = _norm_pwhl_code(code)
    aliases = {
        "BOS": ("boston", "fleet", "boston_fleet"),
        "MIN": ("minnesota", "frost", "minnesota_frost"),
        "MTL": ("montreal", "victoire", "montreal_victoire", "montreal_victorie", "mon"),
        "NY": ("new_york", "sirens", "new_york_sirens", "ny_sirens"),
        "OTT": ("ottawa", "charge", "ottawa_charge"),
        "TOR": ("toronto", "sceptres", "toronto_sceptres"),
        "VAN": ("vancouver", "goldeneyes", "vancouver_goldeneyes"),
        "SEA": ("seattle", "torrent", "seattle_torrent"),
    }
    names = [c, c.lower(), f"pwhl_{c}", f"pwhl_{c.lower()}"]
    names.extend(aliases.get(c, ()))
    return [PWHL_LOGOS_DIR / f"{n}.png" for n in names]


def _pwhl_logo_get(code: str, *, height: int, master: tk.Misc) -> Any:
    c = _norm_pwhl_code(code)
    key = (c, int(height))
    if key in _PWHL_IMG_CACHE:
        return _PWHL_IMG_CACHE[key]
    for p in _pwhl_logo_paths(c):
        if not p.exists():
            continue
        try:
            img = tk.PhotoImage(master=master, file=str(p))
            h0 = int(img.height())
            if h0 > 0 and h0 > int(height):
                factor = max(1, int(round(h0 / max(1, int(height)))))
                img = img.subsample(factor)
            _PWHL_IMG_CACHE[key] = img
            return img
        except Exception:
            continue
    return None


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = str(h).lstrip("#")
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


def _heat_color_from_rank01(t: float, bg_hex: str = "#262626") -> str:
    t = max(0.0, min(1.0, t))
    t = round(t * 31) / 31
    if t <= 0.5:
        u = t * 2.0
        rgb = (255, int(255 * u), 0)
    else:
        u = (t - 0.5) * 2.0
        rgb = (int(255 * (1.0 - u)), 255, 0)
    heat_darken, heat_blend_bg = 0.56, 0.12
    r, g, b = rgb
    r, g, b = int(r * heat_darken), int(g * heat_darken), int(b * heat_darken)
    r, g, b = _hex_to_rgb(_blend(_rgb_to_hex(r, g, b), bg_hex, heat_blend_bg))
    return _rgb_to_hex(r, g, b)


def _safe_float(v: Any) -> float | None:
    try:
        return float(v)
    except Exception:
        return None


def _empty_stats(teams: list[str]) -> dict[str, dict[str, float]]:
    return {
        t: {
            "gp": 0.0,
            "w": 0.0,
            "l": 0.0,
            "wot": 0.0,
            "lot": 0.0,
            "wso": 0.0,
            "lso": 0.0,
            "pts": 0.0,
            "gf": 0.0,
            "ga": 0.0,
            "gd": 0.0,
            "ppgf": 0.0,
            "ppga": 0.0,
            "shgf": 0.0,
            "shga": 0.0,
            "pct": 0.0,
        }
        for t in teams
    }


def _update_game_stats(league: str, stats: dict[str, dict[str, float]], game: dict[str, Any]) -> None:
    away = game.get("awayTeam") or {}
    home = game.get("homeTeam") or {}
    ac = canon_team_code(str(away.get("abbrev") or away.get("abbreviation") or "").upper())
    hc = canon_team_code(str(home.get("abbrev") or home.get("abbreviation") or "").upper())
    if ac not in stats or hc not in stats:
        return
    if not _is_final_state(str(game.get("gameState") or game.get("gameStatus") or "")):
        return

    try:
        a = int(away.get("score") or 0)
        h = int(home.get("score") or 0)
    except Exception:
        return

    stats[ac]["gp"] += 1
    stats[hc]["gp"] += 1
    stats[ac]["gf"] += float(a)
    stats[ac]["ga"] += float(h)
    stats[hc]["gf"] += float(h)
    stats[hc]["ga"] += float(a)
    stats[ac]["gd"] = stats[ac]["gf"] - stats[ac]["ga"]
    stats[hc]["gd"] = stats[hc]["gf"] - stats[hc]["ga"]

    league_u = str(league).upper()
    winner = ac if a > h else hc
    loser = hc if winner == ac else ac

    if league_u == "NHL":
        # Special teams from cached score payload goals list (cache-only, fast).
        # This avoids requiring play-by-play cache for PPGF/PPGA/SHGF/SHGA.
        goals = game.get("goals") or []
        if isinstance(goals, list):
            for gl in goals:
                if not isinstance(gl, dict):
                    continue
                scorer = canon_team_code(str(gl.get("teamAbbrev") or "").upper())
                if scorer not in stats:
                    continue
                against = hc if scorer == ac else ac
                strength = str(gl.get("strength") or "").upper()
                if "PP" in strength:
                    stats[scorer]["ppgf"] += 1.0
                    if against in stats:
                        stats[against]["ppga"] += 1.0
                elif "SH" in strength:
                    stats[scorer]["shgf"] += 1.0
                    if against in stats:
                        stats[against]["shga"] += 1.0

        pdx = game.get("periodDescriptor") or {}
        end_type = str(pdx.get("periodType") or "").upper()
        if end_type not in {"OT", "SO"}:
            go = game.get("gameOutcome") or {}
            end_type = str(go.get("lastPeriodType") or "").upper()

        if end_type == "SO":
            stats[winner]["wso"] += 1
            stats[loser]["lso"] += 1
            stats[winner]["pts"] += 2
            stats[loser]["pts"] += 1
        elif end_type == "OT":
            stats[winner]["wot"] += 1
            stats[loser]["lot"] += 1
            stats[winner]["pts"] += 2
            stats[loser]["pts"] += 1
        else:
            stats[winner]["w"] += 1
            stats[loser]["l"] += 1
            stats[winner]["pts"] += 2

        for t in (ac, hc):
            gp = stats[t]["gp"]
            stats[t]["pct"] = (stats[t]["pts"] / (gp * 2.0)) if gp > 0 else 0.0
        return

    status = str(game.get("statusText") or "").upper()
    if "SO" in status:
        stats[winner]["wso"] += 1
        stats[loser]["lso"] += 1
        stats[winner]["pts"] += 2
        stats[loser]["pts"] += 1
    elif "OT" in status:
        stats[winner]["wot"] += 1
        stats[loser]["lot"] += 1
        stats[winner]["pts"] += 2
        stats[loser]["pts"] += 1
    else:
        stats[winner]["w"] += 1
        stats[loser]["l"] += 1
        stats[winner]["pts"] += 3

    for t in (ac, hc):
        gp = stats[t]["gp"]
        stats[t]["pct"] = (stats[t]["pts"] / (gp * 3.0)) if gp > 0 else 0.0


def _phase_ranges_nhl(
    api: NHLApi,
    today: dt.date,
    *,
    probe_date: dt.date | None = None,
) -> tuple[dict[str, tuple[dt.date, dt.date]], str]:
    b = api.get_season_boundaries(probe_date or today)
    season_start = b.preseason_start or b.first_scheduled_game or b.regular_start or today
    season_end = min(today, b.last_scheduled_game or today)
    reg_start = b.regular_start or season_start
    po_start = b.playoffs_start

    ranges: dict[str, tuple[dt.date, dt.date]] = {}
    pre_end = reg_start - dt.timedelta(days=1)
    if season_start <= pre_end:
        ranges["preseason"] = (season_start, min(pre_end, season_end))

    reg_end = season_end
    if po_start is not None:
        reg_end = min(reg_end, po_start - dt.timedelta(days=1))
    if reg_start <= reg_end:
        ranges["regular"] = (reg_start, reg_end)

    if po_start is not None and po_start <= season_end:
        ranges["postseason"] = (po_start, season_end)

    if po_start is not None and today >= po_start:
        default = "postseason"
    elif today >= reg_start:
        default = "regular"
    else:
        default = "preseason"
    return ranges, default


def _phase_ranges_pwhl(
    api: PWHLApi,
    today: dt.date,
    *,
    probe_date: dt.date | None = None,
) -> tuple[dict[str, tuple[dt.date, dt.date]], str]:
    p_start, p_end = api.get_season_boundaries(probe_date or today, allow_network=True)
    start = p_start or today
    end = min(today, p_end) if isinstance(p_end, dt.date) else today
    if end < start:
        end = start
    return {"regular": (start, end)}, "regular"


def _load_nhl_games_for_date(api: NHLApi, d: dt.date) -> list[dict[str, Any]]:
    iso = d.isoformat()
    for key in (f"nhl/score/final/{iso}", f"nhl/score/live/{iso}"):
        try:
            hit = api.cache.get_json(key, ttl_s=None)  # type: ignore[attr-defined]
        except Exception:
            hit = None
        if isinstance(hit, dict):
            return list((hit.get("games") or []))
    return []


def _load_pwhl_games_for_date(api: PWHLApi, d: dt.date) -> list[dict[str, Any]]:
    try:
        return list(api.get_games_for_date(d, allow_network=False))
    except Exception:
        return []


def _apply_nhl_special_teams_from_pbp_cache(
    *,
    nhl_api: NHLApi,
    stats: dict[str, dict[str, float]],
    game_map: dict[int, tuple[str, str]],
) -> None:
    for gid, teams in game_map.items():
        ac, hc = teams
        if ac not in stats or hc not in stats:
            continue
        pbp = None
        for key in (f"nhl/pbp/final/{gid}", f"nhl/pbp/live/{gid}"):
            try:
                hit = nhl_api.cache.get_json(key, ttl_s=None)  # type: ignore[attr-defined]
            except Exception:
                hit = None
            if isinstance(hit, dict):
                pbp = hit
                break
        if not isinstance(pbp, dict):
            continue
        plays = pbp.get("plays") or pbp.get("allPlays") or []
        for p in plays:
            tkey = str(p.get("typeDescKey") or p.get("result", {}).get("eventTypeId") or "").lower()
            if tkey != "goal" and str(p.get("result", {}).get("eventTypeId") or "").upper() != "GOAL":
                continue
            det = p.get("details") or {}
            scorer = canon_team_code(
                str(
                    det.get("eventOwnerTeamAbbrev")
                    or det.get("teamAbbrev")
                    or (p.get("team") or {}).get("abbrev")
                    or ""
                ).upper()
            )
            if scorer not in stats:
                continue
            against = hc if scorer == ac else ac
            strength = str(det.get("strength") or det.get("strengthCode") or det.get("situationCode") or "").upper()
            if "PP" in strength:
                stats[scorer]["ppgf"] += 1.0
                stats[against]["ppga"] += 1.0
            elif "SH" in strength:
                stats[scorer]["shgf"] += 1.0
                stats[against]["shga"] += 1.0


def _compute_phase_rows(
    *,
    league: str,
    phase_ranges: dict[str, tuple[dt.date, dt.date]],
    nhl_api: NHLApi,
    pwhl_api: PWHLApi,
) -> dict[str, dict[str, Any]]:
    teams = _team_order(league)
    out: dict[str, dict[str, Any]] = {}
    league_u = str(league).upper()
    season_games = 30 if league_u == "PWHL" else 82

    for ph in PHASES:
        if ph not in phase_ranges:
            continue
        start, end = phase_ranges[ph]
        if end < start:
            continue
        stats = _empty_stats(teams)
        dates: list[dt.date] = []
        rows_by_date: dict[dt.date, list[dict[str, Any]]] = {}
        d = start
        while d <= end:
            games = _load_pwhl_games_for_date(pwhl_api, d) if league_u == "PWHL" else _load_nhl_games_for_date(nhl_api, d)
            for g in games:
                _update_game_stats(league_u, stats, g)
            rows: list[dict[str, Any]] = []
            for t in teams:
                s = stats[t]
                gp = int(s["gp"])
                rw = int(s["w"])
                otw = int(s["wot"])
                sow = int(s["wso"])
                rl = int(s["l"])
                otl = int(s["lot"])
                sol = int(s["lso"])
                w = rw + otw + sow
                l = rl + otl + sol
                ot_sow = otw + sow
                ot_sol = otl + sol
                pts = int(s["pts"])
                gf = int(s["gf"])
                ga = int(s["ga"])
                gd = int(s["gd"])
                gr = max(0, season_games - gp)
                max_ppg = 3.0 if league_u == "PWHL" else 2.0
                p_pct = (float(pts) / (float(gp) * max_ppg)) if gp > 0 else 0.0
                w_pct = (float(w) / float(gp)) if gp > 0 else 0.0
                mxp = pts + gr * (3 if league_u == "PWHL" else 2)

                rows.append(
                    {
                        "team": t,
                        "record": f"{w}-{l}-{ot_sol}\u2014{pts}",
                        "gp": gp,
                        "gr": gr,
                        "w": w,
                        "rw": rw,
                        "ot_sow": ot_sow,
                        "otw": otw,
                        "sow": sow,
                        "l": l,
                        "rl": rl,
                        "ot_sol": ot_sol,
                        "otl": otl,
                        "sol": sol,
                        "enotl": 0,
                        "pts": pts,
                        "mxp": mxp,
                        "gf": gf,
                        "ga": ga,
                        "gd": gd,
                        "ppgf": int(s["ppgf"]),
                        "ppga": int(s["ppga"]),
                        "shgf": int(s["shgf"]),
                        "shga": int(s["shga"]),
                        "p_pct": p_pct,
                        "w_pct": w_pct,
                    }
                )
            dates.append(d)
            rows_by_date[d] = rows
            d += dt.timedelta(days=1)
        out[ph] = {"dates": dates, "rows_by_date": rows_by_date}
    return out


def _nhl_game_logs_from_xml() -> dict[str, list[dict[str, Any]]]:
    xml_path = cache_dir() / "online" / "xml" / str(SEASON) / "games.xml"
    if not xml_path.exists():
        return {}
    try:
        root = ET.parse(xml_path).getroot()
    except Exception:
        return {}

    out: dict[str, list[dict[str, Any]]] = {}
    for day_node in root.findall("day"):
        day_iso = str(day_node.get("date") or "").strip()
        try:
            day = dt.date.fromisoformat(day_iso[:10])
        except Exception:
            continue
        for g in day_node.findall("game"):
            if str(g.get("league") or "").strip().upper() != "NHL":
                continue
            state = str(g.get("state") or "").strip().upper()
            if not _is_final_state(state):
                continue
            away = canon_team_code(str(g.get("away_code") or "").strip().upper())
            home = canon_team_code(str(g.get("home_code") or "").strip().upper())
            if away not in TEAM_NAMES or home not in TEAM_NAMES:
                continue
            try:
                away_score = int(float(g.get("away_score") or 0))
                home_score = int(float(g.get("home_score") or 0))
            except Exception:
                continue
            if away_score == home_score:
                continue
            status_txt = str(g.get("status_text") or "").strip().upper()
            ot_or_so = ("OT" in status_txt) or ("SO" in status_txt)

            away_result = "W" if away_score > home_score else ("OTL" if ot_or_so else "L")
            home_result = "W" if home_score > away_score else ("OTL" if ot_or_so else "L")

            out.setdefault(away, []).append(
                {
                    "date": day,
                    "home": False,
                    "opponent": home,
                    "gf": away_score,
                    "ga": home_score,
                    "gd": away_score - home_score,
                    "result": away_result,
                }
            )
            out.setdefault(home, []).append(
                {
                    "date": day,
                    "home": True,
                    "opponent": away,
                    "gf": home_score,
                    "ga": away_score,
                    "gd": home_score - away_score,
                    "result": home_result,
                }
            )

    for team_code in list(out.keys()):
        out[team_code].sort(key=lambda r: (r.get("date") or dt.date.min, str(r.get("opponent") or "")))
    return out


def _record_from_logs(rows: list[dict[str, Any]]) -> tuple[int, int, int]:
    w = 0
    l = 0
    otl = 0
    for r in rows:
        res = str(r.get("result") or "").upper()
        if res == "W":
            w += 1
        elif res == "OTL":
            otl += 1
        elif res == "L":
            l += 1
    return w, l, otl


def _team_stats_row_has_data(row: dict[str, Any]) -> bool:
    try:
        return int(row.get("gp") or 0) > 0
    except Exception:
        return False


def populate_team_stats_tab(
    parent: tk.Frame,
    *,
    league: str,
    get_selected_team_code: Callable[[], str | None],
    set_selected_team_code: Callable[[str | None], None] | None = None,
    logo_bank: Any | None = None,
) -> dict[str, Callable[[], None]]:
    for child in parent.winfo_children():
        child.destroy()

    top = tk.Frame(parent, bg="#2c2c2c")
    top.pack(fill="x", padx=8, pady=(8, 6))
    holder = tk.Frame(parent, bg="#2c2c2c")
    holder.pack(fill="both", expand=True, padx=8, pady=(0, 8))

    league_u = str(league or "NHL").upper()
    cache = DiskCache(nhl_dir(SEASON))
    nhl_api = NHLApi(cache)
    pwhl_api = PWHLApi(DiskCache(pwhl_dir(SEASON)))
    today = END_DATE

    if league_u == "PWHL":
        phase_ranges, default_phase = _phase_ranges_pwhl(pwhl_api, today, probe_date=SEASON_PROBE_DATE)
    else:
        phase_ranges, default_phase = _phase_ranges_nhl(nhl_api, today, probe_date=SEASON_PROBE_DATE)

    phase_rows = _compute_phase_rows(
        league=league_u,
        phase_ranges=phase_ranges,
        nhl_api=nhl_api,
        pwhl_api=pwhl_api,
    )
    if not phase_rows:
        phase_rows = read_team_stats_xml(season=SEASON, league=league_u) or {}
    try:
        if phase_rows:
            write_team_stats_xml(
                season=SEASON,
                league=league_u,
                phase_rows=phase_rows,
            )
    except Exception:
        pass
    available_phases = [ph for ph in PHASES if phase_rows.get(ph) and phase_rows[ph].get("dates")] or ["regular"]
    team_logs = _nhl_game_logs_from_xml() if league_u == "NHL" else {}

    state: dict[str, Any] = {
        "phase": default_phase if default_phase in available_phases else available_phases[0],
        "sort_col": "team",
        "desc": False,
        "rows": [],
        "x_starts": {},
        "col_w": {},
        "team_w": 0,
    }
    btns: dict[str, tk.Label] = {}
    live_imgs: list[Any] = []
    tip: tk.Toplevel | None = None
    tip_job: str | None = None

    phase_bar = tk.Frame(top, bg="#2c2c2c")
    phase_bar.pack(side="left", anchor="w")

    for i, ph in enumerate(available_phases):
        b = tk.Label(phase_bar, text=PHASE_LABEL.get(ph, ph.title()), padx=10, pady=5, cursor="hand2", bg="#2f2f2f", fg="#f0f0f0")
        b.pack(side="left", padx=(0 if i == 0 else 8, 0))
        btns[ph] = b

    form_box = tk.Frame(parent, bg="#202020", bd=1, relief="solid")
    form_title_lbl = tk.Label(
        form_box,
        text="Recent Form",
        bg="#202020",
        fg="#f0f0f0",
        font=("TkDefaultFont", 12, "bold"),
        anchor="w",
        justify="left",
    )
    form_title_lbl.pack(fill="x", padx=10, pady=(8, 3))
    form_body_lbl = tk.Label(
        form_box,
        text="[NF]",
        bg="#202020",
        fg="#d7d7d7",
        font=("TkDefaultFont", 11),
        anchor="w",
        justify="left",
        wraplength=760,
    )
    form_body_lbl.pack(fill="x", padx=10, pady=(0, 8))
    form_box_visible = False

    def _set_form_box_visible(visible: bool) -> None:
        nonlocal form_box_visible
        if visible and not form_box_visible:
            form_box.place(relx=1.0, x=-12, y=12, anchor="ne")
            form_box.lift()
            form_box_visible = True
        elif not visible and form_box_visible:
            form_box.place_forget()
            form_box_visible = False

    def _reposition_form_box(_e=None) -> None:
        if form_box_visible:
            form_box.place_configure(relx=1.0, x=-12, y=12, anchor="ne")
            form_box.lift()

    parent.bind("<Configure>", _reposition_form_box, add="+")

    left = tk.Frame(holder, bg="#2c2c2c")
    right = tk.Frame(holder, bg="#2c2c2c")
    left.grid(row=0, column=0, sticky="nsew")
    right.grid(row=0, column=1, sticky="nsew")
    holder.grid_rowconfigure(0, weight=1)
    holder.grid_columnconfigure(1, weight=1)

    team_canvas = tk.Canvas(left, bg="#2a2a2a", highlightthickness=0)
    data_canvas = tk.Canvas(right, bg="#262626", highlightthickness=0)
    ys = ttk.Scrollbar(right, orient="vertical")
    xs = ttk.Scrollbar(right, orient="horizontal")
    data_canvas.grid(row=0, column=0, sticky="nsew")
    ys.grid(row=0, column=1, sticky="ns")
    xs.grid(row=1, column=0, sticky="ew")
    team_canvas.grid(row=0, column=0, sticky="nsew")
    left.grid_rowconfigure(0, weight=1)
    left.grid_columnconfigure(0, weight=1)
    right.grid_rowconfigure(0, weight=1)
    right.grid_columnconfigure(0, weight=1)

    font = tkfont.nametofont("TkDefaultFont")
    header_font = tkfont.Font(root=parent.winfo_toplevel(), font=font)
    header_h = 28
    cell_h = 26
    team_w = 120
    table_cols = [k for k, _ in TEAM_STATS_COLS]
    table_labels = {k: lbl for k, lbl in TEAM_STATS_COLS}

    def _text_px(s: str) -> int:
        try:
            return int(font.measure(str(s)))
        except Exception:
            return 8 * len(str(s))

    def _header_px(s: str) -> int:
        try:
            return int(header_font.measure(str(s)))
        except Exception:
            return 8 * len(str(s))

    def _fmt(col: str, v: Any) -> str:
        if v in (None, ""):
            return ""
        if col in {"p_pct", "w_pct"}:
            try:
                return f"{float(v) * 100:.1f}%"
            except Exception:
                return str(v)
        if isinstance(v, float) and abs(v - int(v)) < 1e-9:
            return str(int(v))
        return str(v)

    def _recent_form_text(team_code: str) -> tuple[str, str]:
        code = str(team_code or "").upper().strip()
        if league_u != "NHL":
            return ("Recent Form", "[NF]")
        rows_all = [r for r in team_logs.get(code, []) if isinstance(r, dict)]
        if not rows_all:
            return (f"Recent Form - {code or '[NF]'}", "[NF]")

        last5 = rows_all[-5:]
        last10 = rows_all[-10:]
        w5, l5, otl5 = _record_from_logs(last5)
        w10, l10, otl10 = _record_from_logs(last10)
        gf5 = sum(int(r.get("gf") or 0) for r in last5)
        ga5 = sum(int(r.get("ga") or 0) for r in last5)
        gf10 = sum(int(r.get("gf") or 0) for r in last10)
        ga10 = sum(int(r.get("ga") or 0) for r in last10)

        home_rows = [r for r in rows_all if bool(r.get("home"))]
        road_rows = [r for r in rows_all if not bool(r.get("home"))]
        wh, lh, otlh = _record_from_logs(home_rows)
        wr, lr, otlr = _record_from_logs(road_rows)

        trend = [int(r.get("gd") or 0) for r in last5]
        trend_txt = ", ".join((f"{v:+d}" if int(v) != 0 else "0") for v in trend) if trend else "[NF]"
        trend_net = sum(trend) if trend else 0

        lines = [
            f"L5: {w5}-{l5}-{otl5} ({gf5}-{ga5})",
            f"L10: {w10}-{l10}-{otl10} ({gf10}-{ga10})",
            f"Home: {wh}-{lh}-{otlh} | Away: {wr}-{lr}-{otlr}",
            f"GD Trend: {trend_txt} (Net {trend_net:+d})",
        ]
        return (f"Recent Form - {code}", "\n".join(lines))

    def _rows_sorted(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        col = str(state["sort_col"])
        desc = bool(state["desc"])
        if col in {"team", "city", "name"}:
            return sorted(rows, key=lambda r: str(r.get(col, "")), reverse=desc)
        if col == "record":
            return sorted(
                rows,
                key=lambda r: (
                    int(r.get("pts") or 0),
                    _safe_float(r.get("w_pct")) if _safe_float(r.get("w_pct")) is not None else 0.0,
                    int(r.get("gd") or 0),
                    int(r.get("gf") or 0),
                ),
                reverse=True,
            )
        return sorted(
            rows,
            key=lambda r: (
                (_safe_float(r.get(col)) if _safe_float(r.get(col)) is not None else float("-inf" if desc else "inf")),
                str(r.get("team", "")),
            ),
            reverse=desc,
        )

    def _phase_heat_ranks(rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
        out: dict[str, dict[str, float]] = {}
        for col in table_cols:
            vals: list[tuple[str, float]] = []
            for r in rows:
                fv = _safe_float(r.get(col))
                if fv is None:
                    continue
                vals.append((str(r.get("team", "")), fv))
            if len(vals) <= 1:
                out[col] = {t: 0.5 for t, _ in vals}
                continue
            only = [v for _t, v in vals]
            vmin = min(only)
            vmax = max(only)
            ranks: dict[str, float] = {}
            if abs(vmax - vmin) < 1e-12:
                for t, _v in vals:
                    ranks[t] = 0.5
            else:
                span = float(vmax - vmin)
                for t, v in vals:
                    ranks[t] = float((v - vmin) / span)
            out[col] = ranks
        return out

    def _compute_widths(rows: list[dict[str, Any]]) -> tuple[int, dict[str, int]]:
        nonlocal team_w
        max_logo = 0
        for r in rows:
            code = str(r.get("team", ""))
            img = None
            try:
                if league_u == "PWHL":
                    img = _pwhl_logo_get(code, height=16, master=team_canvas)
                else:
                    if logo_bank is not None:
                        img = logo_bank.get(code, height=16, dim=False)
            except Exception:
                img = None
            if img is not None:
                try:
                    max_logo = max(max_logo, int(img.width()))
                except Exception:
                    pass
        max_text = max((_text_px(str(r.get("team", ""))) for r in rows), default=_text_px("Team"))
        team_w = max(76, min(110, max_text + max_logo + 8))

        widths: dict[str, int] = {}
        for col in table_cols:
            hdr = table_labels.get(col, col)
            w = _header_px(hdr) + 14
            for r in rows:
                w = max(w, _text_px(_fmt(col, r.get(col))) + 14)
            if col == "record":
                widths[col] = max(92, min(140, w))
            else:
                widths[col] = max(48, min(90, w))
        return team_w, widths

    def _render() -> None:
        nonlocal live_imgs
        team_canvas.delete("all")
        data_canvas.delete("all")
        live_imgs = []

        phase_key = str(state["phase"])
        phase_blob = phase_rows.get(phase_key, {})
        dates: list[dt.date] = list(phase_blob.get("dates") or [])
        rows_map: dict[dt.date, list[dict[str, Any]]] = dict(phase_blob.get("rows_by_date") or {})
        if not dates:
            rows = []
        else:
            cur_date = dates[-1]
            rows = list(rows_map.get(cur_date) or [])
        rows = [r for r in rows if isinstance(r, dict) and _team_stats_row_has_data(r)]
        rows = _rows_sorted(rows)
        state["rows"] = rows
        heat_ranks = _phase_heat_ranks(rows)
        tw, col_w = _compute_widths(rows)

        total_h = header_h + len(rows) * cell_h
        x_starts: dict[str, int] = {}
        x = 0
        for col in table_cols:
            x_starts[col] = x
            x += int(col_w[col])
        total_w = x

        team_canvas.create_rectangle(0, 0, tw, header_h, fill="#2f2f2f", outline="#323232")
        team_canvas.create_text(tw / 2, header_h / 2, text="Team", fill="#f0f0f0", font=header_font, anchor="center")

        for col in table_cols:
            x0 = x_starts[col]
            x1 = x0 + int(col_w[col])
            data_canvas.create_rectangle(x0, 0, x1, header_h, fill="#2f2f2f", outline="#323232")
            data_canvas.create_text((x0 + x1) / 2, header_h / 2, text=table_labels[col], fill="#f0f0f0", font=header_font, anchor="center")

        sel = str(get_selected_team_code() or "").upper().strip()
        row_codes = {str(r.get("team") or "").upper().strip() for r in rows if isinstance(r, dict)}
        show_form = league_u == "NHL" and bool(sel) and sel in row_codes
        _set_form_box_visible(show_form)
        if show_form:
            title_txt, body_txt = _recent_form_text(sel)
            form_title_lbl.configure(text=title_txt)
            form_body_lbl.configure(text=body_txt if body_txt else "[NF]")

        for i, r in enumerate(rows):
            y0 = header_h + i * cell_h
            y1 = y0 + cell_h
            code = str(r.get("team", "")).upper().strip()
            team_fill = "#2a2a2a"
            team_canvas.create_rectangle(0, y0, tw, y1, fill=team_fill, outline="#323232")

            img = None
            if league_u == "PWHL":
                img = _pwhl_logo_get(code, height=16, master=team_canvas)
            elif logo_bank is not None:
                try:
                    img = logo_bank.get(code, height=16, dim=False)
                except Exception:
                    img = None
            if img is not None:
                live_imgs.append(img)
            gap = 3
            pad_lr = 2
            text_w = _text_px(code)
            img_w = int(img.width()) if img else 0
            group_w = text_w + (gap + img_w if img else 0)
            start_x = max(pad_lr, (tw - group_w) / 2)
            team_canvas.create_text(start_x, (y0 + y1) / 2, text=code, fill="#f0f0f0", anchor="w")
            if img is not None:
                x_logo = start_x + text_w + gap + img_w / 2
                x_logo = min(x_logo, tw - pad_lr - img_w / 2)
                team_canvas.create_image(x_logo, (y0 + y1) / 2, image=img, anchor="center")

            for col in table_cols:
                x0 = x_starts[col]
                x1 = x0 + int(col_w[col])
                sval = _fmt(col, r.get(col))
                rank_map = heat_ranks.get(col, {})
                has_numeric = code in rank_map
                if sval == "":
                    fill = "#262626"
                    txt_col = "#f0f0f0"
                elif has_numeric:
                    if col == "gp":
                        fill = "#262626"
                        txt_col = "#f0f0f0"
                    else:
                        t = rank_map.get(code, 0.5)
                        if col in INVERSE_HEAT_COLS:
                            t = 1.0 - t
                        fill = _heat_color_from_rank01(t)
                        txt_col = "#111111" if _rel_luminance(fill) > 0.40 else "#f0f0f0"
                else:
                    fill = "#262626"
                    txt_col = "#f0f0f0"
                if sel and code == sel:
                    fill = _blend(fill, "#ffffff", 0.08)
                data_canvas.create_rectangle(x0, y0, x1, y1, fill=fill, outline="#323232")
                if sval:
                    data_canvas.create_text((x0 + x1) / 2, (y0 + y1) / 2, text=sval, fill=txt_col, anchor="center")

            if sel and code == sel:
                team_canvas.create_rectangle(1, y0 + 1, tw - 1, y1 - 1, outline="#f0f0f0", width=2)
                data_canvas.create_rectangle(0, y0 + 1, total_w, y1 - 1, outline="#f0f0f0", width=2)

        team_canvas.configure(scrollregion=(0, 0, tw, total_h + 1), width=tw)
        data_canvas.configure(scrollregion=(0, 0, total_w, total_h + 1))
        state["x_starts"] = x_starts
        state["col_w"] = col_w
        state["team_w"] = tw
        # Prevent "splitting" team and record areas when full table fits.
        data_canvas.update_idletasks()
        view_w = int(data_canvas.winfo_width() or 0)
        if view_w >= total_w:
            data_canvas.xview_moveto(0.0)
            xs.grid_remove()
        else:
            xs.grid()
        try:
            team_canvas.yview_moveto(data_canvas.yview()[0])
        except Exception:
            pass

        for ph, b in btns.items():
            b.configure(bg="#3a3a3a" if ph == state["phase"] else "#2f2f2f", fg="#f0f0f0")

    def _set_phase(ph: str) -> None:
        state["phase"] = ph
        state["sort_col"] = "team"
        state["desc"] = False
        _render()

    def _on_header_click(event) -> None:
        x = float(data_canvas.canvasx(event.x))
        y = float(data_canvas.canvasy(event.y))
        if y > header_h:
            return
        rows = list(state.get("rows") or [])
        _tw, col_w = _compute_widths(rows)
        cur = 0
        hit = None
        for col in table_cols:
            nxt = cur + int(col_w[col])
            if cur <= x < nxt:
                hit = col
                break
            cur = nxt
        if not hit:
            return
        state["sort_col"] = hit
        if hit in {"team"}:
            state["desc"] = False
        elif hit in INVERSE_HEAT_COLS:
            state["desc"] = False
        else:
            state["desc"] = True
        _render()

    def _on_team_click(event) -> None:
        y = float(team_canvas.canvasy(event.y))
        if y <= header_h:
            if state["sort_col"] == "team":
                state["desc"] = not bool(state["desc"])
            else:
                state["sort_col"] = "team"
                state["desc"] = False
            _render()
            return
        rows = list(state.get("rows") or [])
        idx = int((y - header_h) // max(1, cell_h))
        if 0 <= idx < len(rows) and callable(set_selected_team_code):
            team = str(rows[idx].get("team", "")).upper().strip()
            if team:
                try:
                    set_selected_team_code(team)
                except Exception:
                    pass
                _render()

    def _set_y(frac: float) -> None:
        frac = max(0.0, min(1.0, float(frac)))
        team_canvas.yview_moveto(frac)
        data_canvas.yview_moveto(frac)
        ys.set(*data_canvas.yview())

    def _yview(*args):
        data_canvas.yview(*args)
        _set_y(data_canvas.yview()[0])

    ys.configure(command=_yview)
    data_canvas.configure(yscrollcommand=ys.set)
    xs.configure(command=lambda *args: data_canvas.xview(*args))

    def _hide_tip() -> None:
        nonlocal tip
        if tip is not None:
            try:
                tip.destroy()
            except Exception:
                pass
        tip = None

    def _cancel_tip_job() -> None:
        nonlocal tip_job
        if tip_job is not None:
            try:
                parent.after_cancel(tip_job)
            except Exception:
                pass
        tip_job = None

    def _schedule_tip(text: str, x_root: int, y_root: int) -> None:
        nonlocal tip, tip_job
        _cancel_tip_job()
        _hide_tip()
        if not text:
            return
        def _show() -> None:
            nonlocal tip, tip_job
            tip_job = None
            tip = tk.Toplevel(parent.winfo_toplevel())
            tip.overrideredirect(True)
            tip.configure(bg="#2c2c2c")
            tip.geometry(f"+{x_root + 14}+{y_root + 14}")
            tk.Label(
                tip,
                text=text,
                bg="#2f2f2f",
                fg="#f0f0f0",
                padx=10,
                pady=6,
                justify="left",
                bd=0,
                highlightthickness=1,
                highlightbackground="#323232",
            ).pack()
        tip_job = parent.after(700, _show)

    def _scroll_vertical(units: int):
        data_canvas.yview_scroll(units, "units")
        _set_y(data_canvas.yview()[0])

    def _scroll_horizontal(units: int):
        sr = data_canvas.cget("scrollregion")
        if sr:
            try:
                x0, _y0, x1, _y1 = map(float, str(sr).split())
                if int(data_canvas.winfo_width() or 0) >= int(x1 - x0):
                    data_canvas.xview_moveto(0.0)
                    return
            except Exception:
                pass
        data_canvas.xview_scroll(units, "units")

    def _on_mousewheel(event):
        if getattr(event, "delta", 0) == 0:
            return "break"
        _scroll_vertical(-1 if event.delta > 0 else 1)
        return "break"

    def _on_shift_mousewheel(event):
        if getattr(event, "delta", 0) == 0:
            return "break"
        _scroll_horizontal(-1 if event.delta > 0 else 1)
        return "break"

    def _on_linux_up(_event):
        _scroll_vertical(-1)
        return "break"

    def _on_linux_down(_event):
        _scroll_vertical(1)
        return "break"

    for w in (team_canvas, data_canvas):
        w.bind("<MouseWheel>", _on_mousewheel)
        w.bind("<Button-4>", _on_linux_up)
        w.bind("<Button-5>", _on_linux_down)
    data_canvas.bind("<Shift-MouseWheel>", _on_shift_mousewheel)

    def _scan_mark(canvas: tk.Canvas, event):
        canvas.scan_mark(event.x, event.y)

    def _scan_drag(canvas: tk.Canvas, event):
        canvas.scan_dragto(event.x, event.y, gain=1)
        _set_y(data_canvas.yview()[0])

    data_canvas.bind("<ButtonPress-2>", lambda e: _scan_mark(data_canvas, e), add="+")
    data_canvas.bind("<B2-Motion>", lambda e: _scan_drag(data_canvas, e), add="+")

    def _on_header_motion(event) -> None:
        y = float(data_canvas.canvasy(event.y))
        if y > header_h:
            _cancel_tip_job()
            _hide_tip()
            return
        x = float(data_canvas.canvasx(event.x))
        x_starts = dict(state.get("x_starts") or {})
        col_w = dict(state.get("col_w") or {})
        hit = None
        for c in table_cols:
            x0 = float(x_starts.get(c, 0))
            x1 = x0 + float(col_w.get(c, 0))
            if x0 <= x < x1:
                hit = c
                break
        if not hit:
            _cancel_tip_job()
            _hide_tip()
            return
        label = table_labels.get(hit, hit)
        if label in {"Team", "RECORD"}:
            _cancel_tip_job()
            _hide_tip()
            return
        _schedule_tip(HEADER_HELP.get(label, label), event.x_root, event.y_root)

    def _on_body_motion(event) -> None:
        y = float(data_canvas.canvasy(event.y))
        if y <= header_h:
            return
        rows = list(state.get("rows") or [])
        idx = int((y - header_h) // max(1, cell_h))
        if not (0 <= idx < len(rows)):
            _cancel_tip_job()
            _hide_tip()
            return
        row = rows[idx]
        x = float(data_canvas.canvasx(event.x))
        x_starts = dict(state.get("x_starts") or {})
        col_w = dict(state.get("col_w") or {})
        hit = None
        for c in table_cols:
            x0 = float(x_starts.get(c, 0))
            x1 = x0 + float(col_w.get(c, 0))
            if x0 <= x < x1:
                hit = c
                break
        if not hit:
            _cancel_tip_job()
            _hide_tip()
            return
        txt = ""
        if hit == "w":
            parts = [("RW", int(row.get("rw") or 0)), ("OTW", int(row.get("otw") or 0)), ("SOW", int(row.get("sow") or 0))]
            parts = [(k, v) for k, v in parts if v > 0]
            txt = "\n".join(f"{k}: {v}" for k, v in parts)
        elif hit == "l":
            parts = [("RL", int(row.get("rl") or 0)), ("OTL", int(row.get("otl") or 0)), ("SOL", int(row.get("sol") or 0))]
            en = int(row.get("enotl") or 0)
            if en > 0:
                parts.append(("ENOTL", en))
            parts = [(k, v) for k, v in parts if v > 0]
            txt = "\n".join(f"{k}: {v}" for k, v in parts)
        elif hit == "pts":
            txt = f"Max Points: {int(row.get('mxp') or 0)}"
        elif hit == "gf":
            ppg = int(row.get("ppgf") or 0)
            shg = int(row.get("shgf") or 0)
            evg = int(row.get("gf") or 0) - ppg - shg
            parts = [("EvG", evg), ("PPG", ppg), ("SHG", shg)]
            parts = [(k, v) for k, v in parts if v > 0]
            txt = "\n".join(f"{k}: {v}" for k, v in parts)
        elif hit == "ga":
            ppga = int(row.get("ppga") or 0)
            shga = int(row.get("shga") or 0)
            evga = int(row.get("ga") or 0) - ppga - shga
            parts = [("EvGA", evga), ("PPGA", ppga), ("SHGA", shga)]
            parts = [(k, v) for k, v in parts if v > 0]
            txt = "\n".join(f"{k}: {v}" for k, v in parts)
        if txt:
            _schedule_tip(txt, event.x_root, event.y_root)
        else:
            _cancel_tip_job()
            _hide_tip()

    def _on_leave(_event=None) -> None:
        _cancel_tip_job()
        _hide_tip()

    for ph, b in btns.items():
        b.bind("<Button-1>", lambda _e, p=ph: _set_phase(p), add="+")
    team_canvas.bind("<Button-1>", _on_team_click)
    data_canvas.bind("<Button-1>", _on_header_click)
    data_canvas.bind("<Motion>", _on_header_motion, add="+")
    data_canvas.bind("<Motion>", _on_body_motion, add="+")
    data_canvas.bind("<Leave>", _on_leave, add="+")
    team_canvas.bind("<Leave>", _on_leave, add="+")

    _render()

    def redraw() -> None:
        _render()

    def reset() -> None:
        ph = default_phase if default_phase in available_phases else available_phases[0]
        _set_phase(ph)

    return {"redraw": redraw, "reset": reset}
