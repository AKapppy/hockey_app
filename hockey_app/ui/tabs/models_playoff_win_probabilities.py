from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from typing import Any, Callable

from hockey_app.ui.tabs.models_data import load_points_history, points_snapshot, regular_season_reference_day, standings_tiebreak_snapshot
from hockey_app.ui.tabs.models_logos import get_model_logo
from hockey_app.ui.tabs.models_playoff_math import (
    best_of_7_lengths_from_score as _shared_best_of_7_lengths_from_score,
    live_playoff_series_probabilities,
    series_probability_table,
    team_strength_snapshot,
)
from hockey_app.ui.tabs.models_playoff_picture import _bracket_snapshot, _series_score_snapshot, playoff_status_map


def _blend(a: str, b: str, t: float) -> str:
    t = max(0.0, min(1.0, float(t)))
    a = a.lstrip("#")
    b = b.lstrip("#")
    ar, ag, ab = int(a[0:2], 16), int(a[2:4], 16), int(a[4:6], 16)
    br, bg, bb = int(b[0:2], 16), int(b[2:4], 16), int(b[4:6], 16)
    r = int(ar + (br - ar) * t)
    g = int(ag + (bg - ag) * t)
    z = int(ab + (bb - ab) * t)
    return f"#{r:02x}{g:02x}{z:02x}"


def _heat_rank01(t: float) -> str:
    t = max(0.0, min(1.0, float(t)))
    t = round(t * 31) / 31
    if t <= 0.5:
        u = t / 0.5
        c = _blend("#ff0000", "#ffff00", u)
    else:
        u = (t - 0.5) / 0.5
        c = _blend("#ffff00", "#00ff00", u)
    return _blend(c, "#262626", 0.42)


def _best_of_7_lengths_from_score(
    p: float,
    wins_for: int,
    wins_against: int,
) -> tuple[float, float, float, float]:
    return _shared_best_of_7_lengths_from_score(p, wins_for, wins_against)


def _series_table(
    a: str,
    b: str,
    team_strength: dict[str, float],
    series_scores: dict[tuple[str, str], dict[str, int]] | None = None,
    live_series_probs: dict[tuple[str, str], dict[str, Any]] | None = None,
) -> dict[str, object]:
    return series_probability_table(
        a,
        b,
        team_strength=team_strength,
        series_scores=series_scores,
        live_series_probs=live_series_probs,
    )


def _pairwise(
    teams: list[str],
    team_strength: dict[str, float],
    series_scores: dict[tuple[str, str], dict[str, int]] | None = None,
    live_series_probs: dict[tuple[str, str], dict[str, Any]] | None = None,
) -> tuple[list[dict[str, object]], list[str]]:
    rows: list[dict[str, object]] = []
    winners: list[str] = []
    for i in range(0, len(teams), 2):
        a = teams[i] if i < len(teams) else ""
        b = teams[i + 1] if i + 1 < len(teams) else ""
        if not a or not b:
            continue
        info = _series_table(a, b, team_strength, series_scores, live_series_probs)
        rows.append(info)
        winners.append(str(info["winner"]))
    return rows, winners


