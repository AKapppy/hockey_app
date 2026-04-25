from __future__ import annotations

import datetime as dt
import math
import os
from pathlib import Path
import sys
import tkinter as tk
import tkinter.font as tkfont
from tkinter import messagebox, ttk
from typing import Any, Callable, cast

import pandas as pd

from hockey_app.ui.components.flat_button import FlatButton
from hockey_app.ui.components.layout_metrics import compute_cell_width, compute_team_col_width
from hockey_app.ui.components.logo_bank import LogoBank
from hockey_app.ui.notebook_scaffold import build_notebook_scaffold
from hockey_app.ui.predictions_mount import mount_predictions_tabs
from hockey_app.runtime.public_predictions import PUBLIC_MODEL_SIMS, build_public_probability_tables
from hockey_app.ui.models_mount import (
    mount_magic_tragic_tab,
    mount_playoff_picture_tab,
    mount_playoff_win_probabilities_tab,
    mount_point_probabilities_tab,
)
from hockey_app.ui.renderers.heatmap_graph import render_df_heatmap_with_graph
from hockey_app.ui.renderers.pie_chart import render_pie_chart_tab
from hockey_app.ui.stats_mount import (
    mount_game_stats_tab,
    mount_games_tab,
    mount_goal_differential_tab,
    mount_player_stats_tab,
    mount_points_tab,
    mount_team_stats_tab,
)
from hockey_app.runtime.prof import StartupProfiler

PWHL_TEAM_COLORS: dict[str, str] = {
    "BOS": "#0B7A75",
    "MIN": "#6A0DAD",
    "MTL": "#2B4A8B",
    "NY": "#2EC4B6",
    "OTT": "#D62828",
    "TOR": "#1D3557",
    "VAN": "#0077B6",
    "SEA": "#264653",
}
PWHL_TEAM_ORDER: list[str] = ["BOS", "MIN", "MTL", "NY", "OTT", "TOR", "VAN", "SEA"]
PWHL_TEAM_NAMES: dict[str, str] = {
    "BOS": "Boston Fleet",
    "MIN": "Minnesota Frost",
    "MTL": "Montreal Victoire",
    "NY": "New York Sirens",
    "OTT": "Ottawa Charge",
    "TOR": "Toronto Sceptres",
    "VAN": "Vancouver",
    "SEA": "Seattle",
}


