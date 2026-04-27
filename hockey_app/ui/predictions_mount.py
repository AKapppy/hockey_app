from __future__ import annotations

import datetime as dt
import xml.etree.ElementTree as ET
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

import pandas as pd

from hockey_app.config import SEASON
from hockey_app.data.paths import cache_dir


def _prediction_day_for_last_column(start_date: dt.date, df: pd.DataFrame) -> dt.date:
    if not isinstance(df, pd.DataFrame) or len(df.columns) == 0:
        return start_date
    return start_date + dt.timedelta(days=max(0, len(df.columns) - 1))


def _prediction_series_for_day(
    df: pd.DataFrame,
    *,
    start_date: dt.date,
    day: dt.date,
) -> pd.Series:
    if not isinstance(df, pd.DataFrame) or len(df.columns) == 0:
        return pd.Series(dtype="float64")
    idx = max(0, min((day - start_date).days, len(df.columns) - 1))
    try:
        series = pd.to_numeric(df.iloc[:, idx], errors="coerce")
    except Exception:
        return pd.Series(dtype="float64")
    series.index = [str(code) for code in series.index]
    return series


def _qualified_prediction_codes_for_round(
    tables: dict[str, pd.DataFrame],
    *,
    source_key: str,
    start_date: dt.date,
    day: dt.date,
    tol: float = 1e-9,
) -> list[str]:
    source_df = tables.get(source_key)
    if not isinstance(source_df, pd.DataFrame) or source_df.empty:
        return []
    series = _prediction_series_for_day(source_df, start_date=start_date, day=day)
    out: list[str] = []
    for code, val in series.items():
        if pd.isna(val):
            continue
        if float(val) >= (1.0 - tol):
            out.append(str(code))
    return out


def _first_locked_prediction_column(df: pd.DataFrame, *, tol: float = 1e-9) -> int | None:
    if not isinstance(df, pd.DataFrame) or df.empty or len(df.columns) == 0:
        return None
    for idx, col in enumerate(df.columns):
        series = pd.to_numeric(df[col], errors="coerce").dropna()
        if series.empty:
            continue
        locked = True
        for val in series.tolist():
            fv = float(val)
            if abs(fv - 0.0) <= tol or abs(fv - 1.0) <= tol:
                continue
            locked = False
            break
        if locked:
            return idx
    return None


def _trim_prediction_df_at_locked_column(df: pd.DataFrame) -> pd.DataFrame:
    cut_idx = _first_locked_prediction_column(df)
    if cut_idx is None:
        return df
    keep_cols = list(df.columns[: cut_idx + 1])
    return df.loc[:, keep_cols].copy()


def _playoff_filtered_prediction_df(
    df: pd.DataFrame,
    *,
    tab_key: str,
    start_date: dt.date,
    league: str,
    tables: dict[str, pd.DataFrame] | None = None,
) -> pd.DataFrame:
    if str(league or "NHL").upper() != "NHL":
        return df
    if tab_key not in {"round2", "round3", "round4", "woncup"}:
        return df

    from hockey_app.ui.tabs.models_data import playoff_field_order, playoffs_have_started

    last_day = _prediction_day_for_last_column(start_date, df)
    if not playoffs_have_started(last_day, league="NHL"):
        return df

    field = [str(code) for code in playoff_field_order(last_day, league="NHL")]
    if not field:
        return df

    available = {str(code) for code in df.index}
    ordered = [code for code in field if code in available]
    if not ordered:
        return df
    source_key = {
        "round2": "madeplayoffs",
        "round3": "round2",
        "round4": "round3",
        "woncup": "round4",
    }.get(tab_key)
    if source_key and isinstance(tables, dict):
        qualified = _qualified_prediction_codes_for_round(
            tables,
            source_key=source_key,
            start_date=start_date,
            day=last_day,
        )
        if qualified:
            qualified_set = {str(code) for code in qualified}
            ordered = [code for code in ordered if code in qualified_set] + [code for code in ordered if code not in qualified_set]
    tail = [str(code) for code in df.index if str(code) not in set(ordered)]
    return df.loc[ordered + tail].copy()


