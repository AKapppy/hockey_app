from __future__ import annotations

import datetime as dt
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk
from pathlib import Path
from typing import Any, Callable

from hockey_app.config import END_DATE, SEASON, SEASON_PROBE_DATE, canon_team_code
from hockey_app.data.cache import DiskCache
from hockey_app.data.nhl_api import NHLApi
from hockey_app.data.paths import nhl_dir, pwhl_dir
from hockey_app.data.pwhl_api import PWHLApi
from hockey_app.data.xml_cache import read_game_stats_xml, write_game_stats_xml
from hockey_app.ui.tabs.team_stats import (
    PHASES,
    PHASE_LABEL,
    _is_final_state,
    _load_nhl_games_for_date,
    _load_pwhl_games_for_date,
    _phase_ranges_nhl,
    _phase_ranges_pwhl,
    _team_order,
)

OUTCOME_RANK: dict[str, int] = {
    "W": 6,
    "OTW": 5,
    "SOW": 4,
    "SOL": 3,
    "OTL": 2,
    "L": 1,
    "": 0,
}


def _phase_auto_scrolls_latest(phase: str) -> bool:
    return str(phase or "").strip().lower() != "postseason"


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


def _heat_color_from_rank01(t: float, bg_hex: str = "#262626") -> str:
    # Matches predictions tab heat palette behavior.
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

PWHL_LOGOS_DIR = Path(__file__).resolve().parents[2] / "assets" / "pwhl_logos"
PWHL_CODE_ALIASES: dict[str, str] = {"MON": "MTL", "NYC": "NY"}
_PWHL_IMG_CACHE: dict[tuple[str, int], Any] = {}


def _norm_pwhl_code(code: str) -> str:
    c = str(code or "").strip().upper()
    return PWHL_CODE_ALIASES.get(c, c)


def _pwhl_logo_paths(code: str) -> list[Path]:
    c = _norm_pwhl_code(code)
    # Include code and team-name variants to support user file naming.
    aliases = {
        "BOS": ("boston", "fleet", "boston_fleet"),
        "MIN": ("minnesota", "frost", "minnesota_frost"),
        "MTL": ("montreal", "victoire", "montreal_victoire", "montreal_victorie"),
        "NY": ("new_york", "sirens", "new_york_sirens", "ny_sirens"),
        "OTT": ("ottawa", "charge", "ottawa_charge"),
        "TOR": ("toronto", "sceptres", "toronto_sceptres"),
        "VAN": ("vancouver", "goldeneyes", "vancouver_goldeneyes"),
        "SEA": ("seattle", "torrent", "seattle_torrent"),
    }
    names = [c, c.lower(), f"pwhl_{c}", f"pwhl_{c.lower()}"]
    if c == "MTL":
        names.extend(["MON", "mon", "pwhl_MON", "pwhl_mon", "MON_pwhl", "mon_pwhl"])
    names.extend(aliases.get(c, ()))
    out: list[Path] = []
    for name in names:
        out.append(PWHL_LOGOS_DIR / f"{name}.png")
    return out


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
            if h0 > 0 and h0 != int(height):
                if h0 > int(height):
                    factor = max(1, int(round(h0 / max(1, int(height)))))
                    img = img.subsample(factor)
                else:
                    # Keep original for upscaling quality.
                    pass
            _PWHL_IMG_CACHE[key] = img
            return img
        except Exception:
            continue
    return None


def _date_labels(start: dt.date, end: dt.date) -> list[tuple[dt.date, str]]:
    out: list[tuple[dt.date, str]] = []
    d = start
    while d <= end:
        out.append((d, f"{d.month}/{d.day}"))
        d += dt.timedelta(days=1)
    return out