def populate_playoff_win_probabilities_tab(
    parent,
    *,
    logo_bank: Any | None = None,
    league: str = "NHL",
) -> dict[str, Callable[[], None]]:
    for child in parent.winfo_children():
        child.destroy()

    df, _d0, d1 = load_points_history(league=league)
    seed_day = regular_season_reference_day(d1, league=str(league or "NHL").upper())
    pts = points_snapshot(df, seed_day)

    root = tk.Frame(parent, bg="#262626")
    root.pack(fill="both", expand=True)

    c = tk.Canvas(root, bg="#262626", highlightthickness=0)
    vs = tk.Scrollbar(root, orient="vertical", command=c.yview)
    c.configure(yscrollcommand=vs.set)
    c.grid(row=0, column=0, sticky="nsew")
    vs.grid(row=0, column=1, sticky="ns")
    root.grid_rowconfigure(0, weight=1)
    root.grid_columnconfigure(0, weight=1)

    def _lock_top() -> None:
        try:
            c.yview_moveto(0.0)
        except Exception:
            pass

    def _on_mousewheel(_event):
        # Keep table header docked at top; no vertical scrolling in this tab.
        _lock_top()
        return "break"

    def _on_linux_up(_event):
        _lock_top()
        return "break"

    def _on_linux_down(_event):
        _lock_top()
        return "break"

    c.bind("<MouseWheel>", _on_mousewheel)
    c.bind("<Button-4>", _on_linux_up)
    c.bind("<Button-5>", _on_linux_down)

    if not pts:
        c.create_text(20, 30, text="No data.", fill="#d0d0d0", anchor="w")

        def redraw() -> None:
            return

        def reset() -> None:
            return

        return {"redraw": redraw, "reset": reset}

    standings = standings_tiebreak_snapshot(seed_day) if str(league or "NHL").upper() == "NHL" else {}
    b = _bracket_snapshot(pts, standings)
    series_scores = _series_score_snapshot(d1, league=str(league or "NHL").upper())
    status_map = playoff_status_map(d1, pts, standings, league=str(league or "NHL").upper(), series_scores=series_scores)
    team_strength = team_strength_snapshot(d1, league=str(league or "NHL").upper())
    live_series_probs = live_playoff_series_probabilities(d1, league=str(league or "NHL").upper())
    west_r1 = [t for t in b.get("West_R1", []) if t]
    east_r1 = [t for t in b.get("East_R1", []) if t]

    rounds: list[tuple[str, list[dict[str, object]]]] = []
    r1_w, w_winners = _pairwise(west_r1, team_strength, series_scores, live_series_probs)
    r1_e, e_winners = _pairwise(east_r1, team_strength, series_scores, live_series_probs)
    rounds.append(("Round 1", r1_w + r1_e))
    r2_w, w2 = _pairwise(w_winners, team_strength, series_scores, live_series_probs)
    r2_e, e2 = _pairwise(e_winners, team_strength, series_scores, live_series_probs)
    if r2_w or r2_e:
        rounds.append(("Round 2", r2_w + r2_e))
    cf_w, w3 = _pairwise(w2, team_strength, series_scores, live_series_probs)
    cf_e, e3 = _pairwise(e2, team_strength, series_scores, live_series_probs)
    cf = cf_w + cf_e
    if cf:
        rounds.append(("Conference Finals", cf))
    cup, _ = _pairwise(w3 + e3, team_strength, series_scores, live_series_probs)
    if cup:
        rounds.append(("Stanley Cup Final", cup))

    c.update_idletasks()
    view_w = int(c.winfo_width() or 1700)
    view_h = int(c.winfo_height() or 900)
    y = 14
    left_round = next((rs for title, rs in rounds if title == "Round 1"), [])
    cup_round = next(((title, rs) for title, rs in rounds if title == "Stanley Cup Final"), None)
    right_rounds = [(title, rs) for title, rs in rounds if title not in {"Round 1", "Stanley Cup Final"}]
    left_units = 1 + (2 * len(left_round)) + 2
    right_units = sum(1 + (2 * len(rs)) + 2 for _title, rs in right_rounds)
    units = max(8, left_units, right_units)
    row_h = max(22, min(40, int((view_h - 48) / units)))
    header_font = ("TkDefaultFont", 15, "bold")
    cell_font = ("TkDefaultFont", 14)
    header_font_obj = tkfont.Font(font=header_font)
    cell_font_obj = tkfont.Font(font=cell_font)

    def _fit_col(title: str, samples: list[str], *, pad: int = 18, min_w: int = 0) -> int:
        vals = [title] + [s for s in samples if s]
        text_w = max((header_font_obj.measure(v) for v in vals), default=0)
        cell_w = max((cell_font_obj.measure(v) for v in vals), default=0)
        return max(min_w, int(max(text_w, cell_w) + pad))

    cols = [
        ("Series", max(132, _fit_col("Series", [f"{str(sr['a'])} vs {str(sr['b'])}" for _t, rr in rounds for sr in rr], pad=24))),
        ("Team", max(58, int(row_h * 2.1))),
        ("in 4", _fit_col("in 4", ["100.00%"], pad=12)),
        ("in 5", _fit_col("in 5", ["100.00%"], pad=12)),
        ("in 6", _fit_col("in 6", ["100.00%"], pad=12)),
        ("in 7", _fit_col("in 7", ["100.00%"], pad=12)),
        ("Prediction", _fit_col("Prediction", [str(sr["pred"]) for _t, rr in rounds for sr in rr], pad=20)),
    ]
    live_imgs: list[Any] = []

    def pct_txt(v: float) -> str:
        if v <= 0:
            return ""
        if v * 100 < 0.01:
            return "<.01%"
        return f"{v*100:.2f}%"

    col_total_w = sum(w for _n, w in cols)
    gap_w = 14
    total_layout_w = col_total_w * 2 + gap_w
    x0 = max(8, int((view_w - total_layout_w) / 2))
    left_x = x0
    right_x = x0 + col_total_w + gap_w
    round_gap = 24

    def draw_round_block(round_title: str, series_rows: list[dict[str, object]], x_base: int, y_base: int) -> int:
        y_loc = y_base
        c.create_text(
            x_base + (col_total_w / 2),
            y_loc,
            text=round_title,
            fill="#f0f0f0",
            anchor="center",
            font=("TkDefaultFont", 17, "bold"),
        )
        y_loc += 18

        x = x_base
        for name, w in cols:
            c.create_rectangle(x, y_loc, x + w, y_loc + row_h, fill="#2f2f2f", outline="#3a3a3a")
            c.create_text(x + w / 2, y_loc + row_h / 2, text=name, fill="#f0f0f0", anchor="center", font=header_font)
            x += w
        y_loc += row_h

        for sr in series_rows:
            a = str(sr["a"])
            b2 = str(sr["b"])
            a4, a5, a6, a7 = sr["a_probs"]  # type: ignore[misc]
            b4, b5, b6, b7 = sr["b_probs"]  # type: ignore[misc]
            pred = str(sr["pred"])
            a_elim = status_map.get(a) == "eliminated"
            b_elim = status_map.get(b2) == "eliminated"

            top_y = y_loc
            c.create_rectangle(x_base, top_y, x_base + cols[0][1], top_y + row_h * 2, fill="#2a2a2a", outline="#3a3a3a")
            series_x0 = x_base
            series_w = cols[0][1]
            a_logo = get_model_logo(a, height=max(18, int(row_h * 0.9)), logo_bank=logo_bank, league=league, master=c, dim=a_elim)
            b_logo = get_model_logo(b2, height=max(18, int(row_h * 0.9)), logo_bank=logo_bank, league=league, master=c, dim=b_elim)
            if a_logo is not None and b_logo is not None:
                live_imgs.extend((a_logo, b_logo))
                gap = 10
                a_w = int(a_logo.width())
                b_w = int(b_logo.width())
                vs_w = max(16, int(cell_font_obj.measure("vs")))
                group_w = a_w + gap + vs_w + gap + b_w
                sx = series_x0 + (series_w - group_w) / 2
                cy = top_y + row_h
                c.create_image(sx + a_w / 2, cy, image=a_logo, anchor="center")
                c.create_text(sx + a_w + gap + (vs_w / 2), cy, text="vs", fill="#f0f0f0", anchor="center", font=cell_font)
                c.create_image(sx + a_w + gap + vs_w + gap + (b_w / 2), cy, image=b_logo, anchor="center")
            else:
                c.create_text(series_x0 + series_w / 2, top_y + row_h, text=f"{a} vs {b2}", fill="#f0f0f0", anchor="center", font=cell_font)

            pred_x0 = x_base + sum(w for _, w in cols[:-1])
            pred_w = cols[-1][1]
            c.create_rectangle(pred_x0, top_y, pred_x0 + pred_w, top_y + row_h * 2, fill="#2a2a2a", outline="#3a3a3a")
            c.create_text(pred_x0 + pred_w / 2, top_y + row_h, text=pred, fill="#f0f0f0", anchor="center", font=cell_font)

            row_defs = [
                (a, (a4, a5, a6, a7), top_y, a_elim),
                (b2, (b4, b5, b6, b7), top_y + row_h, b_elim),
            ]
            series_vals = [a4, a5, a6, a7, b4, b5, b6, b7]
            series_max = max(series_vals) if series_vals else 0.0

            for team, probs, ry, eliminated in row_defs:
                p4, p5, p6, p7 = probs
                tx0 = x_base + cols[0][1]
                team_fill = "#3a3a3a" if eliminated else "#2a2a2a"
                text_fill = "#9e9e9e" if eliminated else "#f0f0f0"
                c.create_rectangle(tx0, ry, tx0 + cols[1][1], ry + row_h, fill=team_fill, outline="#3a3a3a")
                img = get_model_logo(
                    team,
                    height=20,
                    logo_bank=logo_bank,
                    league=league,
                    master=c,
                    dim=eliminated,
                )
                if img is not None:
                    live_imgs.append(img)
                    c.create_image(tx0 + cols[1][1] / 2, ry + row_h / 2, image=img, anchor="center")
                else:
                    c.create_text(tx0 + cols[1][1] / 2, ry + row_h / 2, text=team, fill=text_fill, anchor="center", font=cell_font)

                x2 = tx0 + cols[1][1]
                for val, (_name, w) in zip((p4, p5, p6, p7), cols[2:6]):
                    impossible = val <= 0.0
                    fill = "#3a3a3a" if eliminated else ("#353535" if impossible else (_heat_rank01(val / series_max) if series_max > 0 else _heat_rank01(0.0)))
                    c.create_rectangle(x2, ry, x2 + w, ry + row_h, fill=fill, outline="#3a3a3a")
                    txt_fill = "#888888" if eliminated else ("#9a9a9a" if impossible else "#f0f0f0")
                    c.create_text(x2 + w / 2, ry + row_h / 2, text=pct_txt(val), fill=txt_fill, anchor="center", font=cell_font)
                    x2 += w
            y_loc += row_h * 2
        return y_loc

    left_bottom = draw_round_block("Round 1", left_round, left_x, y)
    right_bottom = y
    right_map = {title: rs for title, rs in right_rounds}
    if "Round 2" in right_map and "Conference Finals" in right_map:
        r2_rows = right_map["Round 2"]
        cf_rows = right_map["Conference Finals"]
        r2_bottom = draw_round_block("Round 2", r2_rows, right_x, y)
        block_h_cf = 18 + row_h + (2 * row_h * len(cf_rows))
        cf_y = max(y, int(left_bottom - block_h_cf))
        cf_bottom = draw_round_block("Conference Finals", cf_rows, right_x, cf_y)
        right_bottom = max(r2_bottom, cf_bottom)
    else:
        for title, rs in right_rounds:
            right_bottom = draw_round_block(title, rs, right_x, right_bottom)
            right_bottom += round_gap

    if cup_round is not None:
        cup_title, cup_rows = cup_round
        cup_x = int(x0 + (total_layout_w - col_total_w) / 2.0)
        cup_y = max(left_bottom, right_bottom) + round_gap
        cup_bottom = draw_round_block(cup_title, cup_rows, cup_x, cup_y)
        right_bottom = max(right_bottom, cup_bottom)

    total_w = right_x + col_total_w + 8
    total_h = max(left_bottom, right_bottom) + 18
    c.configure(scrollregion=(0, 0, max(view_w, total_w), max(view_h, total_h)))
    _lock_top()
    c.bind("<Configure>", lambda _e: _lock_top(), add="+")
    try:
        view_wf = float(max(1, c.winfo_width()))
        if float(total_w) <= view_wf:
            c.xview_moveto(0.0)
        else:
            c.xview_moveto(0.5)
    except Exception:
        pass

    def redraw() -> None:
        return

    def reset() -> None:
        try:
            c.yview_moveto(0.0)
        except Exception:
            pass

    return {"redraw": redraw, "reset": reset}
