import datetime as dt
import math
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import ttk
from typing import Any, Callable, Literal, Optional, cast

import pandas as pd

from hockey_app.domain.colors import (
    _blend,
    _hex_from_hash,
    _hex_to_rgb,
    _rel_luminance,
    _rgb_to_hex,
    bar_gradient_pair,
    theme_adjusted_line_color,
)
from hockey_app.domain.teams import DIVS_MASTER, TEAM_TO_CONF, canon_team_code

try:
    from PIL import Image, ImageOps, ImageTk  # type: ignore

    PIL_OK = True
except Exception:
    Image = None
    ImageTk = None
    ImageOps = None
    PIL_OK = False

DARK_CANVAS_BG = "#262626"
TkImg = Any
LogoBank = Any
_PWHL_LOGO_CACHE: dict[tuple[str, int], TkImg] = {}
_PWHL_LOGOS_DIR = Path(__file__).resolve().parents[2] / "assets" / "pwhl_logos"
_PWHL_CODE_ALIASES: dict[str, str] = {"MON": "MTL", "NYC": "NY"}


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


def _canon_pwhl(code: str) -> str:
    c = str(code or "").upper().strip()
    return _PWHL_CODE_ALIASES.get(c, c)


def _pwhl_logo_candidates(code: str) -> list[Path]:
    c = _canon_pwhl(code)
    names = {
        "BOS": ["BOS", "boston", "fleet"],
        "MIN": ["MIN", "minnesota", "frost"],
        "MTL": ["MTL", "MON", "montreal", "victoire"],
        "NY": ["NY", "NYC", "newyork", "new_york", "sirens"],
        "OTT": ["OTT", "ottawa", "charge"],
        "TOR": ["TOR", "toronto", "sceptres"],
        "VAN": ["VAN", "vancouver"],
        "SEA": ["SEA", "seattle"],
    }.get(c, [c])
    out: list[Path] = []
    for n in names:
        out.append(_PWHL_LOGOS_DIR / f"{n}.png")
    return out


def _pwhl_logo_get(code: str, height: int, master: tk.Misc | None) -> TkImg | None:
    h = int(max(1, height))
    key = (_canon_pwhl(code), h)
    if key in _PWHL_LOGO_CACHE:
        return _PWHL_LOGO_CACHE[key]

    p: Path | None = None
    for cand in _pwhl_logo_candidates(code):
        if cand.exists():
            p = cand
            break
    if p is None:
        return None

    try:
        if PIL_OK:
            img = Image.open(str(p)).convert("RGBA")  # type: ignore
            w0, h0 = img.size  # type: ignore
            if h0 <= 0:
                return None
            w = max(1, int(round((w0 / h0) * h)))
            try:
                resample = Image.Resampling.LANCZOS  # type: ignore
            except Exception:
                resample = Image.LANCZOS  # type: ignore
            out = img.resize((w, h), resample=resample)  # type: ignore
            tkimg = ImageTk.PhotoImage(out)  # type: ignore
        else:
            if master is not None:
                tkimg = tk.PhotoImage(master=master, file=str(p))
            else:
                tkimg = tk.PhotoImage(file=str(p))
            h0 = int(tkimg.height())
            if h0 > h and h0 > 0:
                factor = max(1, int(math.ceil(h0 / h)))
                tkimg = tkimg.subsample(factor)
        _PWHL_LOGO_CACHE[key] = tkimg
        return tkimg
    except Exception:
        return None