def _outcome_codes(league: str, game: dict[str, Any]) -> tuple[str, str, str, str] | None:
    away = game.get("awayTeam") or {}
    home = game.get("homeTeam") or {}
    ac = canon_team_code(str(away.get("abbrev") or away.get("abbreviation") or "").upper())
    hc = canon_team_code(str(home.get("abbrev") or home.get("abbreviation") or "").upper())
    if not ac or not hc:
        return None
    if not _is_final_state(str(game.get("gameState") or game.get("gameStatus") or "")):
        return None

    try:
        ascore = int(away.get("score") or 0)
        hscore = int(home.get("score") or 0)
    except Exception:
        return None
    if ascore == hscore:
        return None

    winner = ac if ascore > hscore else hc
    league_u = str(league).upper()

    if league_u == "NHL":
        pdx = game.get("periodDescriptor") or {}
        end_type = str(pdx.get("periodType") or "").upper()
        if end_type not in {"OT", "SO"}:
            go = game.get("gameOutcome") or {}
            end_type = str(go.get("lastPeriodType") or "").upper()
        if end_type == "SO":
            wcode, lcode = "SOW", "SOL"
        elif end_type == "OT":
            wcode, lcode = "OTW", "OTL"
        else:
            wcode, lcode = "W", "L"
    else:
        status = str(game.get("statusText") or "").upper()
        if "SO" in status:
            wcode, lcode = "SOW", "SOL"
        elif "OT" in status:
            wcode, lcode = "OTW", "OTL"
        else:
            wcode, lcode = "W", "L"

    if winner == ac:
        return ac, hc, wcode, lcode
    return ac, hc, lcode, wcode


def _compute_phase_tables(
    *,
    league: str,
    phase_ranges: dict[str, tuple[dt.date, dt.date]],
    nhl_api: NHLApi,
    pwhl_api: PWHLApi,
) -> dict[str, dict[str, Any]]:
    teams = _team_order(league)
    out: dict[str, dict[str, Any]] = {}
    league_u = str(league).upper()

    for ph in PHASES:
        if ph not in phase_ranges:
            continue
        start, end = phase_ranges[ph]
        if end < start:
            continue

        labels = _date_labels(start, end)
        date_cols = [lbl for (_d, lbl) in labels]
        by_team: dict[str, dict[str, str]] = {t: {lbl: "" for lbl in date_cols} for t in teams}
        by_team_game: dict[str, dict[str, dict[str, Any]]] = {t: {} for t in teams}

        for d, lbl in labels:
            games = _load_pwhl_games_for_date(pwhl_api, d) if league_u == "PWHL" else _load_nhl_games_for_date(nhl_api, d)
            for g in games:
                mapped = _outcome_codes(league_u, g)
                if mapped is None:
                    continue
                ac, hc, acode, hcode = mapped
                if ac in by_team:
                    by_team[ac][lbl] = acode
                    if lbl not in by_team_game[ac]:
                        by_team_game[ac][lbl] = g
                if hc in by_team:
                    by_team[hc][lbl] = hcode
                    if lbl not in by_team_game[hc]:
                        by_team_game[hc][lbl] = g

        rows: list[dict[str, str]] = []
        for t in teams:
            row: dict[str, str] = {"team": t}
            row.update(by_team[t])
            rows.append(row)
        out[ph] = {"date_cols": date_cols, "rows": rows, "games_by_team_col": by_team_game}

    return out