def _rightmost_column_team_order(df: pd.DataFrame) -> list[str]:
    if not isinstance(df, pd.DataFrame) or df.empty or len(df.columns) == 0:
        return [str(code) for code in getattr(df, "index", [])]
    work = df.copy()
    sort_cols: list[str] = []
    ascending: list[bool] = []
    for idx, col in enumerate(reversed(list(df.columns))):
        tmp_col = f"__sort_val_{idx}__"
        work[tmp_col] = pd.to_numeric(work[col], errors="coerce")
        sort_cols.append(tmp_col)
        ascending.append(False)
    work["__sort_team__"] = [str(code).upper() for code in work.index]
    sort_cols.append("__sort_team__")
    ascending.append(True)
    work = work.sort_values(
        by=sort_cols,
        ascending=ascending,
        na_position="last",
        kind="mergesort",
    )
    return [str(code) for code in work.index]


def _prepare_prediction_render_df(
    df: pd.DataFrame,
    *,
    tab_key: str,
    start_date: dt.date,
    league: str,
    tables: dict[str, pd.DataFrame] | None = None,
) -> pd.DataFrame:
    work = df.copy()
    work = _playoff_filtered_prediction_df(
        work,
        tab_key=tab_key,
        start_date=start_date,
        league=league,
        tables=tables,
    )
    if tab_key in {"madeplayoffs", "round2", "round3", "round4", "woncup"}:
        work = _trim_prediction_df_at_locked_column(work)
    return work


def _prediction_visible_row_count(
    tables: dict[str, pd.DataFrame],
    *,
    tab_key: str,
    start_date: dt.date,
    league: str,
    prepared_df: pd.DataFrame,
) -> int | None:
    if str(league or "NHL").upper() != "NHL":
        return None
    day = _prediction_day_for_last_column(start_date, prepared_df)
    started_round = _playoff_started_round(day, league=league)
    if started_round <= 0:
        return None

    thresholds = {
        "round2": ((1, 16),),
        "round3": ((2, 8), (1, 16)),
        "round4": ((3, 4), (2, 8), (1, 16)),
        "woncup": ((4, 2), (3, 4), (2, 8), (1, 16)),
    }.get(tab_key)
    if not thresholds:
        return None

    for threshold_round, visible_count in thresholds:
        if started_round >= threshold_round:
            return min(len(prepared_df.index), int(visible_count))
    return None


def _playoff_started_round(day: dt.date, *, league: str) -> int:
    if str(league or "NHL").upper() != "NHL":
        return 0
    path = cache_dir() / "online" / "xml" / str(SEASON) / "games.xml"
    if not path.exists():
        return 0
    try:
        root = ET.parse(path).getroot()
    except Exception:
        return 0

    max_round = 0
    for day_node in root.findall("day"):
        raw_day = str(day_node.get("date") or "").strip()
        try:
            game_day = dt.date.fromisoformat(raw_day[:10])
        except Exception:
            continue
        if game_day > day:
            continue
        for game in day_node.findall("game"):
            if str(game.get("league") or "").upper() != "NHL":
                continue
            round_no = _xml_playoff_round(game)
            if round_no > max_round:
                max_round = round_no
    return max_round


def _xml_playoff_round(game_node: ET.Element) -> int:
    raw_round = str(game_node.get("playoff_round") or "").strip()
    try:
        round_no = int(raw_round)
        if 1 <= round_no <= 4:
            return round_no
    except Exception:
        pass

    game_type = str(game_node.get("game_type") or game_node.get("game_type_id") or game_node.get("game_type_code") or "").strip().upper()
    gid = str(game_node.get("id") or "").strip()
    if game_type not in {"3", "P"} and not gid.startswith("202503"):
        return 0
    try:
        round_no = int(gid[6:8])
    except Exception:
        return 0
    return round_no if 1 <= round_no <= 4 else 0


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

        base_df = _prepare_prediction_render_df(
            tables[key],
            tab_key=key,
            start_date=start_date,
            league=_league_u(),
            tables=tables,
        )
        base_df.index = [canon_team_code(str(x)) for x in base_df.index]
        base_df = base_df[~base_df.index.duplicated(keep="first")]
        original_order = _rightmost_column_team_order(base_df)
        visible_row_count = _prediction_visible_row_count(
            tables,
            tab_key=key,
            start_date=start_date,
            league=_league_u(),
            prepared_df=base_df,
        )

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
                initial_team_order=original_order,
                visible_row_count=visible_row_count,
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
