from __future__ import annotations

import datetime as dt
import math
import tkinter as tk
from typing import Any, Callable

from hockey_app.config import TEAM_NAMES, TEAM_TO_CONF, TEAM_TO_DIV
from hockey_app.ui.tabs.models_data import (
    games_played_snapshot,
    load_points_history,
    points_snapshot,
    standings_tiebreak_snapshot,
)
from hockey_app.ui.tabs.models_logos import get_model_logo


def _team_sort_key(
    code: str,
    pts: dict[str, float],
    standings: dict[str, dict[str, Any]] | None,
    *,
    scope: str,
) -> tuple[Any, ...]:
    def _to_int(v: Any, default: int = 0) -> int:
        try:
            return int(v)
        except Exception:
            try:
                return int(float(v))
            except Exception:
                return int(default)

    info = (standings or {}).get(code, {}) if isinstance(standings, dict) else {}
    seq_key = "leagueSequence"
    if scope == "conf":
        seq_key = "conferenceSequence"
    elif scope == "div":
        seq_key = "divisionSequence"
    seq = _to_int(info.get(seq_key) if isinstance(info, dict) else 999, 999)
    pts_v = float(pts.get(code, 0.0))
    row_v = _to_int(info.get("row") if isinstance(info, dict) else 0, 0)
    rw_v = _to_int(info.get("rw") if isinstance(info, dict) else 0, 0)
    # Prefer official standings sequence when available. It already bakes in
    # NHL tiebreak progression (ROW/RW/head-to-head and beyond).
    if 1 <= seq < 900:
        return (0, seq, -pts_v, -row_v, -rw_v, TEAM_NAMES.get(code, code), code)
    return (1, -pts_v, -row_v, -rw_v, TEAM_NAMES.get(code, code), code)


def _conf_teams(
    pts: dict[str, float],
    conf: str,
    standings: dict[str, dict[str, Any]] | None = None,
) -> list[str]:
    return sorted(
        [c for c in pts if TEAM_TO_CONF.get(c) == conf],
        key=lambda c: _team_sort_key(c, pts, standings, scope="conf"),
    )


def _div_teams(
    pts: dict[str, float],
    div: str,
    standings: dict[str, dict[str, Any]] | None = None,
) -> list[str]:
    return sorted(
        [c for c in pts if TEAM_TO_DIV.get(c) == div],
        key=lambda c: _team_sort_key(c, pts, standings, scope="div"),
    )


def _target_points(
    pts: dict[str, float],
    conf: str,
    standings: dict[str, dict[str, Any]] | None = None,
) -> dict[str, float]:
    if conf == "East":
        d1, d2 = "Metro", "Atlantic"
    else:
        d1, d2 = "Central", "Pacific"

    d1_list = _div_teams(pts, d1, standings)
    d2_list = _div_teams(pts, d2, standings)
    conf_list = _conf_teams(pts, conf, standings)

    top_d1 = set(d1_list[:3])
    top_d2 = set(d2_list[:3])
    wc_pool = [c for c in conf_list if c not in top_d1 and c not in top_d2]

    def p_of(lst: list[str], i: int) -> float:
        return float(pts[lst[i]]) if i < len(lst) else 0.0

    out = {
        "D1_1": p_of(d1_list, 0),
        "D1_2": p_of(d1_list, 1),
        "D1_3": p_of(d1_list, 2),
        "D2_1": p_of(d2_list, 0),
        "D2_2": p_of(d2_list, 1),
        "D2_3": p_of(d2_list, 2),
        "WC1": p_of(wc_pool, 0),
        "WC2": p_of(wc_pool, 1),
        "NP9": float(pts[conf_list[8]]) if len(conf_list) > 8 else 0.0,
    }
    return out


def _kth_highest(values: list[float], k: int) -> float:
    if k <= 0 or not values:
        return 0.0
    s = sorted((float(v) for v in values), reverse=True)
    idx = min(len(s), k) - 1
    return s[idx]