def populate_game_stats_tab(
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

    phase_tables = _compute_phase_tables(
        league=league_u,
        phase_ranges=phase_ranges,
        nhl_api=nhl_api,
        pwhl_api=pwhl_api,
    )
    if not phase_tables:
        phase_tables = read_game_stats_xml(season=SEASON, league=league_u) or {}
    try:
        if phase_tables:
            write_game_stats_xml(
                season=SEASON,
                league=league_u,
                phase_tables=phase_tables,
            )
    except Exception:
        pass
    available_phases = [ph for ph in PHASES if phase_tables.get(ph)] or ["regular"]

    state: dict[str, Any] = {
        "phase": default_phase if default_phase in available_phases else available_phases[0],
        "sort_col": "team",
        "desc": False,
    }
    btns: dict[str, tk.Label] = {}
    live_imgs: list[Any] = []

    for i, ph in enumerate(available_phases):
        b = tk.Label(top, text=PHASE_LABEL.get(ph, ph.title()), padx=10, pady=5, cursor="hand2", bg="#2f2f2f", fg="#f0f0f0")
        b.pack(side="left", padx=(0 if i == 0 else 8, 0))
        btns[ph] = b

    # Layout mirrors heatmap-like tabs: frozen left team column + scrollable data canvas
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

    cell_h = 26
    header_h = 28
    pad_x = 8
    sort_indicator = ""
    hover_job: str | None = None
    hover_tip: tk.Toplevel | None = None
    hover_target: tuple[str, str, str] | None = None
    hover_imgs: list[Any] = []

    geometry: dict[str, Any] = {"team_w": 120, "cell_w": 68, "date_cols": [], "cell_h": cell_h}

    def _text_px(s: str) -> int:
        try:
            return int(font.measure(s))
        except Exception:
            return 8 * len(s)

    def _header_text_px(s: str) -> int:
        try:
            return int(header_font.measure(s))
        except Exception:
            return 8 * len(s)

    def _rows_sorted(rows: list[dict[str, str]], date_cols: list[str]) -> list[dict[str, str]]:
        col = str(state["sort_col"])
        desc = bool(state["desc"])
        if col == "team":
            return sorted(rows, key=lambda r: str(r.get("team", "")), reverse=desc)
        if col in date_cols:
            return sorted(
                rows,
                key=lambda r: (OUTCOME_RANK.get(str(r.get(col, "")), 0), str(r.get("team", ""))),
                reverse=desc,
            )
        return rows

    def _phase_visible_rows(rows: list[dict[str, str]], date_cols: list[str]) -> list[dict[str, str]]:
        if str(state.get("phase") or "") != "postseason":
            return rows
        visible = [
            row
            for row in rows
            if any(str(row.get(col, "")).strip() for col in date_cols)
        ]
        return visible if visible else rows

    def _row_fill_for_selection(team: str) -> str:
        sel = str(get_selected_team_code() or "").upper()
        if sel and team.upper() == sel:
            return "#3a3a3a"
        return ""

    def _compute_geometry(rows: list[dict[str, str]], date_cols: list[str]) -> None:
        # Team width should fit "[code] [logo]" comfortably without wasting space.
        max_logo_w = 0
        if logo_bank is not None:
            for r in rows:
                t = str(r.get("team", ""))
                try:
                    if league_u == "PWHL":
                        im = _pwhl_logo_get(t, height=16, master=team_canvas)
                    else:
                        im = logo_bank.get(t, height=16, dim=False)
                except Exception:
                    im = None
                if im is not None:
                    try:
                        max_logo_w = max(max_logo_w, int(im.width()))
                    except Exception:
                        pass
        max_team_text = max((_text_px(str(r.get("team", ""))) for r in rows), default=_text_px("Team"))
        geometry["team_w"] = max(84, min(130, pad_x * 3 + max_team_text + max_logo_w))

        max_cell_text = max((_text_px(v) for v in ("OTW", "OTL", "SOW", "SOL", "W", "L", "")), default=24)
        max_header = max((_header_text_px(c) for c in date_cols), default=_header_text_px("12/31"))
        geometry["cell_w"] = max(46, max(max_cell_text, max_header) + 10)
        geometry["date_cols"] = date_cols
        # Dynamically fit rows to viewport so last row isn't clipped.
        try:
            avail_h = int(max(1, data_canvas.winfo_height()))
        except Exception:
            avail_h = 1
        if rows and avail_h > header_h + 20:
            fit_h = max(20, int((avail_h - header_h) / max(1, len(rows))))
            geometry["cell_h"] = min(30, fit_h)
        else:
            geometry["cell_h"] = cell_h

    def _render() -> None:
        nonlocal live_imgs, sort_indicator
        _cancel_hover_job()
        _hide_hover_tip()
        live_imgs = []
        team_canvas.delete("all")
        data_canvas.delete("all")

        table = phase_tables.get(str(state["phase"])) or {"date_cols": [], "rows": []}
        date_cols = list(table.get("date_cols") or [])
        rows = _rows_sorted(list(table.get("rows") or []), date_cols)
        rows = _phase_visible_rows(rows, date_cols)
        state["rows"] = rows
        state["date_cols_live"] = date_cols
        state["games_by_team_col"] = table.get("games_by_team_col") or {}
        _compute_geometry(rows, date_cols)

        tw = int(geometry["team_w"])
        cw = int(geometry["cell_w"])
        ch = int(geometry.get("cell_h") or cell_h)
        total_h = header_h + len(rows) * ch
        total_w = cw * len(date_cols)

        # Team header
        team_canvas.create_rectangle(0, 0, tw, header_h, fill="#2f2f2f", outline="#323232")
        team_label = "Team"
        team_canvas.create_text(tw / 2, header_h / 2, text=team_label, fill="#f0f0f0", font=header_font, anchor="center")

        # Date headers
        for j, c in enumerate(date_cols):
            x0 = j * cw
            x1 = x0 + cw
            data_canvas.create_rectangle(x0, 0, x1, header_h, fill="#2f2f2f", outline="#323232")
            data_canvas.create_text((x0 + x1) / 2, header_h / 2, text=c, fill="#f0f0f0", font=header_font)

        # Rows
        for i, r in enumerate(rows):
            y0 = header_h + i * ch
            y1 = y0 + ch
            team = str(r.get("team", ""))
            row_sel_fill = _row_fill_for_selection(team)

            team_fill = row_sel_fill if row_sel_fill else "#2a2a2a"
            team_canvas.create_rectangle(0, y0, tw, y1, fill=team_fill, outline="#323232")

            img = None
            if logo_bank is not None:
                try:
                    if league_u == "PWHL":
                        img = _pwhl_logo_get(team, height=16, master=team_canvas)
                    else:
                        img = logo_bank.get(team, height=16, dim=False)
                except Exception:
                    img = None
            # Match predictions table spacing exactly.
            gap = 3
            pad_lr = 2
            text_w = _text_px(team)
            img_w = int(img.width()) if img else 0
            group_w = text_w + (gap + img_w if img else 0)
            start_x = max(pad_lr, (tw - group_w) / 2)

            team_canvas.create_text(start_x, (y0 + y1) / 2, text=team, fill="#f0f0f0", anchor="w")
            if img is not None:
                live_imgs.append(img)
                iw = int(img.width())
                x_logo = start_x + text_w + gap + iw / 2
                x_logo = min(x_logo, tw - pad_lr - iw / 2)
                team_canvas.create_image(x_logo, (y0 + y1) / 2, image=img, anchor="center")

            for j, c in enumerate(date_cols):
                x0 = j * cw
                x1 = x0 + cw
                val = str(r.get(c, ""))
                fill = "#262626"
                if val:
                    rank = OUTCOME_RANK.get(val, 0)
                    t = float(max(0, rank - 1)) / 5.0
                    fill = _heat_color_from_rank01(t)
                if row_sel_fill:
                    # Slightly blend selected row so team selection remains visible.
                    fill = "#3a3a3a" if val == "" else fill
                data_canvas.create_rectangle(x0, y0, x1, y1, fill=fill, outline="#323232")
                if val:
                    txt_col = "#111111" if _rel_luminance(fill) > 0.40 else "#f0f0f0"
                    data_canvas.create_text((x0 + x1) / 2, (y0 + y1) / 2, text=val, fill=txt_col)

        team_canvas.configure(scrollregion=(0, 0, tw, total_h + 1), width=tw)
        data_canvas.configure(scrollregion=(0, 0, total_w, total_h + 1))

        # Keep latest date visible by default/reset.
        if bool(state.get("stick_latest", False)):
            data_canvas.xview_moveto(1.0)
            state["stick_latest"] = False

        # Keep both canvases vertically aligned.
        try:
            team_canvas.yview_moveto(data_canvas.yview()[0])
        except Exception:
            pass

        # Active phase button style
        for ph, b in btns.items():
            b.configure(bg="#3a3a3a" if ph == state["phase"] else "#2f2f2f", fg="#f0f0f0")

    def _team_record(team: str) -> str:
        rows = list(state.get("rows") or [])
        date_cols = list(state.get("date_cols_live") or [])
        row = next((r for r in rows if str(r.get("team", "")) == team), None)
        if row is None:
            return ""
        w = otw = sow = l = otl = sol = 0
        for c in date_cols:
            v = str(row.get(c, ""))
            if v == "W":
                w += 1
            elif v == "OTW":
                otw += 1
            elif v == "SOW":
                sow += 1
            elif v == "L":
                l += 1
            elif v == "OTL":
                otl += 1
            elif v == "SOL":
                sol += 1
        wins = w + otw + sow
        otso_losses = otl + sol
        pts = (wins * (3 if league_u == "PWHL" else 2)) + otso_losses
        return f"{wins}-{l}-{otso_losses}\u2014{pts}"

    def _hide_hover_tip() -> None:
        nonlocal hover_tip, hover_imgs
        if hover_tip is not None:
            try:
                hover_tip.destroy()
            except Exception:
                pass
        hover_tip = None
        hover_imgs = []

    def _popup_game_card(game: dict[str, Any], x_root: int, y_root: int) -> None:
        nonlocal hover_tip, hover_imgs
        _hide_hover_tip()
        away = game.get("awayTeam") or {}
        home = game.get("homeTeam") or {}
        ac = canon_team_code(str(away.get("abbrev") or away.get("abbreviation") or "").upper())
        hc = canon_team_code(str(home.get("abbrev") or home.get("abbreviation") or "").upper())
        ascore = str(away.get("score") or 0)
        hscore = str(home.get("score") or 0)
        tip = tk.Toplevel(parent.winfo_toplevel())
        tip.overrideredirect(True)
        tip.configure(bg="#2c2c2c")
        tip.geometry(f"+{x_root + 14}+{y_root + 14}")
        hover_tip = tip

        card = tk.Frame(tip, bg="#444444", bd=0, highlightthickness=1, highlightbackground="#323232")
        card.pack(padx=2, pady=2)
        topf = tk.Frame(card, bg="#444444")
        topf.pack(fill="x", padx=10, pady=(8, 2))
        midf = tk.Frame(card, bg="#444444")
        midf.pack(fill="x", padx=10, pady=(2, 2))

        def _logo_for(code: str) -> Any:
            if league_u == "PWHL":
                return _pwhl_logo_get(code, height=26, master=tip)
            if logo_bank is None:
                return None
            try:
                return logo_bank.get(code, height=26, dim=False)
            except Exception:
                return None

        aimg = _logo_for(ac)
        himg = _logo_for(hc)
        if aimg is not None:
            hover_imgs.append(aimg)
        if himg is not None:
            hover_imgs.append(himg)

        topf.grid_columnconfigure(0, weight=1)
        topf.grid_columnconfigure(1, weight=0)
        topf.grid_columnconfigure(2, weight=1)
        midf.grid_columnconfigure(0, weight=1)
        midf.grid_columnconfigure(1, weight=0)
        midf.grid_columnconfigure(2, weight=1)

        atext = "" if aimg is not None else (ac or "AWY")
        htext = "" if himg is not None else (hc or "HOM")
        al = tk.Label(topf, text=atext, image=aimg if aimg else "", compound="left", bg="#444444", fg="#f0f0f0", anchor="center")
        hl = tk.Label(topf, text=htext, image=himg if himg else "", compound="right", bg="#444444", fg="#f0f0f0", anchor="center")
        at = tk.Label(topf, text="@", bg="#444444", fg="#f0f0f0", font=("TkDefaultFont", 12, "bold"))
        al.grid(row=0, column=0, padx=(0, 6), sticky="e")
        at.grid(row=0, column=1, padx=6)
        hl.grid(row=0, column=2, padx=(6, 0), sticky="w")

        tk.Label(midf, text=ascore, bg="#444444", fg="#f0f0f0", font=("Helvetica", 24)).grid(row=0, column=0, padx=(10, 8))
        tk.Label(midf, text="-", bg="#444444", fg="#f0f0f0", font=("Helvetica", 26)).grid(row=0, column=1, padx=8)
        tk.Label(midf, text=hscore, bg="#444444", fg="#f0f0f0", font=("Helvetica", 24)).grid(row=0, column=2, padx=(8, 10))

    def _popup_team_record(team: str, x_root: int, y_root: int) -> None:
        nonlocal hover_tip
        _hide_hover_tip()
        rec = _team_record(team)
        if not rec:
            return
        tip = tk.Toplevel(parent.winfo_toplevel())
        tip.overrideredirect(True)
        tip.configure(bg="#2c2c2c")
        tip.geometry(f"+{x_root + 14}+{y_root + 14}")
        hover_tip = tip
        lbl = tk.Label(
            tip,
            text=rec,
            bg="#2f2f2f",
            fg="#f0f0f0",
            padx=10,
            pady=6,
            bd=0,
            highlightthickness=1,
            highlightbackground="#323232",
        )
        lbl.pack()

    def _cancel_hover_job() -> None:
        nonlocal hover_job
        if hover_job is not None:
            try:
                parent.after_cancel(hover_job)
            except Exception:
                pass
        hover_job = None

    def _schedule_hover(kind: str, team: str, col: str, x_root: int, y_root: int) -> None:
        nonlocal hover_job, hover_target
        target = (kind, team, col)
        if hover_target == target and hover_tip is not None:
            return
        hover_target = target
        _cancel_hover_job()

        def _fire() -> None:
            nonlocal hover_job
            hover_job = None
            if hover_target != target:
                return
            if kind == "team":
                _popup_team_record(team, x_root, y_root)
                return
            games_map = state.get("games_by_team_col") or {}
            game = ((games_map.get(team) or {}).get(col))
            if isinstance(game, dict):
                _popup_game_card(game, x_root, y_root)

        hover_job = parent.after(1000, _fire)

    def _on_team_motion(event) -> None:
        y = float(team_canvas.canvasy(event.y))
        if y <= header_h:
            _cancel_hover_job()
            _hide_hover_tip()
            return
        rows = list(state.get("rows") or [])
        ch = int(geometry.get("cell_h") or cell_h)
        idx = int((y - header_h) // max(1, ch))
        if 0 <= idx < len(rows):
            team = str(rows[idx].get("team", ""))
            if team:
                _schedule_hover("team", team, "", event.x_root, event.y_root)
                return
        _cancel_hover_job()
        _hide_hover_tip()

    def _on_data_motion(event) -> None:
        x = float(data_canvas.canvasx(event.x))
        y = float(data_canvas.canvasy(event.y))
        if y <= header_h:
            _cancel_hover_job()
            _hide_hover_tip()
            return
        rows = list(state.get("rows") or [])
        date_cols = list(state.get("date_cols_live") or [])
        ch = int(geometry.get("cell_h") or cell_h)
        cw = int(geometry.get("cell_w") or 68)
        ridx = int((y - header_h) // max(1, ch))
        cidx = int(x // max(1, cw))
        if 0 <= ridx < len(rows) and 0 <= cidx < len(date_cols):
            team = str(rows[ridx].get("team", ""))
            col = str(date_cols[cidx])
            val = str(rows[ridx].get(col, ""))
            if team and col and val:
                _schedule_hover("cell", team, col, event.x_root, event.y_root)
                return
        _cancel_hover_job()
        _hide_hover_tip()

    def _on_leave_any(_event=None) -> None:
        _cancel_hover_job()
        _hide_hover_tip()

    def _on_header_click(event) -> None:
        x = float(data_canvas.canvasx(event.x))
        y = float(data_canvas.canvasy(event.y))
        if y > header_h:
            return
        date_cols = list(geometry.get("date_cols") or [])
        cw = int(geometry.get("cell_w") or 68)
        idx = int(x // max(1, cw))
        if 0 <= idx < len(date_cols):
            col = str(date_cols[idx])
            if state["sort_col"] == col:
                state["desc"] = not bool(state["desc"])
            else:
                state["sort_col"] = col
                state["desc"] = True
            _render()

    def _on_team_header_click(event) -> None:
        y = float(team_canvas.canvasy(event.y))
        if y > header_h:
            if callable(set_selected_team_code):
                rows = list(state.get("rows") or [])
                ch = int(geometry.get("cell_h") or cell_h)
                idx = int((y - header_h) // max(1, ch))
                if 0 <= idx < len(rows):
                    team = str(rows[idx].get("team", "")).upper().strip()
                    if team:
                        try:
                            set_selected_team_code(team)
                            _render()
                        except Exception:
                            pass
            return
        if state["sort_col"] == "team":
            state["desc"] = not bool(state["desc"])
        else:
            state["sort_col"] = "team"
            state["desc"] = False
        _render()

    data_canvas.bind("<Button-1>", _on_header_click)
    team_canvas.bind("<Button-1>", _on_team_header_click)
    team_canvas.bind("<Motion>", _on_team_motion, add="+")
    team_canvas.bind("<Leave>", _on_leave_any, add="+")
    data_canvas.bind("<Motion>", _on_data_motion, add="+")
    data_canvas.bind("<Leave>", _on_leave_any, add="+")

    # Scroll behavior copied from established heatmap tabs.
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

    def _xview(*args):
        data_canvas.xview(*args)

    xs.configure(command=_xview)

    def _scroll_vertical(units: int):
        data_canvas.yview_scroll(units, "units")
        _set_y(data_canvas.yview()[0])

    def _scroll_horizontal(units: int):
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

    for w in (data_canvas,):
        w.bind("<Shift-MouseWheel>", _on_shift_mousewheel)

    # Drag-to-scroll like heatmap tabs
    def _scan_mark(canvas: tk.Canvas, event):
        canvas.scan_mark(event.x, event.y)

    def _scan_drag(canvas: tk.Canvas, event):
        canvas.scan_dragto(event.x, event.y, gain=1)
        _set_y(data_canvas.yview()[0])

    data_canvas.bind("<ButtonPress-2>", lambda e: _scan_mark(data_canvas, e), add="+")
    data_canvas.bind("<B2-Motion>", lambda e: _scan_drag(data_canvas, e), add="+")

    def _set_phase(ph: str) -> None:
        state["phase"] = ph
        state["sort_col"] = "team"
        state["desc"] = False
        state["stick_latest"] = _phase_auto_scrolls_latest(ph)
        _render()

    for ph, b in btns.items():
        b.bind("<Button-1>", lambda _e, p=ph: _set_phase(p), add="+")

    state["stick_latest"] = _phase_auto_scrolls_latest(state["phase"])
    _render()

    def redraw() -> None:
        _render()

    def reset() -> None:
        _set_phase(default_phase if default_phase in available_phases else available_phases[0])

    return {"redraw": redraw, "reset": reset}
