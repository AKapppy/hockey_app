from __future__ import annotations

import datetime as dt
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

import pandas as pd


def mount_predictions_tabs(
    pred_notebook: ttk.Notebook,
    tables: dict[str, pd.DataFrame],
    *,
    tab_order: list[str],
    tab_labels: dict[str, str],
    tab_titles: dict[str, str],
    start_date: dt.date,
    images_dir: Path,
    all_codes: list[str],
    canon_team_code: Callable[[str], str],
    team_colors: dict[str, str],
    logo_bank,
    team_col_width: int,
    cell_width: int,
    get_selected_team_code: Callable[[], str | None],
    set_selected_team_code: Callable[[str | None], None],
    render_pie_chart_tab: Callable[..., dict[str, Callable[[], None]]],
    render_df_heatmap_with_graph: Callable[..., dict[str, Callable[[], None]]],
    controllers: dict[str, dict[str, Callable[[], None]]],
    add_gap_tab: Callable[[ttk.Notebook], None],
    get_active_league: Callable[[], str] | None = None,
) -> dict[str, Callable[[], None]]:
    pie_tab = ttk.Frame(pred_notebook, padding=0)
    pred_notebook.add(pie_tab, text="Pie Chart")
    add_gap_tab(pred_notebook)
    pie_tab.grid_rowconfigure(0, weight=1)
    pie_tab.grid_columnconfigure(0, weight=1)

    metric_tabs: dict[str, ttk.Frame] = {}
    for key in tab_order:
        if key not in tables:
            continue
        tab = ttk.Frame(pred_notebook, padding=0)
        pred_notebook.add(tab, text=tab_labels.get(key, key.title()))
        tab.grid_rowconfigure(0, weight=1)
        tab.grid_columnconfigure(0, weight=1)
        metric_tabs[key] = tab

    built: dict[str, bool] = {"__pie__": False}

    def _prediction_default_team_order() -> list[str]:
        # Keep "best team stays on top" across tabs:
        # Cup -> Finals -> Conference Final -> Round 2 -> Make Playoffs.
        priority = [k for k in ("woncup", "round4", "round3", "round2", "madeplayoffs") if k in tables]
        if not priority:
            return [canon_team_code(str(c)) for c in all_codes]

        values_by_metric: dict[str, dict[str, float]] = {}
        team_pool: set[str] = {canon_team_code(str(c)) for c in all_codes}

        for key in priority:
            dfi = tables.get(key)
            if not isinstance(dfi, pd.DataFrame) or dfi.empty or len(dfi.columns) == 0:
                continue
            work = dfi.copy()
            work.index = [canon_team_code(str(x)) for x in work.index]
            work = work[~work.index.duplicated(keep="first")]
            col = work.columns[-1]
            series = pd.to_numeric(work[col], errors="coerce")
            metric_vals: dict[str, float] = {}
            for code, val in series.items():
                cc = canon_team_code(str(code))
                team_pool.add(cc)
                if pd.isna(val):
                    continue
                metric_vals[cc] = float(val)
            values_by_metric[key] = metric_vals

        def _rank_tuple(code: str) -> tuple[float, float, float, float, float, str]:
            c = canon_team_code(str(code))
            vals = [float(values_by_metric.get(metric, {}).get(c, -1.0)) for metric in priority]
            while len(vals) < 5:
                vals.append(-1.0)
            return (-vals[0], -vals[1], -vals[2], -vals[3], -vals[4], c)

        return sorted(team_pool, key=_rank_tuple)

    default_team_order = _prediction_default_team_order()

    def _league_u() -> str:
        if get_active_league is None:
            return "NHL"
        try:
            return str(get_active_league() or "NHL").upper()
        except Exception:
            return "NHL"

    def _is_pwhl_mode() -> bool:
        return _league_u() == "PWHL"

    def _clear_tab(tab: ttk.Frame) -> None:
        for child in tab.winfo_children():
            child.destroy()
        controllers.pop(str(tab), None)

    def _render_coming_soon(tab: ttk.Frame, *, title: str) -> None:
        _clear_tab(tab)
        msg = tk.Frame(tab, bg="#262626")
        msg.grid(row=0, column=0, sticky="nsew")
        msg.grid_rowconfigure(0, weight=1)
        msg.grid_columnconfigure(0, weight=1)
        inner = tk.Frame(msg, bg="#2f2f2f", bd=1, highlightthickness=1, highlightbackground="#3a3a3a")
        inner.place(relx=0.5, rely=0.5, anchor="center")
        tk.Label(
            inner,
            text=title,
            bg="#2f2f2f",
            fg="#f0f0f0",
            font=("TkDefaultFont", 18, "bold"),
            padx=20,
            pady=10,
        ).pack()
        tk.Label(
            inner,
            text="PWHL prediction data is not available yet.",
            bg="#2f2f2f",
            fg="#d0d0d0",
            font=("TkDefaultFont", 12),
            padx=20,
            pady=(0, 16),
        ).pack()
        controllers[str(tab)] = {"redraw": (lambda: None), "reset": (lambda: None)}

    def _build_pie_if_needed() -> None:
        if built["__pie__"]:
            return
        if _is_pwhl_mode():
            _render_coming_soon(pie_tab, title="Predictions Coming Soon")
            built["__pie__"] = True
            return
        try:
            ctrl = render_pie_chart_tab(
                pie_tab,
                tables,
                metric_order=tab_order,
                metric_labels=tab_labels,
                team_colors=team_colors,
                logo_bank=logo_bank,
                original_order=all_codes,
                team_col_width=team_col_width,
                cell_width=cell_width,
                get_selected_team_code=get_selected_team_code,
                set_selected_team_code=set_selected_team_code,
                start_date=start_date,
                images_dir=images_dir,
                cell_height=22,
            )
            controllers[str(pie_tab)] = ctrl
            built["__pie__"] = True
        except Exception as e:
            messagebox.showerror("UI Error", f"Failed to render Pie Chart tab:\n{e}")

    def _build_metric_if_needed(key: str) -> None:
        if built.get(key):
            return
        tab = metric_tabs.get(key)
        if tab is None:
            return
        if _is_pwhl_mode():
            _render_coming_soon(tab, title=f"{tab_labels.get(key, key.title())} Coming Soon")
            built[key] = True
            return

        base_df = tables[key].copy()
        base_df.index = [canon_team_code(str(x)) for x in base_df.index]
        base_df = base_df[~base_df.index.duplicated(keep="first")]
        original_order = list(map(str, base_df.index))

        try:
            ctrl = render_df_heatmap_with_graph(
                tab,
                base_df,
                tab_key=key,
                tab_title=tab_titles.get(key, tab_labels.get(key, key.title())),
                team_colors=team_colors,
                logo_bank=logo_bank,
                original_order=original_order,
                team_col_width=team_col_width,
                cell_width=cell_width,
                get_selected_team_code=get_selected_team_code,
                set_selected_team_code=set_selected_team_code,
                cell_height=22,
                graph_pad_y=12,
                hscroll_units=1,
                start_date=start_date,
                initial_team_order=default_team_order,
            )
            controllers[str(tab)] = ctrl
            built[key] = True
        except Exception as e:
            messagebox.showerror("UI Error", f"Failed to render tab '{key}':\n{e}")

    def _on_pred_tab_changed(_event=None) -> None:
        try:
            tid = pred_notebook.select()
        except Exception:
            return
        if tid == str(pie_tab):
            _build_pie_if_needed()
            return
        for key, tab in metric_tabs.items():
            if tid == str(tab):
                _build_metric_if_needed(key)
                return

    pred_notebook.bind("<<NotebookTabChanged>>", _on_pred_tab_changed, add="+")

    try:
        pred_notebook.select(pie_tab)
    except Exception:
        pass
    _build_pie_if_needed()
    def redraw() -> None:
        built["__pie__"] = False
        _clear_tab(pie_tab)
        for key, tab in metric_tabs.items():
            built[key] = False
            _clear_tab(tab)
        _on_pred_tab_changed()

    return {"redraw": redraw}