def _magic_cell(
    cur_pts: float,
    max_pts: float,
    slot_pts: float,
    rival_max_pts: float,
    rival_next_max_pts: float,
    gr: int,
    playoff_cutoff_rival_max_pts: float,
) -> str:
    """
    Winning-magic semantics (PlayoffStatus style):
    - *: already clinched this slot (or better)
    - X: cannot win this slot (even with help)
    - DNCD: can still win, but not by own results alone
    - N: games this team must win to force-clinch this slot
    """
    cur = float(cur_pts)
    mx = float(max_pts)
    slot = float(slot_pts)
    rival = float(rival_max_pts)
    games_left = max(0, int(gr))

    # If this team's current points already exceed all relevant rival maxima,
    # this slot is mathematically locked.
    if cur > max(slot, rival) + 0.1:
        return "*"
    # If even best-case points cannot reach current slot floor, slot is gone.
    if mx < slot + 1.0 - 0.1:
        return "X"

    # Own-control threshold: beat slot and rival ceilings if they win out.
    threshold = max(slot, rival) + 1.0
    wins_needed = int(math.ceil((threshold - cur) / 2.0))
    if wins_needed <= 0:
        return "*"
    if wins_needed > games_left:
        # Still mathematically alive (with help), but no longer in own control.
        return "DNCD"
    _ = (float(rival_next_max_pts), float(playoff_cutoff_rival_max_pts))
    return str(wins_needed)


def _tragic_cell(
    cur_pts: float,
    max_pts: float,
    slot_pts: float,
    rival_max_pts: float,
    rival_next_max_pts: float,
    gr: int,
    playoff_cutoff_rival_max_pts: float,
) -> str:
    """
    Losing-magic semantics (PlayoffStatus style):
    - *: guaranteed to finish better than this slot
    - X: cannot win this slot anymore
    - MW: might still win this slot even after losing out
    - N: games this team must lose to guarantee losing this slot
    """
    cur = float(cur_pts)
    mx = float(max_pts)
    slot = float(slot_pts)
    rival = float(rival_max_pts)
    games_left = max(0, int(gr))

    # Better-than-slot already locked.
    if cur > rival + 0.1:
        return "*"

    win_threshold = slot + 1.0
    if mx < win_threshold - 0.1:
        return "X"

    losses_needed = int(math.floor((mx - win_threshold) / 2.0)) + 1
    if losses_needed <= 0:
        return "X"
    if losses_needed > games_left:
        return "MW"
    _ = (float(rival_next_max_pts), float(playoff_cutoff_rival_max_pts))
    return str(losses_needed)


