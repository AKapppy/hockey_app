import datetime as dt
import math
from bisect import bisect_left
from pathlib import Path
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk
from typing import Any, Callable, cast

import pandas as pd

from hockey_app.domain.colors import (
    _blend,
    _hex_from_hash,
    _hex_to_rgb,
    _rel_luminance,
    _rgb_to_hex,
)
from hockey_app.domain.teams import DIVS_MASTER, TEAM_NAMES, canon_team_code
from hockey_app.ui.tabs.models_data import playoff_field_order, playoffs_have_started

try:
    from PIL import Image, ImageTk  # type: ignore

    PIL_OK = True
except Exception:
    Image = None
    ImageTk = None
    PIL_OK = False

DARK_CANVAS_BG = "#262626"
TkImg = Any
LogoBank = Any


def _playoff_matchup_ring_order(field: list[str]) -> list[str]:
    if len(field) < 16:
        return [canon_team_code(code) for code in field if canon_team_code(code)]

    west = [canon_team_code(code) for code in field[:8] if canon_team_code(code)]
    east = [canon_team_code(code) for code in field[8:16] if canon_team_code(code)]
    ordered = east[4:8] + east[:4] + west[4:8] + west[:4]

    out: list[str] = []
    seen: set[str] = set()
    for code in ordered:
        if not code or code in seen:
            continue
        seen.add(code)
        out.append(code)
    return out


def _safe_float(v: Any, default: float = float("nan")) -> float:
    try:
        return float(cast(Any, v))
    except Exception:
        return default


def _measure_text_px(font: tkfont.Font, text: str) -> int:
    try:
        return int(font.measure(text))
    except Exception:
        return 8 * len(text)

