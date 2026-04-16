from __future__ import annotations

import datetime as dt
import tkinter as tk
from tkinter import ttk
from typing import Any, Callable

from hockey_app.config import TEAM_NAMES, TEAM_TO_CONF, TEAM_TO_DIV
from hockey_app.ui.tabs.models_data import load_points_history, points_snapshot
from hockey_app.ui.tabs.models_logos import get_model_logo


def _wildcard_columns_snapshot(pts: dict[str, float]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {k: [] for k in ("Pacific", "Central", "Atlantic", "Metro", "WestWC", "EastWC")}
    for div in ("Pacific", "Central", "Atlantic", "Metro"):
        pool = [c for c in pts if TEAM_TO_DIV.get(c) == div]
        out[div] = sorted(pool, key=lambda c: (-pts[c], TEAM_NAMES.get(c, c), c))

    west_taken = set(out["Pacific"][:3] + out["Central"][:3])
    east_taken = set(out["Atlantic"][:3] + out["Metro"][:3])

    west_all = sorted([c for c in pts if TEAM_TO_CONF.get(c) == "West"], key=lambda c: (-pts[c], TEAM_NAMES.get(c, c), c))
    east_all = sorted([c for c in pts if TEAM_TO_CONF.get(c) == "East"], key=lambda c: (-pts[c], TEAM_NAMES.get(c, c), c))

    out["WestWC"] = [c for c in west_all if c not in west_taken]
    out["EastWC"] = [c for c in east_all if c not in east_taken]
    return out


def _bracket_snapshot(pts: dict[str, float]) -> dict[str, list[str]]:
    # Rebuild bracket directly from the same divisional + wildcard placement
    # used in the 1st-round standings block so the visual bracket always matches.
    cols = _wildcard_columns_snapshot(pts)
    pac = cols.get("Pacific", [])
    cen = cols.get("Central", [])
    atl = cols.get("Atlantic", [])
    met = cols.get("Metro", [])
    wwc = cols.get("WestWC", [])
    ewc = cols.get("EastWC", [])

    return {
        "West_R1": [
            pac[0] if len(pac) > 0 else "",
            wwc[1] if len(wwc) > 1 else "",
            pac[1] if len(pac) > 1 else "",
            pac[2] if len(pac) > 2 else "",
            cen[0] if len(cen) > 0 else "",
            wwc[0] if len(wwc) > 0 else "",
            cen[1] if len(cen) > 1 else "",
            cen[2] if len(cen) > 2 else "",
        ],
        "East_R1": [
            atl[0] if len(atl) > 0 else "",
            ewc[1] if len(ewc) > 1 else "",
            atl[1] if len(atl) > 1 else "",
            atl[2] if len(atl) > 2 else "",
            met[0] if len(met) > 0 else "",
            ewc[0] if len(ewc) > 0 else "",
            met[1] if len(met) > 1 else "",
            met[2] if len(met) > 2 else "",
        ],
    }


def _bracket_snapshot_conf_1v8(pts: dict[str, float]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for conf in ("West", "East"):
        conf_codes = [c for c in pts if TEAM_TO_CONF.get(c) == conf]
        conf_sorted = sorted(conf_codes, key=lambda c: (-pts[c], TEAM_NAMES.get(c, c), c))[:8]
        # 1v8, 4v5, 2v7, 3v6
        pairs = [(0, 7), (3, 4), (1, 6), (2, 5)]
        out[f"{conf}_R1"] = [conf_sorted[i] if i < len(conf_sorted) else "" for a, b in pairs for i in (a, b)]
    return out


def _bracket_snapshot_league_1v16(pts: dict[str, float]) -> dict[str, list[str]]:
    league_sorted = sorted(pts.keys(), key=lambda c: (-pts[c], TEAM_NAMES.get(c, c), c))[:16]
    pairs = [(0, 15), (7, 8), (3, 12), (4, 11), (1, 14), (6, 9), (2, 13), (5, 10)]
    ordered = [league_sorted[i] if i < len(league_sorted) else "" for a, b in pairs for i in (a, b)]
    return {"West_R1": ordered[:8], "East_R1": ordered[8:16]}


def _bracket_snapshot_league_1v8(pts: dict[str, float]) -> dict[str, list[str]]:
    # Standard league seeding for 8-team fields:
    # 1v8, 4v5 on one side; 2v7, 3v6 on the other.
    league_sorted = sorted(pts.keys(), key=lambda c: (-pts[c], TEAM_NAMES.get(c, c), c))[:8]
    pairs = [(0, 7), (3, 4), (1, 6), (2, 5)]
    ordered = [league_sorted[i] if i < len(league_sorted) else "" for a, b in pairs for i in (a, b)]
    return {
        "West_R1": ordered[:4] + ["", "", "", ""],
        "East_R1": ordered[4:8] + ["", "", "", ""],
    }


def populate_playoff_picture_tab(
    parent,
    *,
    logo_bank: Any,
    league: str = "NHL",
    get_selected_team_code: Callable[[], str | None],
    set_selected_team_code: Callable[[str | None], None],
) -> dict[str, Callable[[], None]]:
    del get_selected_team_code, set_selected_team_code

    for child in parent.winfo_children():
        child.destroy()

    host = tk.Frame(parent, bg="#262626", bd=0, highlightthickness=0)
    host.pack(fill="both", expand=True)
    host.grid_rowconfigure(1, weight=1)
    host.grid_columnconfigure(0, weight=1)

    league_u = str(league or "NHL").upper()
    points_df, d0, d1 = load_points_history(league=league_u)
    labels: list[dt.date] = []
    cur = d0
    while cur <= d1:
        labels.append(cur)
        cur += dt.timedelta(days=1)
    if not labels:
        labels = [dt.date.today()]

    top = tk.Frame(host, bg="#262626")
    top.grid(row=0, column=0, sticky="ew", pady=(2, 2))
    for c in range(3):
        top.grid_columnconfigure(c, weight=1 if c == 1 else 0)

    prev_btn = tk.Label(top, text="◀", bg="#3a3a3a", fg="#f0f0f0", padx=8, pady=4, cursor="hand2")
    next_btn = tk.Label(top, text="▶", bg="#3a3a3a", fg="#f0f0f0", padx=8, pady=4, cursor="hand2")
    date_lbl = tk.Label(top, text="Loading...", bg="#262626", fg="#f0f0f0", font=("TkDefaultFont", 20, "bold"))
    default_mode = "NHL (Divisional)" if league_u == "NHL" else "League 1-8"
    mode_var = tk.StringVar(value=default_mode)
    prev_btn.grid(row=0, column=0, sticky="w", padx=(8, 8))
    date_lbl.grid(row=0, column=1, sticky="n")
    next_btn.grid(row=0, column=2, sticky="e", padx=(0, 8))

    body = tk.Frame(host, bg="#262626")
    body.grid(row=1, column=0, sticky="nsew")
    body.grid_rowconfigure(0, weight=1)
    body.grid_columnconfigure(0, weight=1)

    canvas = tk.Canvas(body, bg="#262626", highlightthickness=0)
    hsb = tk.Scrollbar(body, orient="horizontal", command=canvas.xview)
    vsb = tk.Scrollbar(body, orient="vertical", command=canvas.yview)
    canvas.configure(xscrollcommand=hsb.set, yscrollcommand=vsb.set)
    canvas.grid(row=0, column=0, sticky="nsew")
    vsb.grid(row=0, column=1, sticky="ns")
    hsb.grid(row=1, column=0, sticky="ew")
    mode_values = ["NHL (Divisional)", "Conference 1-8", "League 1-16"] if league_u == "NHL" else ["League 1-8"]
    mode_box = ttk.Combobox(
        canvas,
        textvariable=mode_var,
        values=mode_values,
        state="readonly",
        width=18,
    )

    state = {"idx": len(labels) - 1}
    live_imgs: list[Any] = []
    hover_cells: list[tuple[float, float, float, float, str]] = []
    tip: tk.Toplevel | None = None
    tip_job: str | None = None

    def draw_code_cell(
        x: int,
        y: int,
        code: str,
        *,
        w: int,
        h: int,
        logos_only: bool = False,
        state_hint: str = "",
    ) -> None:
        if not logos_only:
            fill = "#2a2a2a"
            if state_hint == "clinched":
                fill = "#234123"
            elif state_hint == "eliminated":
                fill = "#4a1f1f"
            canvas.create_rectangle(x, y, x + w, y + h, fill=fill, outline="#3a3a3a", tags=("bracket_bg",))
        if not code:
            return
        base_h = max(14, int(h * 0.70))
        # Normalize visual logo area (not just height) so extreme aspect-ratio
        # logos don't look oversized/undersized versus peers.
        probe = get_model_logo(
            code,
            height=base_h,
            logo_bank=logo_bank,
            league=league_u,
            master=canvas,
        )
        img = probe
        if probe is not None:
            ar = float(max(1, int(probe.width()))) / float(max(1, int(probe.height())))
            ar = max(0.45, min(2.60, ar))
            target_ar = 1.30
            adj_h = int(round(base_h * (target_ar / ar) ** 0.5))
            adj_h = max(max(14, int(h * 0.54)), min(int(h * 0.88), adj_h))
            img = get_model_logo(
                code,
                height=adj_h,
                logo_bank=logo_bank,
                league=league_u,
                master=canvas,
            )
        if logos_only:
            if img is not None:
                live_imgs.append(img)
                canvas.create_image(x + w / 2, y + h / 2, image=img, anchor="center", tags=("bracket_logo",))
            else:
                canvas.create_text(x + w / 2, y + h / 2, text=code, fill="#f0f0f0", anchor="center", tags=("bracket_logo",))
            return

        if img is not None:
            live_imgs.append(img)
            gap = 4
            img_w = int(img.width())
            txt_w = 8 * len(code)
            group_w = txt_w + gap + img_w
            tx = x + max(2, (w - group_w) / 2)
            canvas.create_text(tx, y + h / 2, text=code, fill="#f0f0f0", anchor="w", font=("TkDefaultFont", 10, "bold"), tags=("bracket_logo",))
            canvas.create_image(tx + txt_w + gap + img_w / 2, y + h / 2, image=img, anchor="center", tags=("bracket_logo",))
        else:
            canvas.create_text(x + w / 2, y + h / 2, text=code, fill="#f0f0f0", anchor="center", font=("TkDefaultFont", 10, "bold"), tags=("bracket_logo",))

    def draw_presidents(pts: dict[str, float], x0: int, y0: int, states: dict[str, str]) -> int:
        row_h = 26
        w = 118
        sorted_all = sorted(pts.items(), key=lambda kv: (-kv[1], TEAM_NAMES.get(kv[0], kv[0]), kv[0]))
        y = y0
        for code, _v in sorted_all[:32]:
            draw_code_cell(x0, y, code, w=w, h=row_h, state_hint=states.get(code, ""))
            hover_cells.append((x0, y, x0 + w, y + row_h, str(code)))
            y += row_h
        return y

    def draw_wildcard(pts: dict[str, float], x0: int, y0: int, states: dict[str, str]) -> int:
        cols = _wildcard_columns_snapshot(pts)
        row_h = 38
        cw = 104

        for i in range(3):
            y = y0 + i * row_h
            for j, div in enumerate(("Pacific", "Central", "Atlantic", "Metro")):
                code = cols[div][i] if i < len(cols[div]) else ""
                draw_code_cell(x0 + j * cw, y, code, w=cw, h=row_h, state_hint=states.get(code, ""), logos_only=False)
                if code:
                    hover_cells.append((x0 + j * cw, y, x0 + (j + 1) * cw, y + row_h, str(code)))

        # Keep wildcard continuation visually connected to top-3 rows.
        y_wc = y0 + 3 * row_h
        west = cols["WestWC"]
        east = cols["EastWC"]
        n = max(2, len(west), len(east))
        for i in range(n):
            y = y_wc + i * row_h
            w_code = west[i] if i < len(west) else ""
            e_code = east[i] if i < len(east) else ""
            draw_code_cell(x0, y, w_code, w=cw * 2, h=row_h, state_hint=states.get(w_code, ""), logos_only=False)
            draw_code_cell(x0 + cw * 2, y, e_code, w=cw * 2, h=row_h, state_hint=states.get(e_code, ""), logos_only=False)
            if w_code:
                hover_cells.append((x0, y, x0 + cw * 2, y + row_h, str(w_code)))
            if e_code:
                hover_cells.append((x0 + cw * 2, y, x0 + cw * 4, y + row_h, str(e_code)))
            if i == 1:
                canvas.create_line(x0, y + row_h, x0 + cw * 4, y + row_h, fill="#d0d0d0", width=2)
        return y_wc + n * row_h

    def _pick_predicted_winner(a: str, b: str, pts: dict[str, float]) -> str:
        if not a and not b:
            return ""
        if a and not b:
            return a
        if b and not a:
            return b
        pa = float(pts.get(a, 0.0))
        pb = float(pts.get(b, 0.0))
        if pa == pb:
            return a if str(a) <= str(b) else b
        return a if pa > pb else b

    def draw_side_bracket(
        x0: int,
        y0: int,
        teams_r1: list[str],
        *,
        align: str,
        pts: dict[str, float],
        states: dict[str, str],
    ) -> tuple[int, int, str]:
        row_h = 72
        intra_pair_gap = 12
        pair_gap = 18
        pair_h = row_h * 2 + intra_pair_gap
        col_w = 126
        stage_gap = 28
        join_stub = 34
        mids: list[float] = []
        r1_pairs: list[tuple[str, str]] = []
        pair_centers: list[tuple[float, float]] = []

        def _line(x1: float, y1: float, x2: float, y2: float) -> None:
            canvas.create_line(
                int(round(x1)),
                int(round(y1)),
                int(round(x2)),
                int(round(y2)),
                fill="#8a8a8a",
                width=2,
                tags=("bracket_line",),
            )

        def _edge_in(box_x: float) -> float:
            return box_x if align == "right" else box_x + col_w

        def _edge_out(box_x: float) -> float:
            return box_x + col_w if align == "right" else box_x

        # Push first-round team logos slightly outward so the first connector
        # segment is visible beside the logo.
        x_r0 = x0 - (12 if align == "right" else -12)

        for m in range(4):
            y = y0 + m * (pair_h + pair_gap)
            a = teams_r1[m * 2] if m * 2 < len(teams_r1) else ""
            b = teams_r1[m * 2 + 1] if m * 2 + 1 < len(teams_r1) else ""
            r1_pairs.append((a, b))
            draw_code_cell(x_r0, y, a, w=col_w, h=row_h, logos_only=True, state_hint=states.get(a, ""))
            draw_code_cell(x_r0, y + row_h + intra_pair_gap, b, w=col_w, h=row_h, logos_only=True, state_hint=states.get(b, ""))
            yc_a = y + row_h / 2
            yc_b = y + row_h + intra_pair_gap + row_h / 2
            pair_centers.append((yc_a, yc_b))
            mids.append((yc_a + yc_b) / 2)

        d = 1 if align == "right" else -1
        x_r1 = x0 + d * (col_w + stage_gap)
        x_r2 = x_r1 + d * (col_w + stage_gap)
        x_r3 = x_r2 + d * (col_w + stage_gap)

        r1_codes = [
            _pick_predicted_winner(r1_pairs[0][0], r1_pairs[0][1], pts),
            _pick_predicted_winner(r1_pairs[1][0], r1_pairs[1][1], pts),
            _pick_predicted_winner(r1_pairs[2][0], r1_pairs[2][1], pts),
            _pick_predicted_winner(r1_pairs[3][0], r1_pairs[3][1], pts),
        ]
        for i, code in enumerate(r1_codes):
            draw_code_cell(
                x_r1,
                int(mids[i] - row_h / 2),
                code,
                w=col_w,
                h=row_h,
                logos_only=True,
                state_hint=states.get(code, ""),
            )

        team_edge = x_r0 + col_w / 2
        r1_center_x = x_r1 + col_w / 2
        for i, (ya, yb) in enumerate(pair_centers):
            ym = mids[i]
            xj = team_edge + d * join_stub
            _line(team_edge, ya, xj, ya)
            _line(team_edge, yb, xj, yb)
            _line(xj, ya, xj, yb)
            _line(xj, ym, r1_center_x, ym)

        r2_codes = [
            _pick_predicted_winner(r1_codes[0], r1_codes[1], pts),
            _pick_predicted_winner(r1_codes[2], r1_codes[3], pts),
        ]
        mids2: list[float] = []
        for i, code in enumerate(r2_codes):
            yv = (mids[i * 2] + mids[i * 2 + 1]) / 2
            mids2.append(yv)
            draw_code_cell(
                x_r2,
                int(yv - row_h / 2),
                code,
                w=col_w,
                h=row_h,
                logos_only=True,
                state_hint=states.get(code, ""),
            )

        r1_center_x = x_r1 + col_w / 2
        r2_center_x = x_r2 + col_w / 2
        for i in range(2):
            ya = mids[i * 2]
            yb = mids[i * 2 + 1]
            ym = mids2[i]
            xj = _edge_out(x_r1) + d * join_stub
            _line(r1_center_x, ya, xj, ya)
            _line(r1_center_x, yb, xj, yb)
            _line(xj, ya, xj, yb)
            _line(xj, ym, r2_center_x, ym)

        r3_code = _pick_predicted_winner(r2_codes[0], r2_codes[1], pts)
        sm = (mids2[0] + mids2[1]) / 2
        draw_code_cell(
            x_r3,
            int(sm - row_h / 2),
            r3_code,
            w=col_w,
            h=row_h,
            logos_only=True,
            state_hint=states.get(r3_code, ""),
        )

        r2_center_x = x_r2 + col_w / 2
        r3_center_x = x_r3 + col_w / 2
        xj = _edge_out(x_r2) + d * join_stub
        _line(r2_center_x, mids2[0], xj, mids2[0])
        _line(r2_center_x, mids2[1], xj, mids2[1])
        _line(xj, mids2[0], xj, mids2[1])
        _line(xj, sm, r3_center_x, sm)
        return int(_edge_out(x_r3)), int(sm), r3_code

    def _status_map(_pts: dict[str, float]) -> dict[str, str]:
        # Keep neutral until solver-backed clinch/elimination is wired from Magic/Tragic.
        return {}

    def draw_bracket(pts: dict[str, float], x0: int, y0: int, states: dict[str, str]) -> int:
        mode = mode_var.get()
        if mode == "Conference 1-8":
            b = _bracket_snapshot_conf_1v8(pts)
        elif mode == "League 1-8":
            b = _bracket_snapshot_league_1v8(pts)
        elif mode == "League 1-16":
            b = _bracket_snapshot_league_1v16(pts)
        else:
            b = _bracket_snapshot(pts)
        west = b.get("West_R1", [])
        east = b.get("East_R1", [])
        east_x0 = x0 + 1060
        west_out_x, west_mid_y, west_champ = draw_side_bracket(x0, y0, west, align="right", pts=pts, states=states)
        east_out_x, east_mid_y, east_champ = draw_side_bracket(east_x0, y0, east, align="left", pts=pts, states=states)

        cup_cx = int(round((west_out_x + east_out_x) / 2.0))
        cup_final_y = int(round((west_mid_y + east_mid_y) / 2.0))
        # Cup Finals connector: converge to center and drop vertically only.
        canvas.create_line(int(west_out_x), int(west_mid_y), int(cup_cx), int(cup_final_y), fill="#8a8a8a", width=2, tags=("bracket_line",))
        canvas.create_line(int(east_out_x), int(east_mid_y), int(cup_cx), int(cup_final_y), fill="#8a8a8a", width=2, tags=("bracket_line",))

        cup_win = _pick_predicted_winner(west_champ, east_champ, pts)
        cup_w = 286
        cup_h = 180
        cup_cy = int(cup_final_y + 178)
        canvas.create_line(cup_cx, int(cup_final_y), cup_cx, int(cup_cy - cup_h / 2), fill="#8a8a8a", width=2, tags=("bracket_line",))
        draw_code_cell(
            int(cup_cx - cup_w / 2),
            int(cup_cy - cup_h / 2),
            cup_win,
            w=cup_w,
            h=cup_h,
            logos_only=True,
            state_hint=states.get(cup_win, ""),
        )
        canvas.tag_raise("bracket_logo")

        return int(cup_cy + cup_h / 2 + 36)

    def redraw() -> None:
        live_imgs.clear()
        canvas.delete("all")
        hover_cells.clear()
        day = labels[state["idx"]]
        date_lbl.configure(text=f"{day.day} {day.strftime('%B %Y')}")
        pts = points_snapshot(points_df, day)
        if not pts:
            canvas.create_text(20, 20, text="No standings data available.", fill="#d0d0d0", anchor="w")
            canvas.configure(scrollregion=(0, 0, 1200, 400))
            return

        league_x = 24
        league_w = 118
        wc_x = 164
        wc_w = 104 * 4
        top_y = 8
        standings_left = float(league_x)
        standings_right = float(wc_x + wc_w)
        standings_center = (standings_left + standings_right) / 2.0
        canvas.create_text(standings_center, top_y, text="Standings", fill="#f0f0f0", font=("TkDefaultFont", 17, "bold"), anchor="n")
        # Mode selector inline with top header, centered over full bracket width.
        bracket_w = 1240
        view_w = int(canvas.winfo_width() or 1700)
        # Right-anchor bracket block while preserving wildcard spacing.
        bracket_left = max(int(wc_x + wc_w + 24), int(view_w - bracket_w - 2))
        bracket_right = bracket_left + bracket_w
        bracket_center = (bracket_left + bracket_right) / 2.0
        canvas.create_window(
            bracket_center,
            top_y + 1,
            window=mode_box,
            anchor="n",
        )
        canvas.create_text(league_x + league_w / 2, top_y + 24, text="League", fill="#d0d0d0", font=("TkDefaultFont", 11, "bold"), anchor="n")
        canvas.create_text(wc_x + wc_w / 2, top_y + 24, text="Wildcard", fill="#d0d0d0", font=("TkDefaultFont", 11, "bold"), anchor="n")

        data_y = top_y + 46
        status = _status_map(pts)
        p_end = draw_presidents(pts, league_x, data_y, status)
        w_end = draw_wildcard(pts, wc_x, data_y, status)
        b_end = draw_bracket(pts, bracket_left, 62, status)
        bottom = max(p_end, w_end, b_end) + 24
        canvas.configure(scrollregion=(0, 0, max(1700, bracket_right + 2), max(980, bottom)))

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

        tip_job = parent.after(650, _show)

    def _on_motion(event):
        x = float(canvas.canvasx(event.x))
        y = float(canvas.canvasy(event.y))
        hit = ""
        for x0, y0, x1, y1, code in hover_cells:
            if x0 <= x <= x1 and y0 <= y <= y1:
                d = labels[state["idx"]]
                pts = points_snapshot(points_df, d)
                p = float(pts.get(code, 0.0))
                hit = f"{TEAM_NAMES.get(code, code)} ({code})\nPoints: {int(round(p))}"
                break
        if hit:
            _schedule_tip(hit, int(event.x_root), int(event.y_root))
        else:
            _cancel_tip_job()
            _hide_tip()

    def _on_leave(_event=None):
        _cancel_tip_job()
        _hide_tip()

    def set_idx(i: int) -> None:
        state["idx"] = max(0, min(len(labels) - 1, int(i)))
        redraw()

    hold_job = None
    hold_delta = 0

    def _hold_stop(_event=None):
        nonlocal hold_job
        if hold_job is not None:
            try:
                parent.after_cancel(hold_job)
            except Exception:
                pass
        hold_job = None

    def _hold_tick():
        nonlocal hold_job
        if hold_job is None:
            return
        set_idx(state["idx"] + hold_delta)
        hold_job = parent.after(90, _hold_tick)

    def _hold_start(delta: int):
        nonlocal hold_job, hold_delta
        hold_delta = delta
        set_idx(state["idx"] + delta)
        _hold_stop()
        hold_job = parent.after(1000, _hold_tick)

    prev_btn.bind("<ButtonPress-1>", lambda _e: (_hold_start(-1), "break")[1])
    prev_btn.bind("<ButtonRelease-1>", _hold_stop, add="+")
    prev_btn.bind("<Leave>", _hold_stop, add="+")
    next_btn.bind("<ButtonPress-1>", lambda _e: (_hold_start(1), "break")[1])
    next_btn.bind("<ButtonRelease-1>", _hold_stop, add="+")
    next_btn.bind("<Leave>", _hold_stop, add="+")
    mode_box.bind("<<ComboboxSelected>>", lambda _e: redraw())
    canvas.bind("<Motion>", _on_motion)
    canvas.bind("<Leave>", _on_leave)

    def reset() -> None:
        set_idx(len(labels) - 1)

    redraw()
    return {"redraw": redraw, "reset": reset}