def populate_magic_tragic_tab(
    parent,
    *,
    logo_bank: Any | None = None,
    league: str = "NHL",
) -> dict[str, Callable[[], None]]:
    for child in parent.winfo_children():
        child.destroy()

    df, d0, d1 = load_points_history(league=league)
    days: list[dt.date] = []
    d = d0
    while d <= d1:
        days.append(d)
        d += dt.timedelta(days=1)
    if not days:
        days = [dt.date.today()]

    root = tk.Frame(parent, bg="#262626")
    root.pack(fill="both", expand=True)
    root.grid_rowconfigure(1, weight=1)
    root.grid_columnconfigure(0, weight=1)

    top = tk.Frame(root, bg="#262626")
    top.grid(row=0, column=0, sticky="ew", pady=(8, 6))
    top.grid_columnconfigure(1, weight=1)
    top.grid_columnconfigure(2, weight=1)

    prev_btn = tk.Label(top, text="◀", bg="#3a3a3a", fg="#f0f0f0", padx=8, pady=4, cursor="hand2")
    next_btn = tk.Label(top, text="▶", bg="#3a3a3a", fg="#f0f0f0", padx=8, pady=4, cursor="hand2")
    date_lbl = tk.Label(top, text="", bg="#262626", fg="#f0f0f0", font=("TkDefaultFont", 18, "bold"))
    mode_btn = tk.Label(top, text="Mode: Both", bg="#3a3a3a", fg="#f0f0f0", padx=10, pady=4, cursor="hand2")

    prev_btn.grid(row=0, column=0, sticky="w", padx=(8, 8))
    date_lbl.place(relx=0.5, rely=0.5, anchor="center")
    next_btn.grid(row=0, column=2, sticky="e", padx=(8, 8))
    mode_btn.grid(row=0, column=3, sticky="e", padx=(8, 8))

    c = tk.Canvas(root, bg="#262626", highlightthickness=0)
    c.grid(row=1, column=0, sticky="nsew")
    vs = tk.Scrollbar(root, orient="vertical", command=c.yview)
    c.configure(yscrollcommand=vs.set)
    vs.grid(row=1, column=1, sticky="ns")

    today = dt.date.today()
    if today < days[0]:
        default_idx = 0
    elif today > days[-1]:
        default_idx = len(days) - 1
    else:
        default_idx = (today - days[0]).days
    state = {"idx": default_idx, "mode": "both"}
    live_imgs: list[Any] = []
    resize_after_id: str | None = None
    tie_cache: dict[dt.date, dict[str, dict[str, Any]]] = {}

    def _tie_map(day: dt.date) -> dict[str, dict[str, Any]]:
        if str(league or "NHL").upper() != "NHL":
            return {}
        hit = tie_cache.get(day)
        if isinstance(hit, dict):
            return hit
        try:
            hit = standings_tiebreak_snapshot(day)
        except Exception:
            hit = {}
        tie_cache[day] = hit if isinstance(hit, dict) else {}
        return tie_cache[day]

    def _table(
        conf: str,
        x0: int,
        y0: int,
        tragic: bool,
        *,
        scale: float = 1.0,
        standings: dict[str, dict[str, Any]] | None = None,
    ) -> tuple[int, int]:
        pts = points_snapshot(df, days[state["idx"]])
        gp_map = games_played_snapshot(days[state["idx"]], league=league)
        conf_codes = _conf_teams(pts, conf, standings)

        div1, div2 = ("Metro", "Atlantic") if conf == "East" else ("Central", "Pacific")
        # Wide layout close to spreadsheet shape; team + slot numbers only.
        sf = max(0.48, min(1.10, float(scale)))
        w_team = max(54, int(round(86 * sf)))
        w_slot = max(38, int(round(66 * sf)))
        row_h = max(20, int(round(24 * sf)))
        cols = [
            ("Team", w_team),
            ("D1_1", w_slot),
            ("D1_2", w_slot),
            ("D1_3", w_slot),
            ("D2_1", w_slot),
            ("D2_2", w_slot),
            ("D2_3", w_slot),
            ("WC1", w_slot),
            ("WC2", w_slot),
            ("NP9", w_slot),
        ]
        p1 = div1[0].upper()
        p2 = div2[0].upper()
        label_map = {
            "D1_1": f"{p1}1",
            "D1_2": f"{p1}2",
            "D1_3": f"{p1}3",
            "D2_1": f"{p2}1",
            "D2_2": f"{p2}2",
            "D2_3": f"{p2}3",
            "WC1": "7",
            "WC2": "8",
            "NP9": "9+",
        }
        total_w = sum(w for _n, w in cols)

        # Column headers only (top title row removed; titles are drawn above tables).
        hy = y0
        x = x0
        for name, w in cols:
            c.create_rectangle(x, hy, x + w, hy + row_h, fill="#2f2f2f", outline="#3a3a3a")
            c.create_text(x + w / 2, hy + row_h / 2, text=label_map.get(name, name), fill="#f0f0f0", anchor="center")
            x += w

        # Body rows
        y = hy + row_h
        div1_codes = _div_teams(pts, div1, standings)
        div2_codes = _div_teams(pts, div2, standings)
        conf_all_codes = _conf_teams(pts, conf, standings)
        slot_points = _target_points(pts, conf, standings)
        for code in conf_codes:
            p = float(pts.get(code, 0.0))
            # Conservative cache-only GP handling:
            # if GP is missing, assume 0 GP so rivals get maximum possible points.
            # This avoids premature "IN" (clinched-like) outcomes from approximated GP.
            gp = int(gp_map.get(code, 0))
            gp = max(0, min(82, gp))
            gr = max(0, 82 - gp)
            max_pts = p + 2.0 * gr
            max_pts_map: dict[str, float] = {}
            for t in conf_all_codes:
                tp = float(pts.get(t, 0.0))
                tgp = int(gp_map.get(t, 0))
                tgp = max(0, min(82, tgp))
                tgr = max(0, 82 - tgp)
                max_pts_map[t] = tp + 2.0 * tgr
            row_vals: dict[str, str] = {
                "Team": code,
            }

            same_d1 = TEAM_TO_DIV.get(code) == div1
            same_d2 = TEAM_TO_DIV.get(code) == div2
            d1_others = [t for t in div1_codes if t != code]
            d2_others = [t for t in div2_codes if t != code]
            conf_others = [t for t in conf_all_codes if t != code]
            d1_vals = [max_pts_map.get(t, 0.0) for t in d1_others]
            d2_vals = [max_pts_map.get(t, 0.0) for t in d2_others]
            conf_vals = [max_pts_map.get(t, 0.0) for t in conf_others]
            # 9th-place cutoff competitor (others are 15 teams in-conference).
            # If you are above this rival's max possible points, you're truly "IN".
            playoff_cutoff_rival = _kth_highest(conf_vals, 8)
            for slot in ("D1_1", "D1_2", "D1_3"):
                k = 1 if slot.endswith("_1") else 2 if slot.endswith("_2") else 3
                rival_max = _kth_highest(d1_vals, k)
                rival_next = _kth_highest(d1_vals, k + 1)
                row_vals[slot] = (
                    _tragic_cell(
                        p,
                        max_pts,
                        slot_points[slot],
                        rival_max,
                        rival_next,
                        gr,
                        playoff_cutoff_rival,
                    )
                    if tragic
                    else _magic_cell(
                        p,
                        max_pts,
                        slot_points[slot],
                        rival_max,
                        rival_next,
                        gr,
                        playoff_cutoff_rival,
                    )
                ) if same_d1 else "-"
            for slot in ("D2_1", "D2_2", "D2_3"):
                k = 1 if slot.endswith("_1") else 2 if slot.endswith("_2") else 3
                rival_max = _kth_highest(d2_vals, k)
                rival_next = _kth_highest(d2_vals, k + 1)
                row_vals[slot] = (
                    _tragic_cell(
                        p,
                        max_pts,
                        slot_points[slot],
                        rival_max,
                        rival_next,
                        gr,
                        playoff_cutoff_rival,
                    )
                    if tragic
                    else _magic_cell(
                        p,
                        max_pts,
                        slot_points[slot],
                        rival_max,
                        rival_next,
                        gr,
                        playoff_cutoff_rival,
                    )
                ) if same_d2 else "-"
            # PlayoffStatus-like wildcard framing:
            # 7 ~= playoff cut line, 8 ~= next cut line, 9 = non-playoff baseline.
            wc1_rival = _kth_highest(conf_vals, 8)
            wc2_rival = _kth_highest(conf_vals, 9)
            np9_rival = _kth_highest(conf_vals, 10)
            wc1_next = _kth_highest(conf_vals, 9)
            wc2_next = _kth_highest(conf_vals, 10)
            np9_next = _kth_highest(conf_vals, 11)
            row_vals["WC1"] = (
                _tragic_cell(
                    p,
                    max_pts,
                    slot_points["WC1"],
                    wc1_rival,
                    wc1_next,
                    gr,
                    playoff_cutoff_rival,
                )
                if tragic
                else _magic_cell(
                    p,
                    max_pts,
                    slot_points["WC1"],
                    wc1_rival,
                    wc1_next,
                    gr,
                    playoff_cutoff_rival,
                )
            )
            row_vals["WC2"] = (
                _tragic_cell(
                    p,
                    max_pts,
                    slot_points["WC2"],
                    wc2_rival,
                    wc2_next,
                    gr,
                    playoff_cutoff_rival,
                )
                if tragic
                else _magic_cell(
                    p,
                    max_pts,
                    slot_points["WC2"],
                    wc2_rival,
                    wc2_next,
                    gr,
                    playoff_cutoff_rival,
                )
            )
            row_vals["NP9"] = "MW" if tragic else "0"

            x = x0
            for name, wcol in cols:
                val = row_vals.get(name, "")
                c.create_rectangle(x, y, x + wcol, y + row_h, fill="#2a2a2a", outline="#3a3a3a")
                clr = "#f0f0f0"
                if name == "Team":
                    team_code = str(val)
                    img = get_model_logo(
                        team_code,
                        height=max(14, int(round(18 * sf))),
                        logo_bank=logo_bank,
                        league=league,
                        master=c,
                    )
                    if img is not None:
                        live_imgs.append(img)
                        text_w = max(8, 8 * len(team_code))
                        img_w = int(img.width())
                        gap = 4
                        group_w = text_w + gap + img_w
                        start_x = x + (wcol - group_w) / 2
                        c.create_text(start_x, y + row_h / 2, text=team_code, fill=clr, anchor="w")
                        c.create_image(start_x + text_w + gap + img_w / 2, y + row_h / 2, image=img, anchor="center")
                    else:
                        c.create_text(x + wcol / 2, y + row_h / 2, text=team_code, fill=clr, anchor="center")
                else:
                    c.create_text(x + wcol / 2, y + row_h / 2, text=val, fill=clr, anchor="center")
                x += wcol
            y += row_h

        return total_w, (y - y0)

    def redraw() -> None:
        c.delete("all")
        live_imgs.clear()
        try:
            setattr(c, "_logo_refs_magic_tragic", live_imgs)
        except Exception:
            pass
        day = days[state["idx"]]
        date_lbl.configure(text=day.strftime("%-d %B %Y"))
        pts = points_snapshot(df, day)
        tie_for_day = _tie_map(day)
        if not pts:
            c.create_text(30, 30, text="No data for this date", fill="#d0d0d0", anchor="w")
            c.configure(scrollregion=(0, 0, 1400, 300))
            return

        def _scaled_table_width(sf: float) -> int:
            s = max(0.48, min(1.10, float(sf)))
            w_team = max(54, int(round(86 * s)))
            w_slot = max(38, int(round(66 * s)))
            return w_team + (9 * w_slot)

        base_table_w = 86 + (66 * 9)
        gap = 60
        view_w = int(c.winfo_width() or 1400)
        view_h = int(c.winfo_height() or 900)
        total_base = base_table_w * 2 + gap
        scale = min(1.0, max(0.48, float(max(1, view_w - 48)) / float(max(1, total_base))))
        table_w = _scaled_table_width(scale)
        gap = max(26, int(round(gap * scale)))
        if state["mode"] == "both":
            total_w = table_w * 2 + gap
            xL = max(0, int((view_w - total_w) / 2))
            xR = xL + table_w + gap
        else:
            total_w = table_w
            xL = max(0, int((view_w - table_w) / 2))
            xR = xL
        y_top = 34
        if str(league or "NHL").upper() == "NHL":
            c.create_text(
                view_w / 2,
                12,
                text="Tiebreak order: official NHL standings sequence (PTS, ROW, RW, head-to-head where applicable)",
                fill="#b5b5b5",
                anchor="n",
                font=("TkDefaultFont", 9),
            )
            y_top = 48
        if state["mode"] in ("both", "magic"):
            w1, h1 = _table("West", xL, y_top, tragic=False, scale=scale, standings=tie_for_day)
            w2, h2 = _table("East", xR, y_top, tragic=False, scale=scale, standings=tie_for_day)
            c.create_text(
                xL + w1 / 2,
                y_top - 10,
                text="West Magic Numbers",
                fill="#f0f0f0",
                anchor="center",
                font=("TkDefaultFont", 14, "bold"),
            )
            c.create_text(
                xR + w2 / 2,
                y_top - 10,
                text="East Magic Numbers",
                fill="#f0f0f0",
                anchor="center",
                font=("TkDefaultFont", 14, "bold"),
            )
            max_h = max(h1, h2)
            bottom_y = y_top + max_h
        else:
            max_h = 0
            bottom_y = y_top

        if state["mode"] in ("both", "tragic"):
            # Keep panels tighter so both tables fit on-screen more often.
            y2 = y_top + max_h + 44 if state["mode"] == "both" else y_top
            w1, _h1 = _table("West", xL, y2, tragic=True, scale=scale, standings=tie_for_day)
            w2, _h2 = _table("East", xR, y2, tragic=True, scale=scale, standings=tie_for_day)
            bottom_y = max(bottom_y, y2 + max(_h1, _h2))
            c.create_text(
                xL + w1 / 2,
                y2 - 10,
                text="West Tragic Numbers",
                fill="#f0f0f0",
                anchor="center",
                font=("TkDefaultFont", 14, "bold"),
            )
            c.create_text(
                xR + w2 / 2,
                y2 - 10,
                text="East Tragic Numbers",
                fill="#f0f0f0",
                anchor="center",
                font=("TkDefaultFont", 14, "bold"),
            )

        content_w = xL + total_w + 8
        content_h = int(bottom_y + 28)
        # Keep centered; vertical scrolling only when content exceeds viewport height.
        scroll_w = max(view_w, content_w)
        c.configure(
            scrollregion=(0, 0, scroll_w, max(view_h, content_h)),
        )

    def set_idx(i: int) -> None:
        state["idx"] = max(0, min(len(days) - 1, int(i)))
        redraw()

    def toggle_mode(_e=None):
        order = ["both", "magic", "tragic"]
        nxt = order[(order.index(state["mode"]) + 1) % len(order)]
        state["mode"] = nxt
        mode_btn.configure(text=f"Mode: {nxt.capitalize()}")
        redraw()

    prev_btn.bind("<Button-1>", lambda _e: set_idx(state["idx"] - 1))
    next_btn.bind("<Button-1>", lambda _e: set_idx(state["idx"] + 1))
    mode_btn.bind("<Button-1>", toggle_mode)

    def _on_mousewheel(event):
        if getattr(event, "delta", 0) == 0:
            return "break"
        c.yview_scroll(-1 if event.delta > 0 else 1, "units")
        return "break"

    def _on_shift_mousewheel(event):
        # Disable horizontal scrolling on this tab.
        return "break"

    def _on_linux_up(_event):
        c.yview_scroll(-1, "units")
        return "break"

    def _on_linux_down(_event):
        c.yview_scroll(1, "units")
        return "break"

    c.bind("<MouseWheel>", _on_mousewheel)
    c.bind("<Shift-MouseWheel>", _on_shift_mousewheel)
    c.bind("<Button-4>", _on_linux_up)
    c.bind("<Button-5>", _on_linux_down)

    def _on_resize(_evt=None):
        nonlocal resize_after_id
        if resize_after_id is not None:
            try:
                root.after_cancel(resize_after_id)
            except Exception:
                pass
        # Ensure first paint uses real canvas geometry (avoids squished startup).
        resize_after_id = root.after(90, redraw)

    c.bind("<Configure>", _on_resize, add="+")

    def reset() -> None:
        state["idx"] = default_idx
        state["mode"] = "both"
        mode_btn.configure(text="Mode: Both")
        redraw()

    root.after(120, redraw)
    return {"redraw": redraw, "reset": reset}