def render_pie_chart_tab(
    parent: ttk.Frame,
    tables: dict[str, pd.DataFrame],
    *,
    metric_order: list[str],
    metric_labels: dict[str, str],  # kept for compatibility (not used in hover)
    team_colors: dict[str, str],
    logo_bank: LogoBank,
    original_order: list[str],
    team_col_width: int,
    cell_width: int,
    get_selected_team_code,
    set_selected_team_code,
    start_date: dt.date,
    images_dir: Path,
    cell_height: int = 22,
) -> dict[str, Callable[[], None]]:
    """
    Logos: ONLY in outer ring (madeplayoffs)
    Hover label: centered in hovered slice: "Team Name\\nxx.x%"
    """

    import math
    from bisect import bisect_left

    colors = {
        "bg": DARK_CANVAS_BG,
        "grid": "#323232",
        "header_bg": "#2f2f2f",
        "header_text": "#f0f0f0",
        "team_bg": "#2a2a2a",
        "team_text": "#f0f0f0",
        "cell_text": "#f7f7f7",
        "empty_cell": DARK_CANVAS_BG,
    }

    TABLE_HDR = {
        "madeplayoffs": "Playoffs",
        "round2": "Round 2",
        "round3": "Conf. Finals",
        "round4": "Cup Final",
        "woncup": "Win Cup",
    }

    # pick canonical date columns
    ref_key = next((k for k in metric_order if k in tables), None)
    if not ref_key:
        raise RuntimeError("Pie Chart: no metrics available in tables.")
    date_cols = list(map(str, tables[ref_key].columns))
    MAX_IDX = max(0, len(date_cols) - 1)

    for child in parent.winfo_children():
        child.destroy()

    parent.grid_rowconfigure(0, weight=1)
    parent.grid_columnconfigure(0, weight=1)

    outer = ttk.Frame(parent, padding=0)
    outer.grid(row=0, column=0, sticky="nsew")
    outer.grid_rowconfigure(1, weight=1)
    outer.grid_columnconfigure(0, weight=1)

    # ---- Stepper row ----
    step_row = tk.Frame(outer, bg=colors["bg"], bd=0, highlightthickness=0)
    step_row.grid(row=0, column=0, sticky="ew", pady=(0, 6))
    step_row.grid_columnconfigure(0, weight=0)
    step_row.grid_columnconfigure(1, weight=1)
    step_row.grid_columnconfigure(2, weight=0)

    BTN_BG = "#3a3a3a"
    BTN_FG = "#f0f0f0"
    BTN_HOVER = "#444444"
    TROUGH = "#4a4a4a"
    step_btn_font = ("TkDefaultFont", 12, "bold")

    def _make_step_label(parent_w, text: str) -> tk.Label:
        lbl = tk.Label(
            parent_w,
            text=text,
            bg=BTN_BG,
            fg=BTN_FG,
            font=step_btn_font,
            bd=0,
            highlightthickness=0,
            padx=10,
            pady=8,
            cursor="hand2",
        )
        lbl.bind("<Enter>", lambda _e: lbl.config(bg=BTN_HOVER))
        lbl.bind("<Leave>", lambda _e: lbl.config(bg=BTN_BG))
        return lbl

    prev_btn = _make_step_label(step_row, "◀")
    next_btn = _make_step_label(step_row, "▶")

    slider = tk.Canvas(
        step_row,
        height=int(max(30, cell_height * 1.35)),
        bg=colors["bg"],
        bd=0,
        highlightthickness=0,
    )

    prev_btn.grid(row=0, column=0, sticky="nsew")
    slider.grid(row=0, column=1, sticky="ew")
    next_btn.grid(row=0, column=2, sticky="nsew")

    # ---- Main content ----
    content = tk.Frame(outer, bg=colors["bg"], bd=0, highlightthickness=0)
    content.grid(row=1, column=0, sticky="nsew")
    content.grid_rowconfigure(0, weight=1)
    content.grid_columnconfigure(0, weight=0)  # table
    content.grid_columnconfigure(1, weight=1)  # chart

    # ---- Table host ----
    left_host = tk.Frame(content, bg=colors["bg"], bd=0, highlightthickness=0)
    left_host.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
    left_host.grid_rowconfigure(0, weight=1)
    left_host.grid_columnconfigure(0, weight=1)

    table_frame = tk.Frame(left_host, bg=colors["bg"], bd=0, highlightthickness=0)
    table_frame.grid(row=0, column=0, sticky="nsew")
    table_frame.grid_rowconfigure(0, weight=1)
    table_frame.grid_rowconfigure(1, weight=0)
    table_frame.grid_columnconfigure(0, weight=1)
    table_frame.grid_columnconfigure(1, weight=0)

    table_canvas = tk.Canvas(table_frame, bg=colors["bg"], highlightthickness=0)
    vscroll = ttk.Scrollbar(table_frame, orient="vertical", command=table_canvas.yview)
    hscroll = ttk.Scrollbar(table_frame, orient="horizontal", command=table_canvas.xview)
    table_canvas.configure(yscrollcommand=vscroll.set, xscrollcommand=hscroll.set)

    table_canvas.grid(row=0, column=0, sticky="nsew")
    vscroll.grid(row=0, column=1, sticky="ns")
    hscroll.grid(row=1, column=0, sticky="ew")
    br = tk.Canvas(table_frame, width=18, height=18, bg=colors["bg"], highlightthickness=0)
    br.grid(row=1, column=1, sticky="nsew")

    # ---- Chart ----
    chart_canvas = tk.Canvas(content, bg=colors["bg"], highlightthickness=0)
    chart_canvas.grid(row=0, column=1, sticky="nsew")

    font = tkfont.nametofont("TkDefaultFont")
    header_font = tkfont.Font(root=parent.winfo_toplevel(), font=font)
    header_font.configure(weight="bold")

    date_font = tkfont.Font(root=parent.winfo_toplevel(), font=font)
    date_font.configure(size=max(24, int(font.cget("size")) + 14), weight="bold")

    hover_label_font = tkfont.Font(root=parent.winfo_toplevel(), font=font)
    hover_label_font.configure(size=max(12, int(font.cget("size")) + 2), weight="bold")

    present_codes = set(canon_team_code(c) for c in original_order)

    def _pie_order_by_division() -> list[str]:
        def filt(lst):
            out = []
            for c in lst:
                cc = canon_team_code(c)
                if cc in present_codes:
                    out.append(cc)
            return out

        metro = filt(DIVS_MASTER.get("Metro", []))
        if "NYR" in metro:
            metro = ["NYR"] + [c for c in metro if c != "NYR"]
        atl = filt(DIVS_MASTER.get("Atlantic", []))
        cen = filt(DIVS_MASTER.get("Central", []))
        pac = filt(DIVS_MASTER.get("Pacific", []))
        return metro + atl + cen + pac

    def _pie_order_for_selected_date() -> list[str]:
        selected_day = start_date + dt.timedelta(days=max(0, int(selected_col_idx)))
        if playoffs_have_started(selected_day, league="NHL"):
            field = [canon_team_code(code) for code in playoff_field_order(selected_day, league="NHL")]
            field = [code for code in field if code in present_codes]
            if field:
                ordered = _playoff_matchup_ring_order(field)
                tail = [code for code in _pie_order_by_division() if code not in set(ordered)]
                return ordered + tail
        return _pie_order_by_division()

    pie_order = _pie_order_by_division()

    def _team_alpha_key(code: str) -> tuple[str, str]:
        nm = TEAM_NAMES.get(code, code)
        return (nm.lower(), code)

    default_table_order = sorted([c for c in present_codes], key=_team_alpha_key)
    table_order = default_table_order[:]

    selected_col_idx = MAX_IDX
    hover: dict[str, str | None] = {"team": None, "metric": None}

    _table_cell_bbox: dict[tuple[str, str], tuple[float, float, float, float]] = {}
    _chart_imgs_live: list[TkImg] = []
    _ring_lookup: dict[str, list[tuple[float, str, float]]] = {}
    _ring_geom: dict[str, tuple[float, float]] = {}
    _chart_center = {"cx": 0.0, "cy": 0.0, "inner": 0.0, "outer": 0.0, "thick": 0.0}
    _start0_deg = -90.0

    _wedge_mid: dict[tuple[str, str], tuple[float, float, float, float, float, float]] = {}
    # key=(metric, team) -> (mid_x, mid_y, mid_deg, extent_deg, r_in, r_out)

    # ---- Hover “in-wedge” label (no box; shadow only) ----
    _hov: dict[str, int | None] = {"shadow": None, "text": None}

    def _hover_label_reset():
        _hov["shadow"] = None
        _hov["text"] = None

    def _hover_label_hide():
        try:
            if _hov["shadow"] is not None:
                chart_canvas.itemconfigure(_hov["shadow"], state="hidden")
            if _hov["text"] is not None:
                chart_canvas.itemconfigure(_hov["text"], state="hidden")
        except Exception:
            pass

    def _hover_label_show(msg: str, cx: float, cy: float):
        if not msg:
            _hover_label_hide()
            return

        try:
            if _hov["shadow"] is None:
                _hov["shadow"] = chart_canvas.create_text(
                    0, 0,
                    text="",
                    fill="#000000",
                    font=hover_label_font,
                    justify="center",
                    anchor="center",
                    state="hidden",
                )
            if _hov["text"] is None:
                _hov["text"] = chart_canvas.create_text(
                    0, 0,
                    text="",
                    fill="#f0f0f0",
                    font=hover_label_font,
                    justify="center",
                    anchor="center",
                    state="hidden",
                )

            # shadow (1px offset)
            chart_canvas.itemconfigure(_hov["shadow"], text=msg, state="normal")
            chart_canvas.coords(_hov["shadow"], cx + 1, cy + 1)

            # main text
            chart_canvas.itemconfigure(_hov["text"], text=msg, state="normal")
            chart_canvas.coords(_hov["text"], cx, cy)

            chart_canvas.tag_raise(_hov["shadow"])
            chart_canvas.tag_raise(_hov["text"])
        except Exception:
            pass

    def _pretty_date_for_idx(idx: int) -> str:
        d = start_date + dt.timedelta(days=int(idx))
        return f"{d.day} {d.strftime('%b')} {d.year}"

    def _values_for(metric_key: str) -> pd.Series:
        df = tables.get(metric_key)
        if df is None or not date_cols:
            return pd.Series(dtype="float64")
        if len(df.columns) == 0:
            return pd.Series(dtype="float64")
        # Use positional column access so duplicate date labels (e.g. stale
        # overlong seasons producing repeated m/d columns) still resolve to a
        # single Series instead of a DataFrame.
        idx = max(0, min(selected_col_idx, len(df.columns) - 1))
        try:
            col_data = df.iloc[:, idx]
        except Exception:
            return pd.Series(dtype="float64")
        if isinstance(col_data, pd.DataFrame):
            if col_data.shape[1] == 0:
                return pd.Series(dtype="float64")
            col_data = col_data.iloc[:, -1]
        s = pd.to_numeric(col_data, errors="coerce")
        s.index = [canon_team_code(str(x)) for x in s.index]
        return s

    def _snapshot_df() -> pd.DataFrame:
        data: dict[str, list[float | None]] = {}
        for mk in metric_order:
            s = _values_for(mk)
            col_vals: list[float | None] = []
            for team in table_order:
                v = s.loc[team] if team in s.index else float("nan")
                if pd.isna(v):
                    col_vals.append(None)
                else:
                    try:
                        col_vals.append(_safe_float(v))
                    except Exception:
                        col_vals.append(None)
            data[mk] = col_vals
        return pd.DataFrame(data=data, index=table_order)

    def _ranks01(local_df: pd.DataFrame) -> dict[str, dict[str, float]]:
        out: dict[str, dict[str, float]] = {}
        for col in local_df.columns:
            s = pd.to_numeric(local_df[col], errors="coerce")
            valid = s.dropna()
            if valid.empty or len(valid) == 1:
                out[str(col)] = {team: 0.5 for team in valid.index}
            else:
                r = valid.rank(method="average", ascending=True)
                n = float(len(valid))
                out[str(col)] = {team: float((r.loc[team] - 1.0) / (n - 1.0)) for team in valid.index}
        return out

    def _heat_color_from_rank01(t: float) -> str:
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
        r, g, b = _hex_to_rgb(_blend(_rgb_to_hex(r, g, b), colors["bg"], heat_blend_bg))
        return _rgb_to_hex(r, g, b)

    def _annular_sector_points(cx: float, cy: float, r_in: float, r_out: float, start_deg: float, extent_deg: float) -> list[float]:
        extent_deg = float(extent_deg)
        if abs(extent_deg) < 0.01:
            return []
        steps = int(max(24, min(360, abs(extent_deg) * 2.0)))
        a0 = math.radians(start_deg)
        a1 = math.radians(start_deg + extent_deg)
        if a1 < a0:
            a0, a1 = a1, a0
        pts: list[float] = []
        for i in range(steps + 1):
            t = i / steps
            a = a0 + (a1 - a0) * t
            pts.extend([cx + r_out * math.cos(a), cy + r_out * math.sin(a)])
        for i in range(steps, -1, -1):
            t = i / steps
            a = a0 + (a1 - a0) * t
            pts.extend([cx + r_in * math.cos(a), cy + r_in * math.sin(a)])
        return pts

    def _metric_col_width(mk: str) -> int:
        hdr = TABLE_HDR.get(mk, mk)
        w_hdr = int(_measure_text_px(header_font, hdr))
        w_pct = int(_measure_text_px(font, "100.0%"))
        return int(max(cell_width, w_hdr + 22, w_pct + 20))

    metric_widths = {mk: _metric_col_width(mk) for mk in metric_order}
    metric_x_starts: dict[str, int] = {}
    _x = team_col_width
    for mk in metric_order:
        metric_x_starts[mk] = _x
        _x += metric_widths[mk]
    total_table_w = team_col_width + sum(metric_widths.values())

    content.grid_columnconfigure(0, minsize=min(total_table_w + 30, 820), weight=0)

    def _table_sort_by_team():
        nonlocal table_order
        table_order = sorted(table_order, key=_team_alpha_key)

    def _table_sort_by_metric(mk: str):
        nonlocal table_order
        s = _values_for(mk)

        def key(c: str):
            v = s.loc[c] if c in s.index else float("nan")
            try:
                vf = _safe_float(v)
            except Exception:
                vf = float("nan")
            return (-vf if not pd.isna(vf) else 1e9, _team_alpha_key(c))

        table_order = sorted(table_order, key=key)

    def _table_sort_by_metric_chain(metric_keys: list[str]) -> None:
        nonlocal table_order
        if not metric_keys:
            _table_sort_by_team()
            return
        series_map: dict[str, pd.Series] = {mk: _values_for(mk) for mk in metric_keys}

        def key(c: str):
            vals: list[float] = []
            for mk in metric_keys:
                s = series_map.get(mk)
                v = s.loc[c] if isinstance(s, pd.Series) and c in s.index else float("nan")
                try:
                    vf = _safe_float(v)
                except Exception:
                    vf = float("nan")
                score = vf if not pd.isna(vf) else -1.0
                vals.append(-float(score))
            return (*vals, _team_alpha_key(c))

        table_order = sorted(table_order, key=key)

    if metric_order:
        # Default ranking: right-most metric first (Win Cup -> ... -> Playoffs).
        _table_sort_by_metric_chain(list(reversed(metric_order)))
    else:
        _table_sort_by_team()

    _table_highlight_id: dict[str, int | None] = {"id": None}
    _table_header_band = {"active": False, "y0": 0.0, "y1": 0.0}

    def _set_table_highlight(team: str | None, metric: str | None):
        cid = _table_highlight_id["id"]
        if cid is None:
            cid = table_canvas.create_rectangle(0, 0, 0, 0, outline="#f0f0f0", width=2, state="hidden")
            _table_highlight_id["id"] = cid

        if not team or not metric:
            table_canvas.itemconfigure(cid, state="hidden")
            return

        bb = _table_cell_bbox.get((team, metric))
        if not bb:
            table_canvas.itemconfigure(cid, state="hidden")
            return

        x0, y0, x1, y1 = bb
        table_canvas.coords(cid, x0 + 1, y0 + 1, x1 - 1, y1 - 1)
        table_canvas.itemconfigure(cid, state="normal")
        table_canvas.tag_raise(cid)

    def _on_table_header_click(event):
        x = float(table_canvas.canvasx(event.x))
        y = float(table_canvas.canvasy(event.y))
        if not _table_header_band["active"]:
            return
        if not (_table_header_band["y0"] <= y < _table_header_band["y1"]):
            return

        if x < team_col_width:
            _table_sort_by_team()
        else:
            mk_hit = None
            for mk in metric_order:
                x0 = metric_x_starts[mk]
                x1 = x0 + metric_widths[mk]
                if x0 <= x < x1:
                    mk_hit = mk
                    break
            if mk_hit:
                _table_sort_by_metric(mk_hit)
        draw_table()

    table_canvas.bind("<Button-1>", _on_table_header_click)

    def draw_table():
        nonlocal _table_cell_bbox
        _table_cell_bbox = {}

        table_canvas.delete("all")
        _table_highlight_id["id"] = None
        _table_header_band["active"] = False

        df = _snapshot_df()
        ranks01 = _ranks01(df)
        n_rows = len(df.index)

        title_h = int(max(58, cell_height * 2.8))
        header_h = int(cell_height)
        block_h = title_h + header_h + n_rows * cell_height

        w_canvas = max(1, int(table_canvas.winfo_width() or 1))
        h_canvas = max(1, int(table_canvas.winfo_height() or 1))

        y_off = (h_canvas - block_h) / 2 if h_canvas > block_h else 0.0
        y_off = max(0.0, y_off)

        scroll_h = max(h_canvas, block_h)
        table_canvas.configure(scrollregion=(0, 0, total_table_w, scroll_h))

        sel = get_selected_team_code()

        date_txt = _pretty_date_for_idx(selected_col_idx) if date_cols else ""

        hy0 = y_off + title_h
        hy1 = hy0 + header_h
        _table_header_band.update({"active": True, "y0": hy0, "y1": hy1})

        date_y = hy0 / 2  # center within the entire band above the header row (includes y_off)
        table_canvas.create_text(
            total_table_w / 2,
            date_y,
            text=date_txt,
            fill=colors["header_text"],
            anchor="center",
            font=date_font,
        )

        table_canvas.create_rectangle(0, hy0, team_col_width, hy1, fill=colors["header_bg"], outline=colors["grid"])
        table_canvas.create_text(team_col_width / 2, (hy0 + hy1) / 2, text="Team", fill=colors["header_text"], anchor="center", font=header_font)

        for mk in metric_order:
            x0 = metric_x_starts[mk]
            x1 = x0 + metric_widths[mk]
            table_canvas.create_rectangle(x0, hy0, x1, hy1, fill=colors["header_bg"], outline=colors["grid"])
            table_canvas.create_text((x0 + x1) / 2, (hy0 + hy1) / 2, text=TABLE_HDR.get(mk, mk), fill=colors["header_text"], anchor="center", font=header_font)

        gap = 3
        pad_lr = 2

        for i, team in enumerate(df.index):
            row_y0 = hy1 + i * cell_height
            row_y1 = row_y0 + cell_height

            table_canvas.create_rectangle(0, row_y0, team_col_width, row_y1, fill=colors["team_bg"], outline=colors["grid"])
            code = str(team).upper()
            img = logo_bank.get(code, height=18, dim=False)

            text_w = _measure_text_px(font, code)
            img_w = int(img.width()) if img else 0
            group_w = text_w + (gap + img_w if img else 0)
            start_x = max(pad_lr, (team_col_width - group_w) / 2)

            table_canvas.create_text(start_x, (row_y0 + row_y1) / 2, text=code, fill=colors["team_text"], anchor="w")
            if img:
                x_img = start_x + text_w + gap + img_w / 2
                x_img = min(x_img, team_col_width - pad_lr - img_w / 2)
                table_canvas.create_image(x_img, (row_y0 + row_y1) / 2, image=img, anchor="center")

            for mk in metric_order:
                x0 = metric_x_starts[mk]
                x1 = x0 + metric_widths[mk]
                v = df.at[team, mk]

                if v is None:
                    fill = colors["empty_cell"]
                    txt = ""
                    text_fill = colors["cell_text"]
                else:
                    t = ranks01.get(str(mk), {}).get(team, 0.5)
                    fill = _heat_color_from_rank01(t)
                    txt = f"{_safe_float(v) * 100:.1f}%"
                    text_fill = "#111111" if _rel_luminance(fill) > 0.40 else colors["cell_text"]

                if sel and code != str(sel).upper():
                    fill = _blend(fill, colors["bg"], 0.55)
                    text_fill = _blend(text_fill, colors["bg"], 0.35)

                table_canvas.create_rectangle(x0, row_y0, x1, row_y1, fill=fill, outline=colors["grid"])
                if txt:
                    table_canvas.create_text((x0 + x1) / 2, (row_y0 + row_y1) / 2, text=txt, fill=text_fill, anchor="center")

                _table_cell_bbox[(code, str(mk))] = (x0, row_y0, x1, row_y1)

        _set_table_highlight(hover.get("team"), hover.get("metric"))

    _hover_outline_id: dict[str, int | None] = {"id": None}

    def _set_chart_hover_outline(team: str | None, metric: str | None):
        if _hover_outline_id["id"] is not None:
            try:
                chart_canvas.delete(_hover_outline_id["id"])
            except Exception:
                pass
            _hover_outline_id["id"] = None

        if not team or not metric:
            return

        geom = _ring_geom.get(metric)
        lookup = _ring_lookup.get(metric)
        if not geom or not lookup:
            return

        r_in, r_out = geom
        start_phi = 0.0
        end_phi = None
        for end_phi_i, tcode, _v in lookup:
            if tcode == team:
                end_phi = end_phi_i
                break
            start_phi = end_phi_i

        if end_phi is None or end_phi <= start_phi + 1e-6:
            return

        cx = _chart_center["cx"]
        cy = _chart_center["cy"]
        start_deg = _start0_deg + start_phi
        extent_deg = end_phi - start_phi

        pts = _annular_sector_points(cx, cy, r_in, r_out, start_deg, extent_deg)
        if not pts:
            return
        _hover_outline_id["id"] = chart_canvas.create_polygon(
            pts, fill="", outline="#f0f0f0", width=2, joinstyle="round"
        )

    _cup_cache: dict[int, TkImg] = {}

    def _load_cup_image(max_h: int) -> TkImg | None:
        max_h = int(max(10, max_h))
        if max_h in _cup_cache:
            return _cup_cache[max_h]

        candidates = [
            images_dir / "stanley_cup.png",
            Path(__file__).resolve().parents[2] / "assets" / "stanley_cup.png",
            Path(__file__).resolve().parents[2] / "assets" / "images" / "stanley_cup.png",
        ]
        p = next((cp for cp in candidates if cp.exists()), None)
        if p is None:
            return None

        try:
            if PIL_OK:
                img = Image.open(str(p)).convert("RGBA")  # type: ignore
                w0, h0 = img.size  # type: ignore
                if h0 <= 0:
                    return None
                scale = float(max_h) / float(h0)
                w = max(1, int(round(w0 * scale)))
                try:
                    resample = Image.Resampling.LANCZOS  # type: ignore
                except Exception:
                    resample = Image.LANCZOS  # type: ignore
                out = img.resize((w, max_h), resample=resample)  # type: ignore
                tkimg = ImageTk.PhotoImage(out)  # type: ignore
                _cup_cache[max_h] = tkimg
                return tkimg
            else:
                tkimg = tk.PhotoImage(master=parent.winfo_toplevel(), file=str(p))
                h0 = tkimg.height()
                if h0 > max_h and h0 > 0:
                    factor = max(1, int(math.ceil(h0 / max_h)))
                    tkimg2 = tkimg.subsample(factor)
                    _cup_cache[max_h] = tkimg2
                    return tkimg2
                _cup_cache[max_h] = tkimg
                return tkimg
        except Exception:
            return None

    def _max_logo_height_in_wedge(team: str, extent_deg: float, r_in: float, r_out: float, r_place: float) -> int:
        ar = logo_bank.aspect_ratio(team)
        if not ar or ar <= 0:
            ar = 1.0

        thick = max(1.0, (r_out - r_in))
        arc_len = max(1.0, math.radians(max(0.0, extent_deg)) * max(1.0, r_place))

        thick_eff = thick * 0.86
        arc_eff = arc_len * 0.82

        circle_r = 0.90 * min(thick_eff / 2.0, arc_eff / 2.0)
        h_diag = (2.0 * circle_r) / math.sqrt(1.0 + ar * ar)

        h_thick = thick_eff
        h_arc = arc_eff / ar

        h_max = max(0.0, min(h_diag, h_thick, h_arc))
        return int(max(0, math.floor(h_max)))

    def draw_chart():
        _chart_imgs_live.clear()
        _wedge_mid.clear()
        _ring_lookup.clear()
        _ring_geom.clear()
        _hover_label_reset()
        chart_canvas.delete("all")

        w = max(1, int(chart_canvas.winfo_width() or 1))
        h = max(1, int(chart_canvas.winfo_height() or 1))
        cx = w / 2
        cy = h / 2

        pad = max(14, int(min(w, h) * 0.05))
        outer_r = max(20.0, min(w, h) / 2 - pad)
        inner_r = max(6.0, outer_r * 0.23)
        n = max(1, len(metric_order))
        thick = max(10.0, (outer_r - inner_r) / n)

        _chart_center.update({"cx": cx, "cy": cy, "inner": inner_r, "outer": outer_r, "thick": thick})

        sel = get_selected_team_code()
        pie_order = _pie_order_for_selected_date()

        for i, mk in enumerate(metric_order):
            r_out = outer_r - i * thick
            r_in = max(inner_r, r_out - thick)
            _ring_geom[str(mk)] = (r_in, r_out)

            s = _values_for(mk)
            vals: list[tuple[str, float]] = []
            for team in pie_order:
                if team not in s.index:
                    continue
                v = s.loc[team]
                if pd.isna(v):
                    continue
                try:
                    vf = _safe_float(v)
                except Exception:
                    continue
                if vf <= 0:
                    continue
                vals.append((team, vf))

            total = sum(v for _, v in vals)
            if total <= 0:
                _ring_lookup[str(mk)] = []
                continue

            present = {t for t, _ in vals}
            ordered = [t for t in pie_order if t in present]
            val_map = {t: v for t, v in vals}
            max_v = max(val_map.values()) if val_map else 1.0

            cum = 0.0
            lookup: list[tuple[float, str, float]] = []

            for team in ordered:
                vf = val_map.get(team, 0.0)
                frac = vf / total
                extent = 360.0 * frac
                if extent <= 0.0001:
                    continue

                start_deg = _start0_deg + cum
                mid_deg = start_deg + extent / 2.0
                mid_rad = math.radians(mid_deg)

                r_place = r_in + 0.62 * (r_out - r_in)
                mx = cx + r_place * math.cos(mid_rad)
                my = cy + r_place * math.sin(mid_rad)

                pts = _annular_sector_points(cx, cy, r_in, r_out, start_deg, extent)
                if pts:
                    base = team_colors.get(team, _hex_from_hash(team))
                    tint = 0.06 + 0.08 * i
                    fill = _blend(base, colors["bg"], tint)
                    if sel and str(team).upper() != str(sel).upper():
                        fill = _blend(fill, colors["bg"], 0.65)
                    chart_canvas.create_polygon(pts, fill=fill, outline="")

                _wedge_mid[(str(mk), str(team).upper())] = (mx, my, mid_deg, extent, r_in, r_out)

                # ✅ LOGOS ONLY in the OUTER ring ("madeplayoffs")
                if str(mk) == "madeplayoffs":
                    h_fit = _max_logo_height_in_wedge(team, extent, r_in, r_out, r_place)
                    if h_fit >= 12:
                        norm = 0.0 if max_v <= 0 else max(0.0, min(1.0, vf / max_v))
                        scale = 0.65 + 0.35 * math.sqrt(norm)
                        h_logo = int(max(12, min(h_fit, math.floor(h_fit * scale))))

                        is_dim = bool(sel and str(team).upper() != str(sel).upper())
                        img = logo_bank.get(team, height=h_logo, dim=(PIL_OK and is_dim), dim_amt=0.60)
                        if img is not None:
                            _chart_imgs_live.append(img)
                            chart_canvas.create_image(mx, my, image=img, anchor="center")
                            if (not PIL_OK) and is_dim:
                                ww, hh = int(img.width()), int(img.height())
                                chart_canvas.create_rectangle(
                                    mx - ww/2, my - hh/2, mx + ww/2, my + hh/2,
                                    fill=colors["bg"], outline="", stipple="gray50"
                                )

                cum += extent
                lookup.append((cum, str(team).upper(), vf))

            _ring_lookup[str(mk)] = lookup

        gap_px = max(2, int(round(min(w, h) * 0.003)))
        for i in range(1, len(metric_order)):
            r = outer_r - i * thick
            chart_canvas.create_oval(
                cx - r, cy - r, cx + r, cy + r,
                outline=colors["bg"], width=gap_px
            )

        cup_h = int(max(18, inner_r * 1.55))
        cup_img = _load_cup_image(cup_h)
        if cup_img is not None:
            chart_canvas.create_image(cx, cy, image=cup_img, anchor="center")

        _set_chart_hover_outline(hover.get("team"), hover.get("metric"))

        if hover.get("team") and hover.get("metric"):
            team = str(hover["team"]).upper()
            mk = str(hover["metric"])
            s = _values_for(mk)
            if team in s.index and not pd.isna(s.loc[team]):
                v = _safe_float(s.loc[team])
                key = (mk, team)
                if key in _wedge_mid:
                    mx, my, *_ = _wedge_mid[key]
                    msg = f"{team}\n{v*100:.1f}%"
                    _hover_label_show(msg, mx, my)

    def _hit_test_chart(x: float, y: float) -> tuple[str, str] | tuple[None, None]:
        cx = _chart_center["cx"]
        cy = _chart_center["cy"]
        inner_r = _chart_center["inner"]
        outer_r = _chart_center["outer"]
        thick = _chart_center["thick"]

        dx = x - cx
        dy = y - cy
        rr = math.hypot(dx, dy)
        if rr < inner_r or rr > outer_r or thick <= 0:
            return (None, None)

        ring_i = int((outer_r - rr) // thick)
        ring_i = max(0, min(len(metric_order) - 1, ring_i))
        mk = str(metric_order[ring_i])

        theta_deg = math.degrees(math.atan2(dy, dx))
        phi = (theta_deg - _start0_deg) % 360.0

        lookup = _ring_lookup.get(mk, [])
        if not lookup:
            return (None, None)

        ends = [e for (e, _t, _v) in lookup]
        j = bisect_left(ends, phi)

        # ✅ Fix: float/rounding wrap near 360° (was killing hover)
        if j >= len(lookup):
            return (lookup[-1][1], mk)

        _end, team, _v = lookup[j]
        return (team, mk)

    def _on_chart_motion(event):
        team, mk = _hit_test_chart(event.x, event.y)

        if not team or not mk:
            hover["team"], hover["metric"] = None, None
            _hover_label_hide()
            _set_table_highlight(None, None)
            _set_chart_hover_outline(None, None)
            return

        s = _values_for(mk)
        v = _safe_float(s.loc[team]) if (team in s.index and not pd.isna(s.loc[team])) else float("nan")
        if pd.isna(v):
            hover["team"], hover["metric"] = None, None
            _hover_label_hide()
            _set_table_highlight(None, None)
            _set_chart_hover_outline(None, None)
            return

        hover["team"], hover["metric"] = team, mk

        key = (str(mk), str(team).upper())
        if key in _wedge_mid:
            mx, my, *_ = _wedge_mid[key]
            msg = f"{team}\n{v*100:.1f}%"
            _hover_label_show(msg, mx, my)
        else:
            _hover_label_hide()

        _set_table_highlight(str(team).upper(), str(mk))
        _set_chart_hover_outline(str(team).upper(), str(mk))

    def _on_chart_leave(_event=None):
        hover["team"], hover["metric"] = None, None
        _hover_label_hide()
        _set_table_highlight(None, None)
        _set_chart_hover_outline(None, None)

    def _on_chart_click(event):
        team, _mk = _hit_test_chart(event.x, event.y)
        if team:
            set_selected_team_code(team)

    chart_canvas.bind("<Motion>", _on_chart_motion)
    chart_canvas.bind("<Leave>", _on_chart_leave)
    chart_canvas.bind("<Button-1>", _on_chart_click)

    # ---- Stepper ----
    _slider_state = {"drag": False, "hover": False, "thumb": (0, 0, 0, 0)}
    hold_job = None
    hold_delta = 0

    def _slider_thumb_color() -> str:
        return _blend(BTN_BG, "#ffffff", 0.10) if (_slider_state["drag"] or _slider_state["hover"]) else BTN_BG

    def _draw_slider():
        slider.delete("all")
        w = max(1, int(slider.winfo_width() or 1))
        h = max(1, int(slider.winfo_height() or 1))

        pad = int(max(12, cell_width * 0.22))
        trough_h = int(max(10, cell_height * 0.40))
        thumb_w = int(max(28, cell_width * 0.55))
        thumb_h = int(max(22, cell_height * 0.95))

        x0 = pad
        x1 = w - pad
        if x1 <= x0:
            x1 = x0 + 1

        ty0 = (h - trough_h) / 2
        ty1 = ty0 + trough_h
        slider.create_rectangle(x0, ty0, x1, ty1, fill=TROUGH, outline="")

        if MAX_IDX <= 0:
            tx = x0
        else:
            usable = max(1, (x1 - x0 - thumb_w))
            tx = x0 + (selected_col_idx / MAX_IDX) * usable

        th0 = (h - thumb_h) / 2
        th1 = th0 + thumb_h
        _slider_state["thumb"] = (tx, th0, tx + thumb_w, th1)
        slider.create_rectangle(tx, th0, tx + thumb_w, th1, fill=_slider_thumb_color(), outline="")

    def _idx_from_x(x: float) -> int:
        w = max(1, int(slider.winfo_width() or 1))
        pad = int(max(12, cell_width * 0.22))
        thumb_w = int(max(28, cell_width * 0.55))

        x0 = pad
        x1 = w - pad
        if MAX_IDX <= 0 or x1 <= x0:
            return 0
        usable = max(1, (x1 - x0 - thumb_w))
        rel = (x - x0 - thumb_w / 2) / usable
        idx = int(round(rel * MAX_IDX))
        return max(0, min(MAX_IDX, idx))

    def redraw_all():
        draw_table()
        draw_chart()
        _draw_slider()

    def set_selected(idx: int):
        nonlocal selected_col_idx
        idx = max(0, min(int(idx), MAX_IDX))
        selected_col_idx = idx

        if metric_order:
            _table_sort_by_metric_chain(list(reversed(metric_order)))
        else:
            _table_sort_by_team()

        hover["team"], hover["metric"] = None, None
        _hover_label_hide()
        redraw_all()

    def _step(delta: int):
        set_selected(selected_col_idx + delta)

    def _hold_stop(_event=None):
        nonlocal hold_job
        if hold_job is not None:
            try:
                parent.after_cancel(hold_job)
            except Exception:
                pass
        hold_job = None
        _slider_state["drag"] = False
        _draw_slider()

    def _hold_tick():
        nonlocal hold_job
        if hold_job is None:
            return
        _step(hold_delta)
        hold_job = parent.after(45, _hold_tick)

    def _hold_start(delta: int):
        nonlocal hold_job, hold_delta
        hold_delta = delta
        _step(delta)
        _hold_stop()
        hold_job = parent.after(350, _hold_tick)

    def _slider_press(e):
        _slider_state["drag"] = True
        set_selected(_idx_from_x(e.x))
        return "break"

    def _slider_drag(e):
        if not _slider_state["drag"]:
            return "break"
        set_selected(_idx_from_x(e.x))
        return "break"

    def _slider_release(_e):
        _slider_state["drag"] = False
        _draw_slider()
        return "break"

    slider.bind("<Button-1>", _slider_press)
    slider.bind("<B1-Motion>", _slider_drag)
    slider.bind("<ButtonRelease-1>", _slider_release)
    slider.bind("<Enter>", lambda _e: (_slider_state.__setitem__("hover", True), _draw_slider()))
    slider.bind("<Leave>", lambda _e: (_slider_state.__setitem__("hover", False), _draw_slider()))
    slider.bind("<Configure>", lambda _e: _draw_slider())

    prev_btn.bind("<ButtonPress-1>", lambda _e: (_hold_start(-1), "break")[1])
    prev_btn.bind("<ButtonRelease-1>", _hold_stop, add="+")
    prev_btn.bind("<Leave>", _hold_stop, add="+")
    next_btn.bind("<ButtonPress-1>", lambda _e: (_hold_start(1), "break")[1])
    next_btn.bind("<ButtonRelease-1>", _hold_stop, add="+")
    next_btn.bind("<Leave>", _hold_stop, add="+")

    table_canvas.bind("<Configure>", lambda _e: draw_table())
    chart_canvas.bind("<Configure>", lambda _e: draw_chart())

    def reset_tab():
        nonlocal selected_col_idx, table_order
        selected_col_idx = MAX_IDX
        table_order = default_table_order[:]
        if metric_order:
            _table_sort_by_metric_chain(list(reversed(metric_order)))
        hover["team"], hover["metric"] = None, None
        _hover_label_hide()
        try:
            table_canvas.yview_moveto(0.0)
            table_canvas.xview_moveto(0.0)
        except Exception:
            pass
        redraw_all()

    redraw_all()
    return {"redraw": redraw_all, "reset": reset_tab}