def launch_predictions_ui_window(
    tables: dict[str, pd.DataFrame],
    *,
    season: str,
    start_date: dt.date,
    images_dir: Path,
    tab_order: list[str],
    tab_labels: dict[str, str],
    tab_titles: dict[str, str],
    team_names: dict[str, str],
    dark_window_bg: str,
    dark_canvas_bg: str,
    dark_hilite: str,
    canon_team_code: Callable[[str], str],
    division_columns_for_codes: Callable[[set[str]], dict[str, list[str]]],
    build_team_color_map: Callable[[set[str] | None], dict[str, str]],
    ensure_logo_cached: Callable[[str], None],
    logo_path: Callable[[str], Path],
) -> None:
    prof = StartupProfiler()
    scaffold = build_notebook_scaffold(season=season, dark_window_bg=dark_window_bg)
    prof.mark("build_notebook_scaffold")
    root = scaffold.root
    content = scaffold.content
    public_predictions_page = ttk.Frame(scaffold.main_notebook, padding=0)
    public_predictions_page.grid_rowconfigure(0, weight=1)
    public_predictions_page.grid_columnconfigure(0, weight=1)
    public_predictions_page.grid_rowconfigure(1, weight=0)
    inserted_public_predictions = False
    try:
        scaffold.main_notebook.insert(scaffold.models_page, public_predictions_page, text="Predictions 2")
        inserted_public_predictions = True
    except Exception:
        scaffold.add_gap_tab(scaffold.main_notebook)
        scaffold.main_notebook.add(public_predictions_page, text="Predictions 2")
    if inserted_public_predictions:
        try:
            models_gap = ttk.Frame(scaffold.main_notebook, padding=0)
            scaffold.main_notebook.insert(scaffold.models_page, models_gap, text=" ")
            scaffold.main_notebook.tab(models_gap, state="disabled", padding=(2, 3))
        except Exception:
            pass

    public_pred_notebook = ttk.Notebook(public_predictions_page, style="NB.TNotebook")
    public_pred_notebook.grid(row=0, column=0, sticky="nsew", pady=(0, 0))
    tk.Label(
        public_predictions_page,
        text=f"Public NHL API model (non-MoneyPuck) | {int(PUBLIC_MODEL_SIMS)} sims/team",
        bg=dark_window_bg,
        fg="#9a9a9a",
        font=("TkDefaultFont", 9),
        anchor="e",
        padx=8,
        pady=2,
    ).grid(row=1, column=0, sticky="se")

    app_state: dict[str, Any] = {
        "selected_team_code": None,
        "team_menu": None,
        "season_menu": None,
        "stats_league": "NHL",
    }
    controllers: dict[str, dict[str, Callable[[], None]]] = {}

    all_codes: list[str] = sorted({canon_team_code(str(c)) for dfi in tables.values() for c in dfi.index})
    all_codes_set = set(all_codes)
    team_colors = build_team_color_map(all_codes_set)
    public_start_date = start_date
    public_tables = build_public_probability_tables(
        season,
        today=dt.date.today(),
        start_date=public_start_date,
    )
    if not public_tables:
        col = f"{public_start_date.month}/{public_start_date.day}"
        base_codes = sorted(all_codes_set or set(team_names.keys()))
        for metric_key in ("madeplayoffs", "round2", "round3", "round4", "woncup"):
            public_tables[metric_key] = pd.DataFrame(
                {col: [0.0 for _ in base_codes]},
                index=base_codes,
                dtype="float64",
            )

    logo_bank = LogoBank(
        root,
        bg_hex=dark_canvas_bg,
        canon_team_code=canon_team_code,
        ensure_logo_cached=ensure_logo_cached,
        logo_path=logo_path,
    )
    # Keep startup fast: avoid eager logo download/load and width scans.
    logo_max_w = 40

    font = tkfont.nametofont("TkDefaultFont")
    team_col_width = compute_team_col_width(all_codes, font, logo_max_w)
    cell_width = compute_cell_width(font)
    prof.mark("compute_layout_metrics")

    colors = {"btn_bg": "#3a3a3a", "btn_fg": "#f0f0f0", "btn_hover": "#444444"}

    def _season_start_year(value: str) -> int | None:
        parts = [p for p in str(value).split("-") if p.strip()]
        if len(parts) != 2 or not parts[0].isdigit():
            return None
        return int(parts[0])

    def _season_display(value: str) -> str:
        start = _season_start_year(value)
        if start is None:
            return str(value)
        return f"{start}-{(start + 1) % 100:02d}"

    def _default_current_season_start() -> int:
        d = dt.date.today()
        return d.year if d.month >= 10 else d.year - 1

    def _season_choices(min_start: int = 2023) -> list[str]:
        current_start = _season_start_year(season)
        if current_start is None:
            current_start = _default_current_season_start()
        top_start = max(current_start, _default_current_season_start())
        return [f"{y}-{y + 1}" for y in range(top_start, min_start - 1, -1)]

    pwhl_codes = set(PWHL_TEAM_ORDER)

    def _team_display(code: str) -> str:
        c = str(code).upper()
        league_u = str(app_state.get("stats_league", "NHL")).upper()
        if league_u == "PWHL":
            return PWHL_TEAM_NAMES.get(c, team_names.get(c, c))
        return team_names.get(c, c)

    team_btn = FlatButton(
        content,
        text="Choose team",
        bg=colors["btn_bg"],
        fg=colors["btn_fg"],
        hover_bg=colors["btn_hover"],
        padx=14,
        pady=8,
        anchor="w",
    )
    reset_btn = FlatButton(
        content,
        text="Reset",
        bg=colors["btn_bg"],
        fg=colors["btn_fg"],
        hover_bg=colors["btn_hover"],
        padx=14,
        pady=8,
        anchor="w",
    )
    league_btn = FlatButton(
        content,
        text="League: NHL",
        bg=colors["btn_bg"],
        fg=colors["btn_fg"],
        hover_bg=colors["btn_hover"],
        padx=14,
        pady=8,
        anchor="w",
    )
    season_btn = FlatButton(
        content,
        text=f"Season: {_season_display(season)}",
        bg=colors["btn_bg"],
        fg=colors["btn_fg"],
        hover_bg=colors["btn_hover"],
        padx=14,
        pady=8,
        anchor="w",
    )

    top_x, top_y, btn_gap = 6, 4, 10

    def _position_global_buttons(_e=None):
        content.update_idletasks()
        team_btn.place(x=top_x, y=top_y, anchor="nw")
        reset_btn.place(x=top_x + team_btn.winfo_width() + btn_gap, y=top_y, anchor="nw")
        league_btn.place(x=top_x + team_btn.winfo_width() + reset_btn.winfo_width() + btn_gap * 2, y=top_y, anchor="nw")
        season_btn.place(x=max(10, content.winfo_width() - top_x), y=top_y, anchor="ne")
        team_btn.lift()
        reset_btn.lift()
        league_btn.lift()
        season_btn.lift()

    content.bind("<Configure>", _position_global_buttons, add="+")
    _position_global_buttons()

    def _notify_all_tabs_redraw():
        for ctrl in controllers.values():
            try:
                ctrl["redraw"]()
            except Exception:
                pass

    def _team_button_img(code: str):
        c = str(code).upper()
        league_u = str(app_state.get("stats_league", "NHL")).upper()
        # Prefer PWHL branding only while the PWHL league is active.
        if league_u == "PWHL" and c in pwhl_codes:
            pimg = _pwhl_logo(c, height=28)
            if pimg is not None:
                return pimg
        return logo_bank.get(c, height=28, dim=False)

    def _update_team_button():
        sel = app_state["selected_team_code"]
        if sel:
            img = _team_button_img(sel)
            if img:
                team_btn.set(image=img, text=f"  {_team_display(sel)}", compound="left")
            else:
                team_btn.set(image=None, text=_team_display(sel), compound="none")
        else:
            team_btn.set(image=None, text="Choose team", compound="none")
        _position_global_buttons()

    def _update_league_button():
        league_btn.set(text=f"League: {app_state.get('stats_league', 'NHL')}")
        _position_global_buttons()

    def _close_team_menu():
        tm = app_state.get("team_menu")
        exists = False
        try:
            exists = tm is not None and bool(tm.winfo_exists())
        except Exception:
            exists = False
        if exists:
            try:
                tm.destroy()
            except Exception:
                pass
        app_state["team_menu"] = None

    def _close_season_menu():
        sm = app_state.get("season_menu")
        exists = False
        try:
            exists = sm is not None and bool(sm.winfo_exists())
        except Exception:
            exists = False
        if exists:
            try:
                sm.destroy()
            except Exception:
                pass
        app_state["season_menu"] = None

    season_switch_state: dict[str, Any] = {
        "busy": False,
        "overlay": None,
        "bar": None,
        "status": None,
        "style_ready": False,
        "watchdog_after": None,
    }

    def _show_season_switch_overlay(new_season: str) -> None:
        cur_overlay = season_switch_state.get("overlay")
        try:
            if cur_overlay is not None and bool(cur_overlay.winfo_exists()):
                cur_overlay.destroy()
        except Exception:
            pass

        overlay = tk.Toplevel(root)
        overlay.title("Switching Season")
        overlay.configure(bg=dark_window_bg)
        overlay.transient(root)
        overlay.resizable(False, False)
        overlay.protocol("WM_DELETE_WINDOW", lambda: None)

        root.update_idletasks()
        win_w, win_h = 420, 170
        try:
            x = int(root.winfo_rootx() + max(0, (root.winfo_width() - win_w) / 2))
            y = int(root.winfo_rooty() + max(0, (root.winfo_height() - win_h) / 2))
            overlay.geometry(f"{win_w}x{win_h}+{x}+{y}")
        except Exception:
            overlay.geometry(f"{win_w}x{win_h}")

        panel = tk.Frame(overlay, bg="#242424", bd=1, highlightthickness=1, highlightbackground="#3a3a3a")
        panel.pack(fill="both", expand=True, padx=12, pady=12)

        if not bool(season_switch_state.get("style_ready")):
            try:
                style = ttk.Style(root)
                style.configure(
                    "SeasonSwitch.Horizontal.TProgressbar",
                    troughcolor="#1b1b1b",
                    background="#4ea1ff",
                    bordercolor="#1b1b1b",
                    lightcolor="#4ea1ff",
                    darkcolor="#4ea1ff",
                )
                season_switch_state["style_ready"] = True
            except Exception:
                season_switch_state["style_ready"] = False

        status_lbl = None
        bar = None
        try:
            tk.Label(
                panel,
                text=f"Switching to {str(_season_display(new_season))}",
                bg="#242424",
                fg="#f0f0f0",
                font=("TkDefaultFont", 16, "bold"),
                padx=20,
                pady=(16, 8),
            ).pack()
            status_lbl = tk.Label(
                panel,
                text="Loading season data...",
                bg="#242424",
                fg="#c7c7c7",
                font=("TkDefaultFont", 11),
                padx=20,
                pady=(0, 8),
            )
            status_lbl.pack()
            bar_style = "SeasonSwitch.Horizontal.TProgressbar" if bool(season_switch_state.get("style_ready")) else "Horizontal.TProgressbar"
            bar = ttk.Progressbar(panel, mode="determinate", maximum=100.0, length=300, style=bar_style)
            bar.pack(padx=20, pady=(0, 16))
        except Exception:
            for child in panel.winfo_children():
                try:
                    child.destroy()
                except Exception:
                    pass
            tk.Label(
                panel,
                text=f"Switching season to {str(_season_display(new_season))}",
                bg="#242424",
                fg="#f0f0f0",
                padx=16,
                pady=(16, 8),
            ).pack()
            status_lbl = tk.Label(
                panel,
                text="Loading season data...",
                bg="#242424",
                fg="#f0f0f0",
                padx=16,
                pady=(0, 8),
            )
            status_lbl.pack()
            bar = ttk.Progressbar(panel, mode="determinate", maximum=100.0, length=300)
            bar.pack(padx=16, pady=(0, 16))
        try:
            bar.configure(value=8.0)
        except Exception:
            pass

        try:
            overlay.lift()
            overlay.focus_force()
            overlay.update_idletasks()
        except Exception:
            pass

        season_switch_state["overlay"] = overlay
        season_switch_state["bar"] = bar
        season_switch_state["status"] = status_lbl

    def _clear_switch_watchdog() -> None:
        after_id = season_switch_state.get("watchdog_after")
        if after_id is not None:
            try:
                root.after_cancel(after_id)
            except Exception:
                pass
        season_switch_state["watchdog_after"] = None

    def _hide_season_switch_overlay() -> None:
        _clear_switch_watchdog()
        overlay = season_switch_state.get("overlay")
        try:
            if overlay is not None and bool(overlay.winfo_exists()):
                try:
                    if overlay.grab_current() == overlay:
                        overlay.grab_release()
                except Exception:
                    pass
                overlay.destroy()
        except Exception:
            pass
        season_switch_state["overlay"] = None
        season_switch_state["bar"] = None
        season_switch_state["status"] = None

    def _set_switch_status(text: str) -> None:
        lbl = season_switch_state.get("status")
        try:
            if lbl is not None and bool(lbl.winfo_exists()):
                lbl.configure(text=text)
        except Exception:
            pass

    def _set_switch_progress(value: float) -> None:
        bar = season_switch_state.get("bar")
        try:
            if bar is not None and bool(bar.winfo_exists()):
                bar.configure(value=max(0.0, min(100.0, float(value))))
                bar.update_idletasks()
        except Exception:
            pass

    def _start_switch_watchdog() -> None:
        _clear_switch_watchdog()

        def _tick() -> None:
            if not bool(season_switch_state.get("busy")):
                season_switch_state["watchdog_after"] = None
                return
            bar = season_switch_state.get("bar")
            try:
                if bar is not None and bool(bar.winfo_exists()):
                    cur = float(bar.cget("value") or 0.0)
                    bar.configure(value=min(94.0, cur + 2.0))
            except Exception:
                pass
            try:
                season_switch_state["watchdog_after"] = root.after(140, _tick)
            except Exception:
                season_switch_state["watchdog_after"] = None

        try:
            season_switch_state["watchdog_after"] = root.after(140, _tick)
        except Exception:
            season_switch_state["watchdog_after"] = None

    def _exec_into_season(new_season: str) -> None:
        env = dict(os.environ)
        env["HOCKEY_SEASON"] = str(new_season).strip()
        cwd = Path(__file__).resolve().parents[2]
        try:
            os.chdir(str(cwd))
        except Exception:
            pass
        os.execvpe(sys.executable, [sys.executable, "-m", "hockey_app"], env)

    def _restart_with_season(new_season: str) -> None:
        new_season = str(new_season).strip()
        if not new_season:
            return
        if new_season == season:
            _close_season_menu()
            return
        if bool(season_switch_state.get("busy")):
            return
        _close_season_menu()
        _close_team_menu()
        season_switch_state["busy"] = True
        _show_season_switch_overlay(new_season)
        _clear_switch_watchdog()
        _set_switch_status("Preparing season...")
        _set_switch_progress(16.0)
        _start_switch_watchdog()

        def _launch() -> None:
            try:
                _set_switch_status("Launching season...")
                _set_switch_progress(92.0)
                _exec_into_season(new_season)
            except Exception as e:
                season_switch_state["busy"] = False
                _hide_season_switch_overlay()
                messagebox.showerror("Season Switch Error", f"Failed to relaunch app:\n{e}")

        try:
            # Let Tk paint the overlay before process replacement.
            root.after(180, _launch)
        except Exception:
            _launch()

    menu_bg = "#222222"
    menu_border = "#404040"
    menu_text = "#f0f0f0"
    menu_hover = "#2f2f2f"
    pwhl_logo_dir = Path(__file__).resolve().parents[1] / "assets" / "pwhl_logos"
    pwhl_logo_cache: dict[tuple[str, int], Any] = {}

    divs = division_columns_for_codes(all_codes_set)

    def _open_season_menu():
        has_season_menu = False
        try:
            has_season_menu = app_state["season_menu"] is not None and bool(app_state["season_menu"].winfo_exists())
        except Exception:
            has_season_menu = False
        if has_season_menu:
            _close_season_menu()
            return

        sm = tk.Toplevel(root)
        app_state["season_menu"] = sm

        sm.overrideredirect(True)
        sm.configure(bg=menu_bg)
        sm.transient(root)

        x = season_btn.winfo_rootx()
        y = season_btn.winfo_rooty() + season_btn.winfo_height()
        sm.geometry(f"+{x}+{y}")

        sm.bind("<FocusOut>", lambda _e: _close_season_menu(), add="+")
        sm.bind("<Escape>", lambda _e: _close_season_menu(), add="+")
        sm.focus_force()

        body = tk.Frame(sm, bg=menu_bg, bd=0, highlightthickness=1, highlightbackground=menu_border)
        body.pack(fill="both", expand=True)

        season_col = tk.Frame(body, bg=menu_bg)
        season_col.pack(padx=10, pady=10)

        for season_opt in _season_choices():
            item = tk.Frame(season_col, bg=menu_bg, bd=0, highlightthickness=0)
            item.pack(fill="x", anchor="w", pady=2)

            text = _season_display(season_opt)
            if season_opt == season:
                text = f"{text}  (current)"
            lbl = tk.Label(
                item,
                text=text,
                fg=menu_text,
                bg=menu_bg,
                bd=0,
                highlightthickness=0,
                anchor="w",
                justify="left",
                padx=4,
                pady=2,
                font=("TkDefaultFont", 11),
            )
            lbl.pack(fill="x", anchor="w")

            def _pick(_e=None, s=season_opt):
                _restart_with_season(s)

            def _enter(_e=None):
                item.configure(bg=menu_hover)
                lbl.configure(bg=menu_hover)

            def _leave(_e=None):
                item.configure(bg=menu_bg)
                lbl.configure(bg=menu_bg)

            for w in (item, lbl):
                w.bind("<Button-1>", _pick)
                w.bind("<Enter>", _enter)
                w.bind("<Leave>", _leave)

    def _pwhl_logo(code: str, *, height: int = 28):
        c = str(code).upper()
        key = (c, int(max(1, height)))
        if key in pwhl_logo_cache:
            return pwhl_logo_cache[key]

        candidates = [c]
        if c == "MTL":
            candidates.append("MON")
        for stem in candidates:
            p = pwhl_logo_dir / f"{stem}.png"
            if not p.exists():
                continue
            try:
                img = tk.PhotoImage(master=root, file=str(p))
                h0 = int(img.height() or 0)
                if h0 > key[1]:
                    factor = max(1, int(math.ceil(h0 / key[1])))
                    img = img.subsample(factor)
                pwhl_logo_cache[key] = img
                return img
            except Exception:
                continue
        return None

    def _open_team_menu():
        _close_season_menu()
        has_team_menu = False
        try:
            has_team_menu = app_state["team_menu"] is not None and bool(app_state["team_menu"].winfo_exists())
        except Exception:
            has_team_menu = False
        if has_team_menu:
            _close_team_menu()
            return

        tm = tk.Toplevel(root)
        app_state["team_menu"] = tm

        tm.overrideredirect(True)
        tm.configure(bg=menu_bg)
        tm.transient(root)

        x = team_btn.winfo_rootx()
        y = team_btn.winfo_rooty() + team_btn.winfo_height()
        tm.geometry(f"+{x}+{y}")

        tm.bind("<FocusOut>", lambda _e: _close_team_menu(), add="+")
        tm.bind("<Escape>", lambda _e: _close_team_menu(), add="+")
        tm.focus_force()

        body = tk.Frame(tm, bg=menu_bg, bd=0, highlightthickness=1, highlightbackground=menu_border)
        body.pack(fill="both", expand=True)

        grid = tk.Frame(body, bg=menu_bg)
        grid.pack(padx=10, pady=10)

        def _make_logo_item(parent_col: tk.Frame, code: str):
            league_u = str(app_state.get("stats_league", "NHL")).upper()
            img = _pwhl_logo(code, height=28) if league_u == "PWHL" else logo_bank.get(code, height=28, dim=False)

            item = tk.Frame(parent_col, bg=menu_bg, bd=0, highlightthickness=0)
            item.pack(anchor="w", pady=2)

            lbl = tk.Label(
                item,
                image=img if img else "",
                text="" if img else code,
                fg=menu_text,
                bg=menu_bg,
                bd=0,
                highlightthickness=0,
            )
            lbl.pack(anchor="w", padx=2, pady=2)
            if img:
                cast(Any, lbl).image = img

            def _pick(_e=None, c=code):
                app_state["selected_team_code"] = c
                _update_team_button()
                _close_team_menu()
                _notify_all_tabs_redraw()

            def _enter(_e=None):
                item.configure(bg=menu_hover)
                lbl.configure(bg=menu_hover)

            def _leave(_e=None):
                item.configure(bg=menu_bg)
                lbl.configure(bg=menu_bg)

            for w in (item, lbl):
                w.bind("<Button-1>", _pick)
                w.bind("<Enter>", _enter)
                w.bind("<Leave>", _leave)

        if str(app_state.get("stats_league", "NHL")).upper() == "PWHL":
            cols = [tk.Frame(grid, bg=menu_bg), tk.Frame(grid, bg=menu_bg)]
            cols[0].grid(row=0, column=0, sticky="n", padx=(0, 16))
            cols[1].grid(row=0, column=1, sticky="n", padx=(0, 0))
            for i, code in enumerate(PWHL_TEAM_ORDER):
                _make_logo_item(cols[i % 2], code)
        else:
            for col_i, div_name in enumerate(["Pacific", "Central", "Atlantic", "Metro"]):
                col = tk.Frame(grid, bg=menu_bg)
                col.grid(row=0, column=col_i, sticky="n", padx=(0 if col_i == 0 else 14, 0))

                hdr = tk.Label(
                    col,
                    text=div_name,
                    bg=menu_bg,
                    fg=menu_text,
                    font=("TkDefaultFont", 11, "bold"),
                    anchor="w",
                )
                hdr.pack(fill="x", pady=(0, 8))

                for code in divs.get(div_name, []):
                    _make_logo_item(col, code)

    team_btn.set_command(_open_team_menu)
    season_btn.set_command(_open_season_menu)

    def get_selected_team_code():
        return app_state["selected_team_code"]

    def set_selected_team_code(code: str | None):
        if code is None:
            app_state["selected_team_code"] = None
        else:
            app_state["selected_team_code"] = canon_team_code(str(code))
        _update_team_button()
        _notify_all_tabs_redraw()

    def _active_sub_notebook() -> ttk.Notebook:
        sel = scaffold.main_notebook.select()
        if sel == str(scaffold.predictions_page):
            return scaffold.pred_notebook
        if sel == str(public_predictions_page):
            return public_pred_notebook
        if sel == str(scaffold.stats_page):
            return scaffold.stats_notebook
        return scaffold.models_notebook

    def _active_tab_id() -> str | None:
        try:
            sel = scaffold.main_notebook.select()
            if sel == str(scaffold.scoreboard_page):
                return "scoreboard"
            nb = _active_sub_notebook()
            return nb.select()
        except Exception:
            return None

    def _global_reset():
        _close_team_menu()
        _close_season_menu()
        app_state["selected_team_code"] = None
        _update_team_button()

        tid = _active_tab_id()
        if tid and tid in controllers:
            try:
                controllers[tid]["reset"]()
            except Exception:
                pass

        _notify_all_tabs_redraw()

    reset_btn.set_command(_global_reset)
    _update_team_button()
    _update_league_button()
    prof.mark("build_global_controls")

    stats_loaded = {
        "scoreboard": False,
        "team_stats": False,
        "game_stats": False,
        "player_stats": False,
        "goal_diff": False,
        "points": False,
        "playoff_picture": False,
        "magic_tragic": False,
        "point_probabilities": False,
        "playoff_win_probabilities": False,
    }
    pred_tabs_ctrl: dict[str, Callable[[], None]] = {}
    public_pred_tabs_ctrl: dict[str, Callable[[], None]] = {}

    def _active_stats_colors() -> dict[str, str]:
        if str(app_state.get("stats_league", "NHL")).upper() == "PWHL":
            merged = dict(team_colors)
            merged.update(PWHL_TEAM_COLORS)
            return merged
        return team_colors

    def _load_scoreboard_if_needed() -> None:
        if stats_loaded["scoreboard"] or scaffold.scoreboard_holder is None:
            return
        mount_games_tab(
            scaffold.scoreboard_holder,
            logo_bank,
            team_names=team_names,
            dark_window_bg=dark_window_bg,
            dark_canvas_bg=dark_canvas_bg,
            dark_hilite=dark_hilite,
        )
        stats_loaded["scoreboard"] = True

    def _load_points_if_needed() -> None:
        if stats_loaded["points"] or scaffold.points_holder is None or scaffold.points_tab is None:
            return
        mount_points_tab(
            scaffold.points_holder,
            scaffold.points_tab,
            logo_bank=logo_bank,
            team_colors=_active_stats_colors(),
            team_col_width=team_col_width,
            cell_width=cell_width,
            league=str(app_state.get("stats_league", "NHL")),
            get_selected_team_code=get_selected_team_code,
            set_selected_team_code=set_selected_team_code,
            render_heatmap_with_graph=render_df_heatmap_with_graph,
            controllers=controllers,
        )
        stats_loaded["points"] = True

    def _load_team_stats_if_needed() -> None:
        if (
            stats_loaded["team_stats"]
            or scaffold.team_stats_holder is None
            or scaffold.team_stats_tab is None
        ):
            return
        mount_team_stats_tab(
            scaffold.team_stats_holder,
            scaffold.team_stats_tab,
            logo_bank=logo_bank,
            team_colors=_active_stats_colors(),
            team_col_width=team_col_width,
            cell_width=cell_width,
            league=str(app_state.get("stats_league", "NHL")),
            get_selected_team_code=get_selected_team_code,
            set_selected_team_code=set_selected_team_code,
            render_heatmap_with_graph=render_df_heatmap_with_graph,
            controllers=controllers,
        )
        stats_loaded["team_stats"] = True

    def _load_game_stats_if_needed() -> None:
        if (
            stats_loaded["game_stats"]
            or scaffold.game_stats_holder is None
            or scaffold.game_stats_tab is None
        ):
            return
        mount_game_stats_tab(
            scaffold.game_stats_holder,
            scaffold.game_stats_tab,
            logo_bank=logo_bank,
            team_colors=_active_stats_colors(),
            team_col_width=team_col_width,
            cell_width=cell_width,
            league=str(app_state.get("stats_league", "NHL")),
            get_selected_team_code=get_selected_team_code,
            set_selected_team_code=set_selected_team_code,
            render_heatmap_with_graph=render_df_heatmap_with_graph,
            controllers=controllers,
        )
        stats_loaded["game_stats"] = True

    def _load_goal_diff_if_needed() -> None:
        if (
            stats_loaded["goal_diff"]
            or scaffold.goal_diff_holder is None
            or scaffold.goal_diff_tab is None
        ):
            return
        mount_goal_differential_tab(
            scaffold.goal_diff_holder,
            scaffold.goal_diff_tab,
            logo_bank=logo_bank,
            team_colors=_active_stats_colors(),
            team_col_width=team_col_width,
            cell_width=cell_width,
            league=str(app_state.get("stats_league", "NHL")),
            get_selected_team_code=get_selected_team_code,
            set_selected_team_code=set_selected_team_code,
            render_heatmap_with_graph=render_df_heatmap_with_graph,
            controllers=controllers,
        )
        stats_loaded["goal_diff"] = True

    def _load_player_stats_if_needed() -> None:
        if (
            stats_loaded["player_stats"]
            or scaffold.player_stats_holder is None
            or scaffold.player_stats_tab is None
        ):
            return
        mount_player_stats_tab(
            scaffold.player_stats_holder,
            scaffold.player_stats_tab,
            logo_bank=logo_bank,
            league=str(app_state.get("stats_league", "NHL")),
            get_selected_team_code=get_selected_team_code,
            set_selected_team_code=set_selected_team_code,
            controllers=controllers,
        )
        stats_loaded["player_stats"] = True

    def _ensure_stats_tab_loaded(_event=None) -> None:
        try:
            selected = scaffold.stats_notebook.select()
            label = str(scaffold.stats_notebook.tab(selected, "text"))
        except Exception:
            return
        if label == "Team Stats":
            _load_team_stats_if_needed()
        elif label == "Game Stats":
            _load_game_stats_if_needed()
        elif label == "Player Stats":
            _load_player_stats_if_needed()
        elif label == "Goal Differential":
            _load_goal_diff_if_needed()
        elif label == "Points":
            _load_points_if_needed()

    scaffold.stats_notebook.bind("<<NotebookTabChanged>>", _ensure_stats_tab_loaded, add="+")

    def _load_playoff_picture_if_needed() -> None:
        if (
            stats_loaded["playoff_picture"]
            or scaffold.playoff_picture_holder is None
            or scaffold.playoff_picture_tab is None
        ):
            return
        mount_playoff_picture_tab(
            scaffold.playoff_picture_holder,
            scaffold.playoff_picture_tab,
            logo_bank=logo_bank,
            league=str(app_state.get("stats_league", "NHL")),
            get_selected_team_code=get_selected_team_code,
            set_selected_team_code=set_selected_team_code,
            controllers=controllers,
        )
        stats_loaded["playoff_picture"] = True

    def _load_magic_tragic_if_needed() -> None:
        if (
            stats_loaded["magic_tragic"]
            or scaffold.magic_tragic_holder is None
            or scaffold.magic_tragic_tab is None
        ):
            return
        mount_magic_tragic_tab(
            scaffold.magic_tragic_holder,
            scaffold.magic_tragic_tab,
            logo_bank=logo_bank,
            league=str(app_state.get("stats_league", "NHL")),
            controllers=controllers,
        )
        stats_loaded["magic_tragic"] = True

    def _load_point_probabilities_if_needed() -> None:
        if (
            stats_loaded["point_probabilities"]
            or scaffold.point_probabilities_holder is None
            or scaffold.point_probabilities_tab is None
        ):
            return
        mount_point_probabilities_tab(
            scaffold.point_probabilities_holder,
            scaffold.point_probabilities_tab,
            logo_bank=logo_bank,
            league=str(app_state.get("stats_league", "NHL")),
            controllers=controllers,
        )
        stats_loaded["point_probabilities"] = True

    def _load_playoff_win_probabilities_if_needed() -> None:
        if (
            stats_loaded["playoff_win_probabilities"]
            or scaffold.playoff_win_probabilities_holder is None
            or scaffold.playoff_win_probabilities_tab is None
        ):
            return
        mount_playoff_win_probabilities_tab(
            scaffold.playoff_win_probabilities_holder,
            scaffold.playoff_win_probabilities_tab,
            logo_bank=logo_bank,
            league=str(app_state.get("stats_league", "NHL")),
            controllers=controllers,
        )
        stats_loaded["playoff_win_probabilities"] = True

    def _ensure_models_tab_loaded(_event=None) -> None:
        try:
            selected = scaffold.models_notebook.select()
            label = str(scaffold.models_notebook.tab(selected, "text"))
        except Exception:
            return
        if label == "Playoff Picture":
            _load_playoff_picture_if_needed()
        elif label == "Magic/Tragic":
            _load_magic_tragic_if_needed()
        elif label == "Point Probabilities":
            _load_point_probabilities_if_needed()
        elif label == "Playoff Win Probabilities":
            _load_playoff_win_probabilities_if_needed()

    scaffold.models_notebook.bind("<<NotebookTabChanged>>", _ensure_models_tab_loaded, add="+")
    # Preload the first Models tab once to avoid any lazy-load race where the holder renders blank.
    _load_playoff_picture_if_needed()

    def _invalidate_stats_numeric_tabs() -> None:
        stats_loaded["team_stats"] = False
        stats_loaded["game_stats"] = False
        stats_loaded["player_stats"] = False
        stats_loaded["points"] = False
        stats_loaded["goal_diff"] = False
        if scaffold.team_stats_holder is not None:
            for child in scaffold.team_stats_holder.winfo_children():
                child.destroy()
        if scaffold.game_stats_holder is not None:
            for child in scaffold.game_stats_holder.winfo_children():
                child.destroy()
        if scaffold.points_holder is not None:
            for child in scaffold.points_holder.winfo_children():
                child.destroy()
        if scaffold.player_stats_holder is not None:
            for child in scaffold.player_stats_holder.winfo_children():
                child.destroy()
        if scaffold.goal_diff_holder is not None:
            for child in scaffold.goal_diff_holder.winfo_children():
                child.destroy()
        if scaffold.team_stats_tab is not None:
            controllers.pop(str(scaffold.team_stats_tab), None)
        if scaffold.game_stats_tab is not None:
            controllers.pop(str(scaffold.game_stats_tab), None)
        if scaffold.points_tab is not None:
            controllers.pop(str(scaffold.points_tab), None)
        if scaffold.goal_diff_tab is not None:
            controllers.pop(str(scaffold.goal_diff_tab), None)
        if scaffold.player_stats_tab is not None:
            controllers.pop(str(scaffold.player_stats_tab), None)
        # Models tabs also depend on league context now.
        stats_loaded["playoff_picture"] = False
        stats_loaded["magic_tragic"] = False
        stats_loaded["point_probabilities"] = False
        stats_loaded["playoff_win_probabilities"] = False
        if scaffold.playoff_picture_holder is not None:
            for child in scaffold.playoff_picture_holder.winfo_children():
                child.destroy()
        if scaffold.magic_tragic_holder is not None:
            for child in scaffold.magic_tragic_holder.winfo_children():
                child.destroy()
        if scaffold.point_probabilities_holder is not None:
            for child in scaffold.point_probabilities_holder.winfo_children():
                child.destroy()
        if scaffold.playoff_win_probabilities_holder is not None:
            for child in scaffold.playoff_win_probabilities_holder.winfo_children():
                child.destroy()
        if scaffold.playoff_picture_tab is not None:
            controllers.pop(str(scaffold.playoff_picture_tab), None)
        if scaffold.magic_tragic_tab is not None:
            controllers.pop(str(scaffold.magic_tragic_tab), None)
        if scaffold.point_probabilities_tab is not None:
            controllers.pop(str(scaffold.point_probabilities_tab), None)
        if scaffold.playoff_win_probabilities_tab is not None:
            controllers.pop(str(scaffold.playoff_win_probabilities_tab), None)

    def _toggle_stats_league() -> None:
        cur = str(app_state.get("stats_league", "NHL")).upper()
        app_state["stats_league"] = "PWHL" if cur == "NHL" else "NHL"
        sel = str(app_state.get("selected_team_code") or "").upper()
        if app_state["stats_league"] == "PWHL":
            if sel and sel not in pwhl_codes:
                app_state["selected_team_code"] = None
        else:
            if sel and sel not in all_codes_set:
                app_state["selected_team_code"] = None
        _update_team_button()
        _update_league_button()
        _invalidate_stats_numeric_tabs()
        _ensure_stats_tab_loaded()
        try:
            if isinstance(pred_tabs_ctrl, dict) and callable(pred_tabs_ctrl.get("redraw")):
                pred_tabs_ctrl["redraw"]()
        except Exception:
            pass
        try:
            if isinstance(public_pred_tabs_ctrl, dict) and callable(public_pred_tabs_ctrl.get("redraw")):
                public_pred_tabs_ctrl["redraw"]()
        except Exception:
            pass
        try:
            if scaffold.main_notebook.select() == str(scaffold.models_page):
                _ensure_models_tab_loaded()
        except Exception:
            pass

    league_btn.set_command(_toggle_stats_league)

    def _on_main_tab_changed(_event=None) -> None:
        try:
            selected = scaffold.main_notebook.select()
        except Exception:
            return
        if selected == str(scaffold.scoreboard_page):
            _load_scoreboard_if_needed()
        elif selected == str(scaffold.stats_page):
            _ensure_stats_tab_loaded()
        elif selected == str(scaffold.models_page):
            _ensure_models_tab_loaded()

    scaffold.main_notebook.bind("<<NotebookTabChanged>>", _on_main_tab_changed, add="+")

    pred_tabs_ctrl = mount_predictions_tabs(
        scaffold.pred_notebook,
        tables,
        tab_order=tab_order,
        tab_labels=tab_labels,
        tab_titles=tab_titles,
        start_date=start_date,
        images_dir=images_dir,
        all_codes=all_codes,
        canon_team_code=canon_team_code,
        team_colors=team_colors,
        logo_bank=logo_bank,
        team_col_width=team_col_width,
        cell_width=cell_width,
        get_selected_team_code=get_selected_team_code,
        set_selected_team_code=set_selected_team_code,
        render_pie_chart_tab=render_pie_chart_tab,
        render_df_heatmap_with_graph=render_df_heatmap_with_graph,
        controllers=controllers,
        add_gap_tab=scaffold.add_gap_tab,
        get_active_league=lambda: str(app_state.get("stats_league", "NHL")),
    )
    prof.mark("mount_predictions_tabs")
    public_pred_tabs_ctrl = mount_predictions_tabs(
        public_pred_notebook,
        public_tables,
        tab_order=tab_order,
        tab_labels=tab_labels,
        tab_titles=tab_titles,
        start_date=public_start_date,
        images_dir=images_dir,
        all_codes=all_codes,
        canon_team_code=canon_team_code,
        team_colors=team_colors,
        logo_bank=logo_bank,
        team_col_width=team_col_width,
        cell_width=cell_width,
        get_selected_team_code=get_selected_team_code,
        set_selected_team_code=set_selected_team_code,
        render_pie_chart_tab=render_pie_chart_tab,
        render_df_heatmap_with_graph=render_df_heatmap_with_graph,
        controllers=controllers,
        add_gap_tab=scaffold.add_gap_tab,
        get_active_league=lambda: str(app_state.get("stats_league", "NHL")),
    )
    prof.mark("mount_public_predictions_tabs")

    try:
        scaffold.main_notebook.select(scaffold.scoreboard_page)
    except Exception:
        pass

    prof.mark("initial_tab_select")
    prof.emit(prefix="[ui-startup]")

    root.mainloop()