def render_df_heatmap_with_graph(
    parent: ttk.Frame,
    df: pd.DataFrame,
    *,
    tab_key: str,
    tab_title: str,
    team_colors: dict[str, str],
    logo_bank: LogoBank,
    original_order: list[str],
    team_col_width: int,
    cell_width: int,
    get_selected_team_code,
    set_selected_team_code=None,
    cell_height: int = 22,
    graph_pad_y: int = 12,
    hscroll_units: int = 1,
    start_date: dt.date,
    value_kind: Literal["percent", "number"] = "percent",
    allow_negative_values: bool = False,
    stats_league: Literal["NHL", "PWHL"] = "NHL",
    initial_team_order: Optional[list[str]] = None,
    visible_row_count: Optional[int] = None,
) -> dict[str, Callable[[], None]]:
    colors = {
        "canvas_bg": DARK_CANVAS_BG,
        "grid": "#323232",
        "header_bg": "#2f2f2f",
        "header_text": "#f0f0f0",
        "team_bg": "#2a2a2a",
        "team_text": "#f0f0f0",
        "cell_text": "#f7f7f7",
        "empty_cell": DARK_CANVAS_BG,
        "graph_bg": DARK_CANVAS_BG,
        "graph_grid": "#3a3a3a",
        "graph_text": "#f0f0f0",
        "bar_bg": DARK_CANVAS_BG,
        "bar_grid": "#3a3a3a",
        "bar_text": "#f0f0f0",
    }
    heat_darken, heat_blend_bg, text_lum_split = 0.56, 0.12, 0.40

    for child in parent.winfo_children():
        child.destroy()

    parent.grid_rowconfigure(0, weight=1)
    parent.grid_columnconfigure(0, weight=1)

    outer = ttk.Frame(parent, padding=0)
    outer.grid(row=0, column=0, sticky="nsew")

    outer.grid_rowconfigure(1, weight=1)
    outer.grid_columnconfigure(1, weight=1)
    outer.grid_columnconfigure(2, weight=0)

    corner = tk.Canvas(outer, height=cell_height, width=team_col_width, highlightthickness=0, bg=colors["header_bg"])
    header = tk.Canvas(outer, height=cell_height, highlightthickness=0, bg=colors["header_bg"])
    bar_header = tk.Canvas(outer, height=cell_height, highlightthickness=0, bg=colors["header_bg"])
    vspacer = tk.Canvas(outer, height=cell_height, width=18, highlightthickness=0, bg=colors["header_bg"])

    corner.grid(row=0, column=0, sticky="nsew")
    header.grid(row=0, column=1, sticky="nsew")
    bar_header.grid(row=0, column=2, sticky="nsew")
    vspacer.grid(row=0, column=3, sticky="nsew")

    paned = tk.PanedWindow(
        outer,
        orient=tk.VERTICAL,
        bd=0,
        relief="flat",
        sashwidth=6,
        sashrelief="flat",
        showhandle=True,
        background=colors["canvas_bg"],
    )
    paned.grid(row=1, column=0, columnspan=4, sticky="nsew")

    # ---- Top pane: table + bar chart ----
    table_frame = ttk.Frame(paned, padding=0)
    table_frame.grid_rowconfigure(0, weight=1)
    table_frame.grid_columnconfigure(1, weight=1)

    teams = tk.Canvas(table_frame, width=team_col_width, highlightthickness=0, bg=colors["team_bg"])
    data = tk.Canvas(table_frame, highlightthickness=0, bg=colors["canvas_bg"])
    vscroll = ttk.Scrollbar(table_frame, orient="vertical")

    bar_frame = tk.Frame(table_frame, bg=colors["bar_bg"], bd=0, highlightthickness=0)
    bar_frame.grid_rowconfigure(0, weight=1)
    bar_frame.grid_columnconfigure(0, weight=1)

    bars = tk.Canvas(bar_frame, highlightthickness=0, bg=colors["bar_bg"])
    bars.grid(row=0, column=0, sticky="nsew")

    teams.grid(row=0, column=0, sticky="nsew")
    data.grid(row=0, column=1, sticky="nsew")
    bar_frame.grid(row=0, column=2, sticky="nsew")
    vscroll.grid(row=0, column=3, sticky="ns")

    # ---- Bottom pane: line graph + right column ----
    graph_frame = ttk.Frame(paned, padding=0)
    graph_frame.grid_rowconfigure(0, weight=1)
    graph_frame.grid_columnconfigure(1, weight=1)

    axis = tk.Canvas(graph_frame, width=team_col_width, highlightthickness=0, bg=colors["graph_bg"])
    graph = tk.Canvas(graph_frame, highlightthickness=0, bg=colors["graph_bg"])

    right_col = tk.Frame(graph_frame, bg=colors["graph_bg"], bd=0, highlightthickness=0)
    right_col.grid_columnconfigure(0, weight=1)
    right_col.grid_rowconfigure(2, weight=1)

    bar_frame.grid_propagate(False)
    right_col.grid_propagate(False)

    step_row = tk.Frame(right_col, bg=colors["graph_bg"], bd=0, highlightthickness=0)
    title_lbl = tk.Label(
        right_col,
        text="" if tab_key in {"points", "goal_differential"} else tab_title,
        bg=colors["graph_bg"],
        fg=colors["graph_text"],
        bd=0,
        highlightthickness=0,
        font=("TkDefaultFont", 18),
        anchor="center",
    )
    logos_canvas = tk.Canvas(right_col, bg=colors["graph_bg"], highlightthickness=0)

    step_row.grid(row=0, column=0, sticky="ew")
    title_lbl.grid(row=1, column=0, sticky="ew", pady=(1, 0))
    logos_canvas.grid(row=2, column=0, sticky="nsew", pady=(0, 0))


    g_v_spacer = tk.Canvas(graph_frame, width=18, highlightthickness=0, bg=colors["graph_bg"])

    axis.grid(row=0, column=0, sticky="nsew")
    graph.grid(row=0, column=1, sticky="nsew")
    right_col.grid(row=0, column=2, sticky="nsew")
    g_v_spacer.grid(row=0, column=3, sticky="nsew")

    paned.add(table_frame)
    paned.add(graph_frame)

    hscroll = ttk.Scrollbar(outer, orient="horizontal")
    hscroll.grid(row=2, column=1, columnspan=2, sticky="ew")
    vblank = tk.Canvas(outer, height=18, width=18, highlightthickness=0, bg=colors["header_bg"])
    vblank.grid(row=2, column=3, sticky="nsew")

    font = tkfont.nametofont("TkDefaultFont")

    # ---------------- Helpers ----------------
    def _apply_heat_adjust(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
        r, g, b = rgb
        r, g, b = int(r * heat_darken), int(g * heat_darken), int(b * heat_darken)
        r, g, b = _hex_to_rgb(_blend(_rgb_to_hex(r, g, b), colors["canvas_bg"], heat_blend_bg))
        return r, g, b

    def _heat_color_from_rank01(t: float) -> str:
        t = max(0.0, min(1.0, t))
        t = round(t * 31) / 31
        if t <= 0.5:
            u = t * 2.0
            rgb = (255, int(255 * u), 0)
        else:
            u = (t - 0.5) * 2.0
            rgb = (int(255 * (1.0 - u)), 255, 0)
        r, g, b = _apply_heat_adjust(rgb)
        return _rgb_to_hex(r, g, b)

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

    show_percent = (value_kind == "percent")
    stats_league_u = str(stats_league or "NHL").upper()

    def _fmt_value(v: float) -> str:
        if show_percent:
            return f"{v * 100:.1f}%"
        return f"{int(round(v))}"

    def _tab_ymax(local_df: pd.DataFrame) -> float:
        s = pd.to_numeric(local_df.to_numpy().ravel(), errors="coerce")
        s = s[~pd.isna(s)]
        return 0.05 if s.size == 0 else max(0.05, float(s.max()))

    def _tab_ymin(local_df: pd.DataFrame) -> float:
        s = pd.to_numeric(local_df.to_numpy().ravel(), errors="coerce")
        s = s[~pd.isna(s)]
        if s.size == 0:
            return 0.0
        if show_percent:
            return 0.0
        return float(s.min())

    def _visible_col_bounds() -> tuple[int, int]:
        if len(current_df.columns) == 0:
            return (0, 0)
        left_px = max(0.0, _left_px(data))
        view_w = float(max(1, data.winfo_width() or 1))
        i0 = int(max(0, min(len(current_df.columns) - 1, math.floor(left_px / float(cell_width)))))
        i1 = int(max(0, min(len(current_df.columns) - 1, math.floor((left_px + view_w - 1) / float(cell_width)))))
        return (i0, i1)

    def _col_series(i: int) -> pd.Series:
        if len(current_df.columns) == 0:
            return pd.Series(dtype="float64")
        idx = max(0, min(int(i), len(current_df.columns) - 1))
        col = current_df.columns[idx]
        return pd.to_numeric(current_df[col], errors="coerce").dropna()

    def _scale_df() -> pd.DataFrame:
        # Percent tabs keep full historical range. Numeric tabs (Points) scale to
        # season-to-selected-day to avoid "fixed full-season" axes while stepping.
        if show_percent or len(current_df.columns) == 0:
            return current_df
        end_idx = max(0, min(selected_col_idx, len(current_df.columns) - 1))
        cols = list(current_df.columns[: end_idx + 1])
        if not cols:
            return current_df
        return current_df[cols]

    def _current_ymax() -> float:
        if not show_percent and len(current_df.columns) > 0:
            _i0, i1 = _visible_col_bounds()
            s = _col_series(i1)
            ymax = float(s.max()) if not s.empty else 1.0
        else:
            ymax = _tab_ymax(_scale_df())
        if show_percent:
            return max(0.05, min(1.0, ymax))
        return max(1.0, ymax)

    def _current_ymin() -> float:
        if not show_percent and len(current_df.columns) > 0:
            i0, _i1 = _visible_col_bounds()
            s = _col_series(i0)
            ymin = float(s.min()) if not s.empty else 0.0
        else:
            ymin = _tab_ymin(_scale_df())
        if show_percent:
            return 0.0
        if allow_negative_values:
            return ymin
        return max(0.0, ymin)

    def choose_major_tick_step(y_max: float, usable_px: float) -> float:
        if y_max <= 0:
            return 0.2 if show_percent else 10.0
        target_px = 52.0
        desired_lines = max(3, int(usable_px / target_px) + 1)
        if show_percent:
            candidates = (
                [0.5, 1, 2, 2.5, 5, 10, 20, 25, 50] if y_max * 100 > 10
                else [0.1, 0.2, 0.5, 1, 2, 2.5, 5]
            )
            y_metric = y_max * 100.0
            best_step, best_score = 20.0, 1e9
            for step in candidates:
                n_lines = int(math.floor(y_metric / step)) + 1
                if n_lines < 2:
                    continue
                clutter = max(0, n_lines - 12) * 3.0
                score = abs(n_lines - desired_lines) + clutter
                if abs(y_metric - 100.0) < 1e-6 and step == 20:
                    score -= 0.25
                if score < best_score:
                    best_score, best_step = score, step
            return best_step / 100.0

        candidates_num = [1, 2, 5, 10, 20, 25, 50, 100]
        best_step, best_score = 10.0, 1e9
        for step in candidates_num:
            n_lines = int(math.floor(y_max / step)) + 1
            if n_lines < 2:
                continue
            clutter = max(0, n_lines - 12) * 3.0
            score = abs(n_lines - desired_lines) + clutter
            if score < best_score:
                best_score, best_step = score, step
        return float(best_step)

    # ----- X/Y scroll pixel helpers -----
    def _scrollregion_w(canvas: tk.Canvas, fallback: float) -> float:
        sr = canvas.cget("scrollregion")
        if not sr:
            return float(fallback)
        x0, _y0, x1, _y1 = map(float, sr.split())
        return float(x1 - x0)

    def _view_w(canvas: tk.Canvas) -> float:
        return float(max(1, canvas.winfo_width()))

    def _max_left_px(canvas: tk.Canvas, fallback: float) -> float:
        return max(0.0, _scrollregion_w(canvas, fallback) - _view_w(canvas))

    def _left_px(canvas: tk.Canvas) -> float:
        try:
            return float(canvas.canvasx(0))
        except Exception:
            try:
                frac = float(canvas.xview()[0])
                sr_w = _scrollregion_w(canvas, float(canvas.winfo_width() or 1))
                return frac * sr_w
            except Exception:
                return 0.0

    def _set_left_px(canvas: tk.Canvas, left: float, fallback: float) -> None:
        left = max(0.0, min(_max_left_px(canvas, fallback), float(left)))
        sr_w = _scrollregion_w(canvas, fallback)
        if sr_w <= 0:
            return
        canvas.xview_moveto(max(0.0, min(1.0, left / sr_w)))

    def _scrollregion_h(canvas: tk.Canvas, fallback: float) -> float:
        sr = canvas.cget("scrollregion")
        if not sr:
            return float(fallback)
        _x0, y0, _x1, y1 = map(float, sr.split())
        return float(y1 - y0)

    def _view_h(canvas: tk.Canvas) -> float:
        return float(max(1, canvas.winfo_height()))

    def _max_top_px(canvas: tk.Canvas, fallback: float) -> float:
        return max(0.0, _scrollregion_h(canvas, fallback) - _view_h(canvas))

    def _top_px(canvas: tk.Canvas) -> float:
        try:
            return float(canvas.canvasy(0))
        except Exception:
            try:
                return float(canvas.yview()[0]) * _scrollregion_h(canvas, float(canvas.winfo_height() or 1))
            except Exception:
                return 0.0

    def _set_top_px(canvas: tk.Canvas, top: float, fallback: float) -> None:
        top = max(0.0, min(_max_top_px(canvas, fallback), float(top)))
        sr_h = _scrollregion_h(canvas, fallback)
        if sr_h <= 0:
            return
        canvas.yview_moveto(max(0.0, min(1.0, top / sr_h)))

    def sync_x_from_data() -> None:
        left = _left_px(data)
        _set_left_px(header, left, float(total_w))
        _set_left_px(graph, left, float(total_w))

    def _ensure_col_visible(idx: int, *, margin_cols: float = 0.75) -> None:
        if len(current_df.columns) == 0:
            return
        idx = max(0, min(int(idx), len(current_df.columns) - 1))

        view_w = float(max(1, data.winfo_width() or 1))
        left = float(_left_px(data))
        right = left + view_w

        col_left = float(idx * cell_width)
        col_right = col_left + float(cell_width)
        margin = float(cell_width) * float(margin_cols)

        target_left = left
        if col_left - margin < left:
            target_left = max(0.0, col_left - margin)
        elif col_right + margin > right:
            target_left = max(0.0, col_right + margin - view_w)

        target_left = round(target_left / float(cell_width)) * float(cell_width)
        _set_left_px(data, target_left, float(total_w))
        sync_x_from_data()

    # ---------------- Scrolling wiring ----------------
    def yview(*args):
        teams.yview(*args)
        data.yview(*args)
        bars.yview(*args)

    vscroll.config(command=yview)
    teams.configure(yscrollcommand=vscroll.set)
    data.configure(yscrollcommand=vscroll.set)
    bars.configure(yscrollcommand=vscroll.set)

    def xscroll_command(*args):
        data.xview(*args)
        sync_x_from_data()
        draw_graph()

    hscroll.config(command=xscroll_command)
    header.configure(xscrollcommand=hscroll.set)
    data.configure(xscrollcommand=hscroll.set)
    graph.configure(xscrollcommand=hscroll.set)

    # ---------------- Data state ----------------
    base_df = df.copy()
    current_df = base_df.copy()
    ranks01 = _ranks01(current_df)

    total_w = len(current_df.columns) * cell_width
    header.configure(scrollregion=(0, 0, total_w, cell_height))
    data.configure(scrollregion=(0, 0, total_w, 1))
    graph.configure(scrollregion=(0, 0, total_w, 1))

    selected_col_idx = len(current_df.columns) - 1

    def _team_sort_key_value(team_code: Any) -> str:
        return str(team_code).upper()

    def _sort_by_selected_col() -> None:
        nonlocal current_df
        if len(current_df.columns) == 0:
            return
        col = current_df.columns[max(0, min(selected_col_idx, len(current_df.columns) - 1))]
        work = current_df.copy()
        work["__sort_val__"] = pd.to_numeric(work[col], errors="coerce")
        work["__sort_team__"] = [_team_sort_key_value(t) for t in work.index]
        work = work.sort_values(
            by=["__sort_val__", "__sort_team__"],
            ascending=[False, True],
            na_position="last",
            kind="mergesort",
        )
        current_df = work.drop(columns=["__sort_val__", "__sort_team__"])

    locked_default_order: list[str] = []
    if isinstance(initial_team_order, list) and initial_team_order:
        idx_set = {str(code) for code in current_df.index}
        seen: set[str] = set()
        for raw in initial_team_order:
            code = str(raw)
            if code in idx_set and code not in seen:
                locked_default_order.append(code)
                seen.add(code)

    def _apply_locked_default_order() -> bool:
        nonlocal current_df
        if not locked_default_order:
            return False
        current_codes = [str(code) for code in current_df.index]
        current_set = set(current_codes)
        ordered = [code for code in locked_default_order if code in current_set]
        ordered_set = set(ordered)
        tail = [code for code in current_codes if code not in ordered_set]
        current_df = current_df.reindex(ordered + tail)
        return True

    # Default order can be injected by caller (e.g., Cup-first ranking).
    if not _apply_locked_default_order():
        # Fallback: sort by active (today/rightmost) column.
        _sort_by_selected_col()

    def _pretty_date_for_idx(idx: int) -> str:
        d = start_date + dt.timedelta(days=int(idx))
        return f"{d.day} {d.strftime('%b')} {d.year}"

    # ---------------- Right column width: snap to full date-columns ----------------
    right_col_w = {"w": 360}
    RIGHT_COL_SCALE = 1.50
    RIGHT_COL_MAX_FRAC = 0.55

    def _compute_right_col_width(total_px: int, vspacer_px: int) -> int:
        total_px = max(1, int(total_px))
        vspacer_px = max(0, int(vspacer_px))

        step_row.update_idletasks()
        min_btn_w = max(1, int(prev_btn.winfo_reqwidth() or 1))
        min_btn_w2 = max(1, int(next_btn.winfo_reqwidth() or 1))
        min_slider_mid = int(max(1, cell_width * 2.4))
        min_right = int(min_btn_w + min_btn_w2 + min_slider_mid)

        max_right = int(max(min_right, total_px * 0.42))

        fixed_left = int(team_col_width + vspacer_px)
        avail_for_data_and_right = total_px - fixed_left
        if avail_for_data_and_right <= min_right + cell_width:
            return int(max(min_right, min(avail_for_data_and_right, max_right)))

        k = int((avail_for_data_and_right - min_right) // cell_width)
        k = max(1, k)

        right = int(avail_for_data_and_right - k * cell_width)

        while k > 1 and right < min_right:
            k -= 1
            right = int(avail_for_data_and_right - k * cell_width)

        while right > max_right:
            k2 = k + 1
            right2 = int(avail_for_data_and_right - k2 * cell_width)
            if right2 < min_right:
                break
            k = k2
            right = right2

        right = int(round(right * RIGHT_COL_SCALE))
        right = min(right, int(avail_for_data_and_right - cell_width))
        right = max(min_right, right)
        right = min(right, int(total_px * RIGHT_COL_MAX_FRAC))
        return int(right)

    def _apply_right_col_width():
        outer.update_idletasks()

        vsp_w = int(vscroll.winfo_reqwidth() or 18)
        vspacer.config(width=vsp_w)
        vblank.config(width=vsp_w)
        g_v_spacer.config(width=vsp_w)

        total_px = int(outer.winfo_width() or 1)
        rw = _compute_right_col_width(total_px, vsp_w)
        right_col_w["w"] = rw

        outer.grid_columnconfigure(2, minsize=rw, weight=0)
        table_frame.grid_columnconfigure(2, minsize=rw, weight=0)
        graph_frame.grid_columnconfigure(2, minsize=rw, weight=0)

        for w in (bar_header, bar_frame, bars, right_col, logos_canvas):
            try:
                w.config(width=rw)
            except Exception:
                pass

    # ---------------- Bar header ----------------
    def _update_bar_header():
        bar_header.delete("all")
        bar_header.create_rectangle(0, 0, right_col_w["w"], cell_height, fill=colors["header_bg"], outline=colors["grid"])
        if len(current_df.columns):
            bar_header.create_text(
                right_col_w["w"] / 2,
                cell_height / 2,
                text=_pretty_date_for_idx(selected_col_idx),
                fill=colors["header_text"],
                anchor="center",
            )

    def draw_header():
        _apply_right_col_width()

        corner.delete("all")
        header.delete("all")
        vspacer.delete("all")

        corner.create_rectangle(0, 0, team_col_width, cell_height, fill=colors["header_bg"], outline=colors["grid"])
        corner.create_text(
            team_col_width / 2,
            cell_height / 2,
            text="Team",
            fill=colors["header_text"],
            anchor="center",
        )

        header.create_rectangle(0, 0, total_w, cell_height, fill=colors["header_bg"], outline=colors["grid"])
        for j, col in enumerate(current_df.columns):
            x0 = j * cell_width
            x1 = x0 + cell_width
            header.create_rectangle(x0, 0, x1, cell_height, fill=colors["header_bg"], outline=colors["grid"])
            header.create_text((x0 + x1) / 2, cell_height / 2, text=str(col), fill=colors["header_text"], anchor="center")

        vsp_w = int(vscroll.winfo_reqwidth() or 18)
        vspacer.create_rectangle(0, 0, vsp_w, cell_height, fill=colors["header_bg"], outline=colors["grid"])

        _update_bar_header()

    # ---------------- Table draw ----------------
    def draw_table():
        nonlocal ranks01
        ranks01 = _ranks01(current_df)

        y_frac = data.yview()[0] if data.yview() else 0.0
        left = _left_px(data)

        teams.delete("all")
        data.delete("all")

        total_h = len(current_df.index) * cell_height
        teams.configure(scrollregion=(0, 0, team_col_width, total_h))
        data.configure(scrollregion=(0, 0, total_w, total_h))

        gap = 3
        pad_lr = 2
        sel = get_selected_team_code()

        for i, team in enumerate(current_df.index):
            y_top = i * cell_height
            y_bot = y_top + cell_height
            teams.create_rectangle(0, y_top, team_col_width, y_bot, fill=colors["team_bg"], outline=colors["grid"])

            code = str(team)
            if stats_league_u == "PWHL":
                img = _pwhl_logo_get(code, height=18, master=parent.winfo_toplevel())
            else:
                img = logo_bank.get(code, height=18, dim=False)

            text_w = _measure_text_px(font, code)
            img_w = int(img.width()) if img else 0
            group_w = text_w + (gap + img_w if img else 0)
            start_x = max(pad_lr, (team_col_width - group_w) / 2)

            teams.create_text(start_x, (y_top + y_bot) / 2, text=code, fill=colors["team_text"], anchor="w")
            if img:
                x_img = start_x + text_w + gap + img_w / 2
                x_img = min(x_img, team_col_width - pad_lr - img_w / 2)
                teams.create_image(x_img, (y_top + y_bot) / 2, image=img, anchor="center")

            if sel and code == sel:
                teams.create_rectangle(1, y_top + 1, team_col_width - 1, y_bot - 1, outline="#f0f0f0", width=2)

        for i, team in enumerate(current_df.index):
            y_top = i * cell_height
            y_bot = y_top + cell_height
            for j, col in enumerate(current_df.columns):
                x_left = j * cell_width
                x_right = x_left + cell_width
                val = current_df.at[team, col]

                if pd.isna(val):
                    fill, text, text_fill = colors["empty_cell"], "", colors["cell_text"]
                else:
                    t = ranks01[str(col)].get(team, 0.5)
                    fill = _heat_color_from_rank01(t)
                    text = _fmt_value(_safe_float(val))
                    text_fill = "#111111" if _rel_luminance(fill) > text_lum_split else colors["cell_text"]

                data.create_rectangle(x_left, y_top, x_right, y_bot, fill=fill, outline=colors["grid"])
                if text:
                    data.create_text((x_left + x_right) / 2, (y_top + y_bot) / 2, text=text, fill=text_fill, anchor="center")

            if sel and str(team) == sel:
                data.create_rectangle(0, y_top + 1, total_w, y_bot - 1, outline="#f0f0f0", width=2)

        teams.yview_moveto(y_frac)
        data.yview_moveto(y_frac)
        _set_left_px(data, left, float(total_w))
        sync_x_from_data()

    def _on_team_click(event):
        if not callable(set_selected_team_code):
            return "break"
        y = float(teams.canvasy(event.y))
        if y < 0:
            return "break"
        i = int(y // max(1, cell_height))
        if 0 <= i < len(current_df.index):
            try:
                set_selected_team_code(str(current_df.index[i]))
            except Exception:
                pass
        return "break"

    # ---------------- Graph draw ----------------
    def draw_graph():
        g_h = max(int(graph.winfo_height() or 1), 1)

        axis.delete("all")
        graph.delete("all")

        y_min = _current_ymin()
        y_max = _current_ymax()
        if y_max <= y_min:
            y_max = y_min + (1.0 if not show_percent else 0.05)
        graph.configure(scrollregion=(0, 0, total_w, g_h))
        axis.create_rectangle(0, 0, team_col_width, g_h, fill=colors["graph_bg"], outline=colors["grid"])

        usable = max(20, g_h - 2 * graph_pad_y)

        def y_for(p: float) -> float:
            p = max(y_min, min(y_max, p))
            span = max(1e-9, (y_max - y_min))
            return graph_pad_y + (1.0 - ((p - y_min) / span)) * usable

        step = max(1e-9, choose_major_tick_step(y_max - y_min, usable))
        ticks: list[float] = []
        t = y_min
        while t <= y_max + 1e-9:
            ticks.append(t)
            t += step
        if (not ticks) or abs(ticks[-1] - y_max) > (step * 0.25):
            ticks.append(y_max)

        if show_percent:
            step_pct = step * 100.0
            fmt = (lambda v: f"{v*100:.1f}%") if step_pct < 1.0 else (lambda v: f"{v*100:.0f}%")
        else:
            fmt = lambda v: f"{int(round(v))}"

        label_pad = 6
        label_x = team_col_width - label_pad

        for p in ticks:
            y = y_for(p)
            axis.create_text(label_x, y, text=fmt(p), fill=colors["graph_text"], anchor="e")
            graph.create_line(0, y, total_w, y, fill=colors["graph_grid"])

        # Goal-differential style tabs can cross zero; draw an explicit zero guide.
        if allow_negative_values and (y_min < 0.0 < y_max):
            y0 = y_for(0.0)
            axis.create_text(label_x, y0, text="0", fill=colors["graph_text"], anchor="e")
            graph.create_line(0, y0, total_w, y0, fill="#6a6a6a", width=2)

        sel = get_selected_team_code()

        for team in current_df.index:
            s = pd.to_numeric(current_df.loc[team], errors="coerce")
            segs: list[list[float]] = []
            seg: list[float] = []

            for j, col in enumerate(current_df.columns):
                v = s.loc[col]
                if pd.isna(v):
                    if len(seg) >= 4:
                        segs.append(seg)
                    seg = []
                    continue
                seg.extend([j * cell_width + cell_width / 2, y_for(_safe_float(v))])

            if len(seg) >= 4:
                segs.append(seg)
            if not segs:
                continue

            code = str(team).upper()
            base = team_colors.get(code, _hex_from_hash(code))
            lc = theme_adjusted_line_color(code, base)

            width = 2
            if sel and code == sel:
                width = 4
                lc = _blend(lc, "#ffffff", 0.15)
            elif sel and code != sel:
                lc = _blend(lc, colors["graph_bg"], 0.70)
                width = 2

            for pts in segs:
                graph.create_line(*pts, fill=lc, width=width, smooth=True, splinesteps=12)

        sync_x_from_data()

    graph.bind("<Configure>", lambda _e: draw_graph())
    axis.bind("<Configure>", lambda _e: draw_graph())

    # ---------------- Bar chart (right) ----------------
    _bar_imgs_live: list[TkImg] = []
    _grad_cache: dict[tuple[str, int, int, str, str], TkImg] = {}
    _grad_cache_order: list[tuple[str, int, int, str, str]] = []
    GRAD_CACHE_MAX = 800

    def _cache_grad(key, tkimg: TkImg) -> TkImg:
        if key in _grad_cache:
            return _grad_cache[key]
        _grad_cache[key] = tkimg
        _grad_cache_order.append(key)
        if len(_grad_cache_order) > GRAD_CACHE_MAX:
            old = _grad_cache_order.pop(0)
            _grad_cache.pop(old, None)
        return tkimg

    def _bar_gradient_colors(team_code: str) -> tuple[str, str]:
        c0, c1 = bar_gradient_pair(team_code, team_colors)
        c0 = _blend(c0, colors["bar_bg"], 0.35)
        c1 = _blend(c1, colors["bar_bg"], 0.35)

        sel = get_selected_team_code()
        if sel and str(team_code).upper() == str(sel).upper():
            c0 = _blend(c0, "#ffffff", 0.10)
            c1 = _blend(c1, "#ffffff", 0.10)
        elif sel and str(team_code).upper() != str(sel).upper():
            c0 = _blend(c0, colors["bar_bg"], 0.70)
            c1 = _blend(c1, colors["bar_bg"], 0.70)
        return c0, c1

    def _gradient_photo(width_px: int, height_px: int, c0: str, c1: str, team_code: str) -> TkImg | None:
        if not PIL_OK:
            return None

        w = int(max(1, width_px))
        h = int(max(1, height_px))
        key = (str(team_code).upper(), w, h, c0, c1)
        if key in _grad_cache:
            return _grad_cache[key]

        ramp = Image.new("L", (w, 1))  # type: ignore
        if w == 1:
            ramp.putdata([255])  # type: ignore
        else:
            ramp.putdata([int(255 * x / (w - 1)) for x in range(w)])  # type: ignore

        grad = ramp.resize((w, h))  # type: ignore
        grad = ImageOps.colorize(grad, black=c0, white=c1)  # type: ignore
        tkimg = ImageTk.PhotoImage(grad.convert("RGBA"))  # type: ignore
        return _cache_grad(key, tkimg)

    def _draw_gradient_fallback(canvas: tk.Canvas, x0: float, y0: float, x1: float, y1: float, c0: str, c1: str):
        width = max(1.0, x1 - x0)
        steps = int(min(60, max(14, width / 10.0)))
        for k in range(steps):
            t0 = k / steps
            t1 = (k + 1) / steps
            fill = _blend(c0, c1, (t0 + t1) / 2.0)
            xa = x0 + width * t0
            xb = x0 + width * t1
            canvas.create_rectangle(xa, y0, xb, y1, fill=fill, outline="")

    _autofocus = {"suspended": False}

    def _ensure_selected_team_visible(center_if_needed: bool = False):
        view_h = float(max(1, data.winfo_height() or 1))
        one_row_mode = view_h <= float(cell_height) * 1.25

        if _autofocus.get("suspended") and (not center_if_needed) and (not one_row_mode):
            return

        sel = get_selected_team_code()
        if not sel or sel not in current_df.index:
            return

        try:
            i = int(list(current_df.index).index(sel))
        except Exception:
            return

        total_h = float(max(1, len(current_df.index) * cell_height))
        top_px = float(_top_px(data))
        bot_px = float(top_px + view_h)

        row_top = float(i * cell_height)
        row_bot = float(row_top + cell_height)

        if (row_top >= top_px) and (row_bot <= bot_px) and (not center_if_needed):
            return

        if one_row_mode:
            desired_top = row_top
        else:
            desired_top = row_top + (cell_height / 2.0) - (view_h / 2.0)

        desired_top = max(0.0, min(desired_top, total_h - view_h))
        desired_top = round(desired_top / float(cell_height)) * float(cell_height)
        desired_top = max(0.0, min(desired_top, total_h - view_h))

        _set_top_px(data, desired_top, total_h)
        _set_top_px(teams, desired_top, total_h)
        _set_top_px(bars, desired_top, total_h)

    def draw_bars():
        bars.delete("all")
        _bar_imgs_live.clear()

        total_h = len(current_df.index) * cell_height
        bars.configure(scrollregion=(0, 0, right_col_w["w"], total_h))

        if len(current_df.columns) == 0:
            return

        col_idx = max(0, min(selected_col_idx, len(current_df.columns) - 1))
        col = current_df.columns[col_idx]
        if show_percent:
            x_min = 0.0
            x_max = _current_ymax()
            if x_max <= x_min:
                x_max = x_min + 0.05
        else:
            col_vals = pd.to_numeric(current_df[col], errors="coerce").dropna()
            if col_vals.empty:
                x_min, x_max = 0.0, 1.0
            else:
                x_min = float(col_vals.min())
                x_max = float(col_vals.max())
                if x_max <= x_min:
                    x_max = x_min + 1.0

        pad_x = int(max(6, cell_width * 0.12))
        label_pad = int(max(8, cell_width * 0.18))

        w = max(1, int(bars.winfo_width() or right_col_w["w"]))
        usable_w = max(40, w - pad_x - label_pad)

        step = max(1e-9, choose_major_tick_step(x_max - x_min, usable_w))
        p = x_min
        while p <= x_max + 1e-9:
            x = pad_x + ((p - x_min) / max(1e-9, (x_max - x_min))) * usable_w
            bars.create_line(x, 0, x, total_h, fill=colors["bar_grid"])
            p += step

        # Goal-differential style tabs can cross zero; draw an explicit zero guide.
        if allow_negative_values and (x_min < 0.0 < x_max):
            x0 = pad_x + ((0.0 - x_min) / max(1e-9, (x_max - x_min))) * usable_w
            bars.create_line(x0, 0, x0, total_h, fill="#6a6a6a", width=2)
            bars.create_text(x0 + 4, 2, text="0", fill=colors["bar_text"], anchor="nw")

        sel = get_selected_team_code()

        for i, team in enumerate(current_df.index):
            y_top = i * cell_height
            y_bot = y_top + cell_height
            y_mid = (y_top + y_bot) / 2

            val = current_df.at[team, col]
            if pd.isna(val):
                continue
            try:
                valf = _safe_float(val)
            except Exception:
                continue

            bar_len = usable_w * ((valf - x_min) / max(1e-9, (x_max - x_min)))
            bar_len = max(0.0, min(usable_w, bar_len))

            x0 = pad_x
            x1 = pad_x + bar_len

            if bar_len > 0:
                y0 = y_top + 2
                y1p = y_bot - 2
                bar_h = int(max(1, y1p - y0))
                c0, c1 = _bar_gradient_colors(str(team))

                if PIL_OK:
                    img = _gradient_photo(int(round(bar_len)), bar_h, c0, c1, str(team))
                    if img is not None:
                        _bar_imgs_live.append(img)
                        bars.create_image(x0, y0, image=img, anchor="nw")
                    else:
                        _draw_gradient_fallback(bars, x0, y0, x1, y1p, c0, c1)
                else:
                    _draw_gradient_fallback(bars, x0, y0, x1, y1p, c0, c1)

            txt = _fmt_value(valf)
            tw = _measure_text_px(font, txt)

            is_dim = bool(sel and str(team).upper() != sel)
            outside_text = _blend(colors["bar_text"], colors["bar_bg"], 0.45) if is_dim else colors["bar_text"]

            inside_ok = bar_len >= (tw + 14)
            c0, c1 = _bar_gradient_colors(str(team))
            rep = _blend(c0, c1, 0.85)
            inside_color = "#111111" if _rel_luminance(rep) > 0.62 else "#f7f7f7"
            if is_dim:
                inside_color = _blend(inside_color, colors["bar_bg"], 0.35)

            if inside_ok:
                bars.create_text(x1 - 7, y_mid, text=txt, fill=inside_color, anchor="e")
            else:
                tx = min(w - label_pad, x1 + 6)
                bars.create_text(tx, y_mid, text=txt, fill=outside_text, anchor="w")

        try:
            bars.yview_moveto(data.yview()[0])
        except Exception:
            pass

    # ---------------- Stepper controls ----------------
    hold_job = None
    hold_delta = 0
    MAX_IDX = max(0, len(current_df.columns) - 1)

    SLIDER_BG = colors["graph_bg"]
    TROUGH = "#4a4a4a"
    BTN_BG = "#3a3a3a"
    BTN_FG = "#f0f0f0"
    BTN_HOVER = "#444444"

    _slider_state = {"drag": False, "hover": False, "thumb": (0, 0, 0, 0)}

    step_row.grid_columnconfigure(0, weight=0)
    step_row.grid_columnconfigure(1, weight=1)
    step_row.grid_columnconfigure(2, weight=0)

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
            pady=6,
            cursor="hand2",
        )
        lbl.bind("<Enter>", lambda _e: lbl.config(bg=BTN_HOVER))
        lbl.bind("<Leave>", lambda _e: lbl.config(bg=BTN_BG))
        return lbl

    prev_btn = _make_step_label(step_row, "◀")
    next_btn = _make_step_label(step_row, "▶")

    slider = tk.Canvas(
        step_row,
        height=int(max(28, cell_height * 1.2)),
        bg=SLIDER_BG,
        bd=0,
        highlightthickness=0,
    )

    prev_btn.grid(row=0, column=0, sticky="nsew", padx=0, pady=0)
    slider.grid(row=0, column=1, sticky="ew", padx=0, pady=0)
    next_btn.grid(row=0, column=2, sticky="nsew", padx=0, pady=0)

    def _slider_thumb_color() -> str:
        return _blend(BTN_BG, "#ffffff", 0.08) if (_slider_state["drag"] or _slider_state["hover"]) else BTN_BG

    def _draw_slider():
        slider.delete("all")
        w = max(1, int(slider.winfo_width() or 1))
        h = max(1, int(slider.winfo_height() or 1))

        pad = int(max(10, cell_width * 0.22))
        trough_h = int(max(8, cell_height * 0.35))
        thumb_w = int(max(26, cell_width * 0.55))
        thumb_h = int(max(20, cell_height * 0.90))

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
        pad = int(max(10, cell_width * 0.22))
        thumb_w = int(max(26, cell_width * 0.55))

        x0 = pad
        x1 = w - pad
        if MAX_IDX <= 0 or x1 <= x0:
            return 0

        usable = max(1, (x1 - x0 - thumb_w))
        rel = (x - x0 - thumb_w / 2) / usable
        idx = int(round(rel * MAX_IDX))
        return max(0, min(MAX_IDX, idx))

    # ---------------- Logos (right column) ----------------
    _logo_imgs_live: list[TkImg] = []

    def _values_on_selected_date() -> pd.Series:
        if len(current_df.columns) == 0:
            return pd.Series(dtype="float64")
        col = current_df.columns[max(0, min(selected_col_idx, len(current_df.columns) - 1))]
        return pd.to_numeric(current_df[col], errors="coerce")

    def _rank_codes(codes: list[str], s: pd.Series) -> list[str]:
        vals = []
        for c in codes:
            if c in s.index:
                v = s.loc[c]
                if not pd.isna(v):
                    vals.append((c, _safe_float(v)))
        vals.sort(key=lambda t: t[1], reverse=True)
        return [c for c, _ in vals]

    def _playoff_layout(s: pd.Series) -> dict[str, list[str]]:
        codes_present = [canon_team_code(x) for x in current_df.index]
        present_set = set(codes_present)

        div_top: dict[str, list[str]] = {}
        for div in ["Pacific", "Central", "Atlantic", "Metro"]:
            lst = [c for c in DIVS_MASTER[div] if c in present_set]
            ranked = _rank_codes(lst, s)
            div_top[div] = ranked[:3]

        def conf_pool(conf: str) -> list[str]:
            return [c for c in codes_present if TEAM_TO_CONF.get(c, "") == conf]

        west_taken = set(div_top["Pacific"] + div_top["Central"])
        east_taken = set(div_top["Atlantic"] + div_top["Metro"])

        west_rest = [c for c in conf_pool("West") if c not in west_taken]
        east_rest = [c for c in conf_pool("East") if c not in east_taken]

        west_ranked = _rank_codes(west_rest, s)
        east_ranked = _rank_codes(east_rest, s)

        return {
            "Pacific": div_top["Pacific"],
            "Central": div_top["Central"],
            "Atlantic": div_top["Atlantic"],
            "Metro": div_top["Metro"],
            "W_WC": west_ranked[:2],
            "E_WC": east_ranked[:2],
            "W_U": west_ranked[2:4],
            "E_U": east_ranked[2:4],
        }

    def _conf_top_n(s: pd.Series, n: int) -> tuple[list[str], list[str]]:
        codes_present = [canon_team_code(x) for x in current_df.index]
        west = [c for c in codes_present if TEAM_TO_CONF.get(c, "") == "West"]
        east = [c for c in codes_present if TEAM_TO_CONF.get(c, "") == "East"]
        return _rank_codes(west, s)[:n], _rank_codes(east, s)[:n]

    def _cup_two(s: pd.Series) -> list[str]:
        west, east = _conf_top_n(s, 1)
        picks = []
        if west:
            picks.append(west[0])
        if east:
            picks.append(east[0])
        picks.sort(key=lambda c: float(s.loc[c]) if c in s.index and not pd.isna(s.loc[c]) else -1.0, reverse=True)
        return picks[:2]

    def draw_logos():
        logos_canvas.delete("all")
        _logo_imgs_live.clear()

        w = max(1, int(logos_canvas.winfo_width() or right_col_w["w"]))
        h = max(1, int(logos_canvas.winfo_height() or 1))

        s = _values_on_selected_date()
        sel = get_selected_team_code()

        def logo_h_for_layout(rows: int, cols: int, codes_to_draw: list[str]) -> int:
            rows = max(1, int(rows))
            cols = max(1, int(cols))

            pad_y_local = int(max(8, cell_height * 0.25))
            avail_h = max(1, h - 2 * pad_y_local)
            slot_h = float(avail_h) / float(rows)

            h_by_slot = slot_h * 0.90

            pad_x_local = int(max(10, w * 0.06))
            avail_w = max(1, w - 2 * pad_x_local)
            col_w = float(avail_w) / float(cols)
            allowed_logo_w = col_w * 0.88

            h_by_width = h_by_slot
            for code in codes_to_draw:
                ar = logo_bank.aspect_ratio(code)
                if ar and ar > 0:
                    h_by_width = min(h_by_width, allowed_logo_w / ar)

            max_h = float(max(cell_height * 1.6, slot_h * 0.86))
            min_h = float(max(14, cell_height * 0.75))

            chosen = min(h_by_slot, h_by_width, max_h)
            return int(max(min_h, chosen))

        def draw_logo(code: str, x: float, y: float, logo_h: int):
            if not code:
                return
            is_dim = bool(sel and code.upper() != str(sel).upper())
            img = logo_bank.get(code, height=int(logo_h), dim=(PIL_OK and is_dim), dim_amt=0.60)
            if img is None:
                return
            _logo_imgs_live.append(img)
            logos_canvas.create_image(x, y, image=img, anchor="center")

            if (not PIL_OK) and is_dim:
                ww, hh = int(img.width()), int(img.height())
                x0, y0 = x - ww / 2, y - hh / 2
                x1, y1 = x + ww / 2, y + hh / 2
                logos_canvas.create_rectangle(x0, y0, x1, y1, fill=colors["graph_bg"], outline="", stipple="gray50")

        pad_x = int(max(10, w * 0.06))
        pad_y = int(max(8, cell_height * 0.25))

        if tab_key in {"points", "goal_differential"}:
            # Points tab intentionally has no bottom-right logo panel.
            return
        elif tab_key == "madeplayoffs":
            layout = _playoff_layout(s)
            rows, cols = 7, 4
            codes_to_draw = []
            for k in ["Pacific", "Central", "Atlantic", "Metro", "W_WC", "E_WC", "W_U", "E_U"]:
                codes_to_draw += [c for c in layout.get(k, []) if c]
            logo_h = logo_h_for_layout(rows, cols, codes_to_draw)

            col_w = (w - 2 * pad_x) / cols
            xs = [pad_x + (i + 0.5) * col_w for i in range(cols)]
            x_w_center = (xs[0] + xs[1]) / 2
            x_e_center = (xs[2] + xs[3]) / 2

            avail_h = max(1, h - 2 * pad_y)
            ys = [pad_y + (i + 0.5) * (avail_h / rows) for i in range(rows)]

            for r in range(3):
                draw_logo(layout["Pacific"][r] if r < len(layout["Pacific"]) else "", xs[0], ys[r], logo_h)
                draw_logo(layout["Central"][r] if r < len(layout["Central"]) else "", xs[1], ys[r], logo_h)
                draw_logo(layout["Atlantic"][r] if r < len(layout["Atlantic"]) else "", xs[2], ys[r], logo_h)
                draw_logo(layout["Metro"][r] if r < len(layout["Metro"]) else "", xs[3], ys[r], logo_h)

            ww = layout["W_WC"]; ew = layout["E_WC"]
            draw_logo(ww[0] if len(ww) > 0 else "", x_w_center, ys[3], logo_h)
            draw_logo(ew[0] if len(ew) > 0 else "", x_e_center, ys[3], logo_h)
            draw_logo(ww[1] if len(ww) > 1 else "", x_w_center, ys[4], logo_h)
            draw_logo(ew[1] if len(ew) > 1 else "", x_e_center, ys[4], logo_h)

            wu = layout["W_U"]; eu = layout["E_U"]
            draw_logo(wu[0] if len(wu) > 0 else "", x_w_center, ys[5], logo_h)
            draw_logo(eu[0] if len(eu) > 0 else "", x_e_center, ys[5], logo_h)
            draw_logo(wu[1] if len(wu) > 1 else "", x_w_center, ys[6], logo_h)
            draw_logo(eu[1] if len(eu) > 1 else "", x_e_center, ys[6], logo_h)

        elif tab_key == "round2":
            west, east = _conf_top_n(s, 6)
            rows, cols = 6, 2
            logo_h = logo_h_for_layout(rows, cols, [c for c in (west + east) if c])
            col_w = (w - 2 * pad_x) / cols
            xs = [pad_x + (i + 0.5) * col_w for i in range(cols)]
            avail_h = max(1, h - 2 * pad_y)
            ys = [pad_y + (i + 0.5) * (avail_h / rows) for i in range(rows)]
            for i in range(rows):
                draw_logo(west[i] if i < len(west) else "", xs[0], ys[i], logo_h)
                draw_logo(east[i] if i < len(east) else "", xs[1], ys[i], logo_h)

        elif tab_key == "round3":
            west, east = _conf_top_n(s, 4)
            rows, cols = 4, 2
            logo_h = logo_h_for_layout(rows, cols, [c for c in (west + east) if c])
            col_w = (w - 2 * pad_x) / cols
            xs = [pad_x + (i + 0.5) * col_w for i in range(cols)]
            avail_h = max(1, h - 2 * pad_y)
            ys = [pad_y + (i + 0.5) * (avail_h / rows) for i in range(rows)]
            for i in range(rows):
                draw_logo(west[i] if i < len(west) else "", xs[0], ys[i], logo_h)
                draw_logo(east[i] if i < len(east) else "", xs[1], ys[i], logo_h)

        elif tab_key == "round4":
            west, east = _conf_top_n(s, 2)
            rows, cols = 2, 2
            logo_h = logo_h_for_layout(rows, cols, [c for c in (west + east) if c])
            col_w = (w - 2 * pad_x) / cols
            xs = [pad_x + (i + 0.5) * col_w for i in range(cols)]
            avail_h = max(1, h - 2 * pad_y)
            ys = [pad_y + (i + 0.5) * (avail_h / rows) for i in range(rows)]
            for i in range(rows):
                draw_logo(west[i] if i < len(west) else "", xs[0], ys[i], logo_h)
                draw_logo(east[i] if i < len(east) else "", xs[1], ys[i], logo_h)

        else:  # woncup
            picks = _cup_two(s)
            rows = 2 if len(picks) >= 2 else 1
            cols = 1
            logo_h = logo_h_for_layout(max(2, rows), cols, [c for c in picks if c])
            x = w / 2
            avail_h = max(1, h - 2 * pad_y)
            ys = [pad_y + (i + 0.5) * (avail_h / max(2, rows)) for i in range(max(2, rows))]
            draw_logo(picks[0] if len(picks) > 0 else "", x, ys[0], logo_h)
            draw_logo(picks[1] if len(picks) > 1 else "", x, ys[1], logo_h)

    logos_canvas.bind("<Configure>", lambda _e: draw_logos(), add="+")

    # ---------------- Selecting date ----------------
    def set_selected(idx: int, *, ensure_visible: bool = True, force_redraw: bool = False):
        nonlocal selected_col_idx
        idx = max(0, min(int(idx), MAX_IDX))
        if idx == selected_col_idx and not force_redraw:
            return
        selected_col_idx = idx
        if not locked_default_order:
            _sort_by_selected_col()

        try:
            parent.update_idletasks()
        except Exception:
            pass

        if ensure_visible:
            _ensure_col_visible(selected_col_idx)

        draw_table()
        draw_graph()
        _update_bar_header()
        draw_bars()
        draw_logos()
        _draw_slider()

    def _step(delta: int):
        next_idx = max(0, min(selected_col_idx + delta, MAX_IDX))
        if next_idx == selected_col_idx:
            return
        set_selected(next_idx, ensure_visible=True)

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
        set_selected(_idx_from_x(e.x), ensure_visible=True)
        return "break"

    def _slider_drag(e):
        if not _slider_state["drag"]:
            return "break"
        set_selected(_idx_from_x(e.x), ensure_visible=True)
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

    # ---------------- Sorting ----------------
    def _sort_by_team() -> None:
        nonlocal current_df
        current_df = current_df.sort_index()

    def reset_sort():
        if not _apply_locked_default_order():
            _sort_by_selected_col()
        redraw_all()

    def on_header_click(event):
        nonlocal current_df
        x = header.canvasx(event.x)
        idx = int(x // cell_width)
        if 0 <= idx < len(current_df.columns):
            col = current_df.columns[idx]
            work = current_df.copy()
            work["__sort_val__"] = pd.to_numeric(work[col], errors="coerce")
            work["__sort_team__"] = [_team_sort_key_value(t) for t in work.index]
            work = work.sort_values(
                by=["__sort_val__", "__sort_team__"],
                ascending=[False, True],
                na_position="last",
                kind="mergesort",
            )
            current_df = work.drop(columns=["__sort_val__", "__sort_team__"])
            redraw_all()

    header.bind("<Button-1>", on_header_click)
    corner.bind("<Button-1>", lambda _e: (_sort_by_team(), redraw_all()))

    # ---------------- Wheel / drag scrolling ----------------
    def _mark_manual_scroll():
        _autofocus["suspended"] = True

    def _scroll_vertical(units: int):
        _mark_manual_scroll()
        teams.yview_scroll(units, "units")
        data.yview_scroll(units, "units")
        bars.yview_scroll(units, "units")

    def _scroll_horizontal(units: int):
        data.xview_scroll(units, "units")
        sync_x_from_data()
        draw_graph()

    def _on_mousewheel(event):
        if getattr(event, "delta", 0) == 0:
            return "break"
        _scroll_vertical(-1 if event.delta > 0 else 1)
        return "break"

    def _on_shift_mousewheel(event):
        if getattr(event, "delta", 0) == 0:
            return "break"
        _scroll_horizontal(-hscroll_units if event.delta > 0 else hscroll_units)
        return "break"

    def _on_linux_up(_event):
        _scroll_vertical(-1); return "break"

    def _on_linux_down(_event):
        _scroll_vertical(1); return "break"

    for w in (teams, data, header, corner, axis, graph, bars):
        w.bind("<MouseWheel>", _on_mousewheel)
        w.bind("<Button-4>", _on_linux_up)
        w.bind("<Button-5>", _on_linux_down)

    teams.bind("<Button-1>", _on_team_click, add="+")

    for w in (header, data, graph):
        w.bind("<Shift-MouseWheel>", _on_shift_mousewheel)

    def _scan_mark(canvas, event):
        _mark_manual_scroll()
        canvas.scan_mark(event.x, event.y)

    def _scan_drag(canvas, event):
        _mark_manual_scroll()
        canvas.scan_dragto(event.x, event.y, gain=1)

        if canvas is data:
            try:
                teams.yview_moveto(data.yview()[0])
                bars.yview_moveto(data.yview()[0])
            except Exception:
                pass

        if canvas is graph:
            left = _left_px(graph)
            _set_left_px(data, left, float(total_w))

        sync_x_from_data()
        draw_graph()

    data.bind("<ButtonPress-1>", lambda e: _scan_mark(data, e))
    data.bind("<B1-Motion>", lambda e: _scan_drag(data, e))
    graph.bind("<ButtonPress-1>", lambda e: _scan_mark(graph, e))
    graph.bind("<B1-Motion>", lambda e: _scan_drag(graph, e))

    # ---------------- Default sizing + clamp ----------------
    auto_layout = True
    dragging = False
    layout_job: str | None = None

    _drag_ctx = {"offset": 0, "bind_motion": None, "bind_release": None}

    def _min_top_px() -> int:
        return int(cell_height)

    def _min_bottom_structural(paned_h: int) -> int:
        right_col.update_idletasks()
        step_req = int(step_row.winfo_reqheight() or 0)
        title_req = int(title_lbl.winfo_reqheight() or 0)
        pad = int(max(6, cell_height * 0.20))
        structural = int(step_req + title_req + pad * 2)
        frac_floor = int(max(0, paned_h) * 0.16)
        return int(max(structural, frac_floor))

    def _default_top_px(paned_h: int) -> int:
        paned_h = int(max(0, paned_h))
        min_top = _min_top_px()
        min_bottom = _min_bottom_structural(paned_h)
        max_top_struct = max(min_top, paned_h - min_bottom)
        max_top_struct = min(max_top_struct, max(0, paned_h - 1))
        row_count = len(current_df.index)
        if isinstance(visible_row_count, int) and visible_row_count > 0:
            row_count = min(row_count, int(visible_row_count))
        table_need = int(row_count * cell_height)
        return int(max(min_top, min(table_need, max_top_struct)))

    def _bounds():
        paned_h = int(paned.winfo_height() or 0)
        if paned_h < 2:
            return (0, 0)
        min_top = _min_top_px()
        max_top = _default_top_px(paned_h)  # default == MAX TOP
        return (min_top, max_top)

    def _place_top_clamped(top: int) -> None:
        min_top, max_top = _bounds()
        if max_top <= 0:
            return
        top = int(max(min_top, min(max_top, top)))
        paned.sash_place(0, 0, top)

    def _apply_default_layout() -> None:
        paned_h = int(paned.winfo_height() or 0)
        if paned_h < 2:
            return
        _place_top_clamped(_default_top_px(paned_h))
        paned.update_idletasks()
        _autofocus["suspended"] = False
        _ensure_selected_team_visible(center_if_needed=True)

    def _clamp_sash():
        min_top, max_top = _bounds()
        if max_top <= 0:
            return
        try:
            _x, y = paned.sash_coord(0)
        except Exception:
            return
        _place_top_clamped(int(y))

    _clamp_job: dict[str, str | None] = {"id": None}

    def _run_clamp():
        _clamp_job["id"] = None
        _clamp_sash()
        _ensure_selected_team_visible(center_if_needed=True)

    def _clamp_sash_after_idle():
        if _clamp_job["id"] is not None:
            return
        _clamp_job["id"] = paned.after_idle(_run_clamp)

    def _queue_layout():
        nonlocal layout_job
        if layout_job is not None:
            return
        layout_job = paned.after_idle(_run_layout)

    def _run_layout():
        nonlocal layout_job
        layout_job = None
        _apply_default_layout()

    def _near_sash(event, tol: int = 10) -> bool:
        try:
            _, y = paned.sash_coord(0)
        except Exception:
            return False
        return abs(event.y - y) <= tol

    def _unbind_drag_hooks():
        top = paned.winfo_toplevel()
        if _drag_ctx.get("bind_motion"):
            try:
                top.unbind("<B1-Motion>", _drag_ctx["bind_motion"])
            except Exception:
                pass
        if _drag_ctx.get("bind_release"):
            try:
                top.unbind("<ButtonRelease-1>", _drag_ctx["bind_release"])
            except Exception:
                pass
        _drag_ctx["bind_motion"] = None
        _drag_ctx["bind_release"] = None

    def _on_motion_global(event):
        if not dragging:
            return
        # screen -> paned local
        y_local = int(event.y_root - paned.winfo_rooty())
        desired = int(y_local + _drag_ctx["offset"])
        _place_top_clamped(desired)
        _ensure_selected_team_visible(center_if_needed=True)
        return "break"

    def _on_release_global(_event=None):
        nonlocal dragging
        if not dragging:
            return
        dragging = False
        _autofocus["suspended"] = False
        _unbind_drag_hooks()
        _clamp_sash()
        _ensure_selected_team_visible(center_if_needed=True)
        return "break"

    def _on_press(event):
        nonlocal dragging, auto_layout
        if not _near_sash(event):
            return
        dragging = True
        auto_layout = False
        _autofocus["suspended"] = False

        try:
            _x, sash_y = paned.sash_coord(0)
            _drag_ctx["offset"] = int(sash_y - event.y)
        except Exception:
            _drag_ctx["offset"] = 0

        _unbind_drag_hooks()
        top = paned.winfo_toplevel()
        _drag_ctx["bind_motion"] = top.bind("<B1-Motion>", _on_motion_global, add="+")
        _drag_ctx["bind_release"] = top.bind("<ButtonRelease-1>", _on_release_global, add="+")
        return "break"

    def _on_double(_event=None):
        nonlocal auto_layout, dragging
        dragging = False
        _unbind_drag_hooks()
        auto_layout = True
        _autofocus["suspended"] = False
        _queue_layout()
        return "break"

    def _on_paned_configure(_event=None):
        if auto_layout:
            _queue_layout()
        else:
            _clamp_sash_after_idle()

    paned.bind("<ButtonPress-1>", _on_press)
    paned.bind("<Double-Button-1>", _on_double)
    paned.bind("<Configure>", _on_paned_configure)

    # ---------------- Redraw + Reset ----------------
    def redraw_all():
        nonlocal total_w, MAX_IDX
        total_w = len(current_df.columns) * cell_width

        header.configure(scrollregion=(0, 0, total_w, cell_height))
        data.configure(scrollregion=(0, 0, total_w, 1))

        MAX_IDX = max(0, len(current_df.columns) - 1)

        draw_header()
        draw_table()
        draw_graph()
        draw_bars()
        draw_logos()
        _draw_slider()
        _update_bar_header()
        _ensure_selected_team_visible(center_if_needed=False)

    def reset_tab():
        nonlocal current_df, selected_col_idx, auto_layout

        current_df = base_df.copy()
        if not _apply_locked_default_order():
            order = [t for t in original_order if t in current_df.index]
            if order:
                current_df = current_df.loc[order]

        auto_layout = True

        try:
            teams.yview_moveto(0.0)
            data.yview_moveto(0.0)
            bars.yview_moveto(0.0)
        except Exception:
            pass

        _set_left_px(data, _max_left_px(data, float(total_w)), float(total_w))
        sync_x_from_data()

        selected_col_idx = len(current_df.columns) - 1 if len(current_df.columns) else 0
        _autofocus["suspended"] = False

        redraw_all()
        _apply_default_layout()
        set_selected(selected_col_idx, ensure_visible=False, force_redraw=True)

    def _on_outer_configure(_e=None):
        _apply_right_col_width()
        _update_bar_header()
        draw_bars()
        draw_logos()
        _draw_slider()

    outer.bind("<Configure>", _on_outer_configure, add="+")

    redraw_all()

    def _init_layout(tries: int = 0):
        if int(paned.winfo_height() or 0) < 2 and tries < 25:
            parent.after(25, lambda: _init_layout(tries + 1))
            return
        _apply_default_layout()
        _set_left_px(data, _max_left_px(data, float(total_w)), float(total_w))
        sync_x_from_data()
        set_selected(len(current_df.columns) - 1, ensure_visible=False, force_redraw=True)

    parent.after(0, _init_layout)

    return {"redraw": redraw_all, "reset": reset_tab}

#endregion

#region App
