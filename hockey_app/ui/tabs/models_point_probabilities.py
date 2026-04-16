from __future__ import annotations

import datetime as dt
import math
import tkinter as tk
from typing import Any, Callable

from hockey_app.config import TEAM_NAMES
from hockey_app.ui.tabs.models_data import PWHL_TEAM_NAMES, games_played_snapshot, load_points_history, points_snapshot
from hockey_app.ui.tabs.models_logos import get_model_logo


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
    # Match dark-mode style used in other tabs: red -> yellow -> green.
    t = max(0.0, min(1.0, float(t)))
    t = round(t * 31) / 31
    if t <= 0.5:
        u = t / 0.5
        c = _blend("#ff0000", "#ffff00", u)
    else:
        u = (t - 0.5) / 0.5
        c = _blend("#ffff00", "#00ff00", u)
    return _blend(c, "#262626", 0.42)


def _estimate_point_split(point_pct: float) -> tuple[float, float, float]:
    # Per-game point outcomes: 0, 1 (OTL/SOL), 2.
    mu = max(0.0, min(2.0, float(point_pct) * 2.0))
    # Keep a modest 1-point channel so odd totals are reachable.
    p1 = min(0.24, mu * 0.45)
    p2 = (mu - p1) / 2.0
    p2 = max(0.0, min(1.0, p2))
    p0 = 1.0 - p1 - p2
    if p0 < 0.0:
        over = -p0
        p1 = max(0.0, p1 - over)
        p0 = 0.0
    s = p0 + p1 + p2
    if s <= 0.0:
        return (1.0, 0.0, 0.0)
    return (p0 / s, p1 / s, p2 / s)


def _estimate_point_split_from_history(
    row_vals: list[float],
    gp: int,
    point_pct: float,
) -> tuple[float, float, float]:
    # Infer 1-point vs 2-point result rates from observed point jumps.
    if gp <= 0 or len(row_vals) < 2:
        return _estimate_point_split(point_pct)

    one = 0.0
    two = 0.0
    other_pos = 0.0
    prev = row_vals[0]
    for cur in row_vals[1:]:
        d = float(cur) - float(prev)
        prev = cur
        if d <= 0.0:
            continue
        if d < 1.5:
            one += 1.0
        elif d < 2.5:
            two += 1.0
        else:
            other_pos += 1.0

    # Sparse history fallback.
    if (one + two + other_pos) <= 1.0:
        return _estimate_point_split(point_pct)

    p1 = max(0.0, min(1.0, one / float(gp)))
    p2 = max(0.0, min(1.0, (two + other_pos) / float(gp)))
    p0 = max(0.0, 1.0 - p1 - p2)

    # Keep expected points aligned with current point pace.
    target_mu = max(0.0, min(2.0, float(point_pct) * 2.0))
    cur_mu = p1 + 2.0 * p2
    if cur_mu > 0.0:
        scale = target_mu / cur_mu
        p1 *= scale
        p2 *= scale
        p1 = max(0.0, min(1.0, p1))
        p2 = max(0.0, min(1.0 - p1, p2))
        p0 = max(0.0, 1.0 - p1 - p2)

    s = p0 + p1 + p2
    if s <= 0.0:
        return _estimate_point_split(point_pct)
    return (p0 / s, p1 / s, p2 / s)


def _estimate_point_split_pwhl(point_pct: float) -> tuple[float, float, float, float]:
    # PWHL standings points per game outcomes: 0, 1, 2, 3.
    # Keep a compact distribution anchored to point pace.
    mu = max(0.0, min(3.0, float(point_pct) * 3.0))
    p1 = min(0.18, mu * 0.20)
    p2 = min(0.34, mu * 0.30)
    p3 = max(0.0, (mu - p1 - 2.0 * p2) / 3.0)
    p0 = max(0.0, 1.0 - p1 - p2 - p3)
    s = p0 + p1 + p2 + p3
    if s <= 0.0:
        return (1.0, 0.0, 0.0, 0.0)
    return (p0 / s, p1 / s, p2 / s, p3 / s)


def _estimate_point_split_pwhl_from_history(
    row_vals: list[float],
    gp: int,
    point_pct: float,
) -> tuple[float, float, float, float]:
    if gp <= 0 or len(row_vals) < 2:
        return _estimate_point_split_pwhl(point_pct)

    one = 0.0
    two = 0.0
    three = 0.0
    prev = row_vals[0]
    for cur in row_vals[1:]:
        d = float(cur) - float(prev)
        prev = cur
        if d <= 0.0:
            continue
        if d < 1.5:
            one += 1.0
        elif d < 2.5:
            two += 1.0
        else:
            three += 1.0

    if (one + two + three) <= 1.0:
        return _estimate_point_split_pwhl(point_pct)

    p1 = max(0.0, min(1.0, one / float(gp)))
    p2 = max(0.0, min(1.0, two / float(gp)))
    p3 = max(0.0, min(1.0, three / float(gp)))
    p0 = max(0.0, 1.0 - p1 - p2 - p3)

    target_mu = max(0.0, min(3.0, float(point_pct) * 3.0))
    cur_mu = p1 + 2.0 * p2 + 3.0 * p3
    if cur_mu > 0.0:
        scale = target_mu / cur_mu
        p1 = max(0.0, min(1.0, p1 * scale))
        p2 = max(0.0, min(1.0, p2 * scale))
        p3 = max(0.0, min(1.0, p3 * scale))
        p0 = max(0.0, 1.0 - p1 - p2 - p3)
    s = p0 + p1 + p2 + p3
    if s <= 0.0:
        return _estimate_point_split_pwhl(point_pct)
    return (p0 / s, p1 / s, p2 / s, p3 / s)


def _points_distribution(cur_points: int, games_remaining: int, point_pct: float) -> dict[int, float]:
    p0, p1, p2 = _estimate_point_split(point_pct)
    dist: dict[int, float] = {0: 1.0}
    for _ in range(max(0, games_remaining)):
        nxt: dict[int, float] = {}
        for d, pr in dist.items():
            nxt[d] = nxt.get(d, 0.0) + pr * p0
            nxt[d + 1] = nxt.get(d + 1, 0.0) + pr * p1
            nxt[d + 2] = nxt.get(d + 2, 0.0) + pr * p2
        dist = nxt
    return {cur_points + k: v for k, v in dist.items() if v > 0.0}


def _fmt_prob(prob: float) -> str:
    pct = prob * 100.0
    if pct <= 0.0:
        return ""
    if pct < 0.01:
        return "<.01%"
    return f"{pct:.2f}%"


def populate_point_probabilities_tab(
    parent,
    *,
    logo_bank: Any | None = None,
    league: str = "NHL",
) -> dict[str, Callable[[], None]]:
    for child in parent.winfo_children():
        child.destroy()

    root = tk.Frame(parent, bg="#262626", bd=0, highlightthickness=0)
    root.pack(fill="both", expand=True)
    root.grid_rowconfigure(0, weight=0)
    root.grid_rowconfigure(1, weight=1)
    root.grid_rowconfigure(2, weight=0)
    root.grid_columnconfigure(0, weight=0)
    root.grid_columnconfigure(1, weight=1)
    root.grid_columnconfigure(2, weight=0)

    top = tk.Frame(root, bg="#262626")
    top.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(2, 2))
    for c in range(3):
        top.grid_columnconfigure(c, weight=1 if c == 1 else 0)

    prev_btn = tk.Label(top, text="◀", bg="#3a3a3a", fg="#f0f0f0", padx=8, pady=4, cursor="hand2")
    next_btn = tk.Label(top, text="▶", bg="#3a3a3a", fg="#f0f0f0", padx=8, pady=4, cursor="hand2")
    date_lbl = tk.Label(top, text="Loading...", bg="#262626", fg="#f0f0f0", font=("TkDefaultFont", 16, "bold"))
    prev_btn.grid(row=0, column=0, sticky="w", padx=(8, 8))
    date_lbl.grid(row=0, column=1, sticky="n")
    next_btn.grid(row=0, column=2, sticky="e", padx=(0, 8))

    teams_canvas = tk.Canvas(root, bg="#262626", highlightthickness=0)
    data_canvas = tk.Canvas(root, bg="#262626", highlightthickness=0)
    vs = tk.Scrollbar(root, orient="vertical")
    hs = tk.Scrollbar(root, orient="horizontal")

    teams_canvas.grid(row=1, column=0, sticky="nsew")
    data_canvas.grid(row=1, column=1, sticky="nsew")
    vs.grid(row=1, column=2, sticky="ns")
    hs.grid(row=2, column=1, sticky="ew")

    team_w = 116
    cell_w = 52
    row_h = 24

    league_u = str(league or "NHL").upper()
    df, d0, d1 = load_points_history(league=league_u)
    labels: list[dt.date] = []
    cur = d0
    while cur <= d1:
        labels.append(cur)
        cur += dt.timedelta(days=1)
    if not labels:
        labels = [dt.date.today()]

    team_names = PWHL_TEAM_NAMES if league_u == "PWHL" else TEAM_NAMES
    season_games = 30 if league_u == "PWHL" else 82
    _layout_state = {"can_scroll_y": True}
    state = {"sort": "max", "idx": len(labels) - 1}  # max | team
    prob_cache: dict[str, dict[str, Any]] = {}

    def _build_day_probabilities(day: dt.date) -> dict[str, Any]:
        key = day.isoformat()
        hit = prob_cache.get(key)
        if isinstance(hit, dict):
            return hit

        pts = points_snapshot(df, day)
        if not pts:
            out = {"teams": [], "values": [], "row_probs": {}}
            prob_cache[key] = out
            return out

        teams = sorted(list(pts.keys()), key=lambda code: (team_names.get(code, code), code))
        gp_snapshot = games_played_snapshot(day, league=league_u)
        min_target = int(min(pts.values()))
        max_target = 0
        row_probs: dict[str, dict[int, float]] = {}

        for t in teams:
            cur_pts = float(pts[t])
            gp = int(gp_snapshot.get(t, 0))
            if gp <= 0:
                # Safe fallback if GP is unavailable for a team code.
                pace = 1.4 if league_u == "PWHL" else 1.15
                gp = int(round(cur_pts / pace))
                gp = max(0, min(season_games, gp))
            # Guard against stale low GP snapshots producing impossible ceilings.
            max_reasonable_ppg = 2.1 if league_u == "PWHL" else 1.45
            gp_floor = int(math.ceil(cur_pts / max(0.1, max_reasonable_ppg)))
            gp = max(gp, gp_floor)
            gp = max(0, min(season_games, gp))
            gr = max(0, season_games - gp)

            ppg_cap = 3.0 if league_u == "PWHL" else 2.0
            point_pct = max(0.01, min(0.99, cur_pts / float(max(2, ppg_cap * gp))))

            t_min = int(max(0, math.floor(cur_pts)))
            t_max = int(min(season_games * int(ppg_cap), math.floor(cur_pts + ppg_cap * gr)))
            max_target = max(max_target, t_max)

            row_series: list[float] = []
            try:
                row = df.loc[t]
                row_series = [float(v) for v in row.tolist() if v is not None]
            except Exception:
                row_series = []
            dist: dict[int, float] = {int(round(cur_pts)): 1.0}
            if league_u == "PWHL":
                p0, p1, p2, p3 = _estimate_point_split_pwhl_from_history(row_series, gp, point_pct)
                for _ in range(max(0, gr)):
                    nxt: dict[int, float] = {}
                    for cur_total, pr in dist.items():
                        nxt[cur_total] = nxt.get(cur_total, 0.0) + pr * p0
                        nxt[cur_total + 1] = nxt.get(cur_total + 1, 0.0) + pr * p1
                        nxt[cur_total + 2] = nxt.get(cur_total + 2, 0.0) + pr * p2
                        nxt[cur_total + 3] = nxt.get(cur_total + 3, 0.0) + pr * p3
                    dist = nxt
            else:
                p0, p1, p2 = _estimate_point_split_from_history(row_series, gp, point_pct)
                for _ in range(max(0, gr)):
                    nxt = {}
                    for cur_total, pr in dist.items():
                        nxt[cur_total] = nxt.get(cur_total, 0.0) + pr * p0
                        nxt[cur_total + 1] = nxt.get(cur_total + 1, 0.0) + pr * p1
                        nxt[cur_total + 2] = nxt.get(cur_total + 2, 0.0) + pr * p2
                    dist = nxt
            probs = dist
            total = sum(probs.values())
            if total > 0.0:
                probs = {k: v / total for k, v in probs.items()}
            probs = {k: v for k, v in probs.items() if t_min <= k <= t_max}
            row_probs[t] = probs

        values = list(range(min_target, max_target + 1))
        values = [v for v in values if any(row_probs[t].get(v, 0.0) > 0.0 for t in teams)]

        out = {"teams": teams, "values": values, "row_probs": row_probs}
        prob_cache[key] = out
        return out

    def yview(*args):
        if not _layout_state["can_scroll_y"]:
            teams_canvas.yview_moveto(0.0)
            data_canvas.yview_moveto(0.0)
            return
        teams_canvas.yview(*args)
        data_canvas.yview(*args)

    def xview(*args):
        data_canvas.xview(*args)

    vs.config(command=yview)
    hs.config(command=xview)
    teams_canvas.configure(yscrollcommand=vs.set)
    data_canvas.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)

    def _on_mousewheel(event):
        if getattr(event, "delta", 0) == 0:
            return "break"
        units = -1 if event.delta > 0 else 1
        yview("scroll", units, "units")
        return "break"

    def _on_shift_mousewheel(event):
        if getattr(event, "delta", 0) == 0:
            return "break"
        units = -3 if event.delta > 0 else 3
        xview("scroll", units, "units")
        return "break"

    def _on_linux_up(_event):
        yview("scroll", -1, "units")
        return "break"

    def _on_linux_down(_event):
        yview("scroll", 1, "units")
        return "break"

    for w in (teams_canvas, data_canvas):
        w.bind("<MouseWheel>", _on_mousewheel)
        w.bind("<Button-4>", _on_linux_up)
        w.bind("<Button-5>", _on_linux_down)
        w.bind("<Shift-MouseWheel>", _on_shift_mousewheel)

    def _max_prob_target(code: str, row_probs: dict[str, dict[int, float]]) -> int:
        row = row_probs.get(code, {})
        if not row:
            return 0
        # Prefer highest probability; tie-break by higher point total.
        return int(max(row.items(), key=lambda kv: (float(kv[1]), int(kv[0])))[0])

    def _sorted_teams(teams: list[str], row_probs: dict[str, dict[int, float]]) -> list[str]:
        if state["sort"] == "team":
            return sorted(teams, key=lambda t: (team_names.get(t, t), t))
        return sorted(teams, key=lambda t: (-_max_prob_target(t, row_probs), team_names.get(t, t), t))

    def _draw() -> None:
        teams_canvas.delete("all")
        data_canvas.delete("all")
        day = labels[state["idx"]]
        date_lbl.configure(text=f"{day.day} {day.strftime('%B %Y')}")
        snap = _build_day_probabilities(day)
        teams = [str(t) for t in (snap.get("teams") or [])]
        values = [int(v) for v in (snap.get("values") or [])]
        row_probs = snap.get("row_probs") if isinstance(snap.get("row_probs"), dict) else {}
        if not teams or not values or not row_probs:
            data_canvas.create_text(24, 24, text="No points data available for selected date.", fill="#d0d0d0", anchor="w")
            teams_canvas.configure(scrollregion=(0, 0, team_w + 58, 120), width=team_w + 58)
            data_canvas.configure(scrollregion=(0, 0, 1000, 300))
            return
        ordered = _sorted_teams(teams, row_probs)
        teams_canvas._imgs = []  # type: ignore[attr-defined]

        # left headers (both frozen)
        max_w = 58
        teams_canvas.create_rectangle(0, 0, team_w, row_h, fill="#2f2f2f", outline="#3a3a3a")
        teams_canvas.create_text(team_w / 2, row_h / 2, text="Team", fill="#f0f0f0")
        teams_canvas.create_rectangle(team_w, 0, team_w + max_w, row_h, fill="#2f2f2f", outline="#3a3a3a")
        teams_canvas.create_text(team_w + max_w / 2, row_h / 2, text="Pred", fill="#f0f0f0")

        # right point headers
        for j, v in enumerate(values):
            x = j * cell_w
            data_canvas.create_rectangle(x, 0, x + cell_w, row_h, fill="#2f2f2f", outline="#3a3a3a")
            data_canvas.create_text(x + cell_w / 2, row_h / 2, text=str(v), fill="#f0f0f0")

        for i, t in enumerate(ordered):
            y = (i + 1) * row_h
            teams_canvas.create_rectangle(0, y, team_w, y + row_h, fill="#2a2a2a", outline="#3a3a3a")
            teams_canvas.create_rectangle(team_w, y, team_w + max_w, y + row_h, fill="#2a2a2a", outline="#3a3a3a")
            teams_canvas.create_text(team_w + max_w / 2, y + row_h / 2, text=str(_max_prob_target(t, row_probs)), fill="#f0f0f0")

            img = get_model_logo(
                t,
                height=16,
                logo_bank=logo_bank,
                league=league_u,
                master=teams_canvas,
            )
            if img is not None:
                teams_canvas.create_image(team_w / 2 + 18, y + row_h / 2, image=img, anchor="center")
                teams_canvas.create_text(team_w / 2 - 4, y + row_h / 2, text=t, fill="#f0f0f0", anchor="e")
                if not hasattr(teams_canvas, "_imgs"):
                    teams_canvas._imgs = []  # type: ignore[attr-defined]
                teams_canvas._imgs.append(img)  # type: ignore[attr-defined]
            else:
                teams_canvas.create_text(team_w / 2, y + row_h / 2, text=t, fill="#f0f0f0", anchor="center")

            row = row_probs[t]
            row_max = max(row.values()) if row else 0.0
            for j, v in enumerate(values):
                p = row.get(v, 0.0)
                x = j * cell_w
                if p <= 0.0:
                    fill = "#262626"
                    txt = ""
                else:
                    fill = _heat_rank01(p / row_max) if row_max > 0 else _heat_rank01(0.0)
                    txt = _fmt_prob(p)
                data_canvas.create_rectangle(x, y, x + cell_w, y + row_h, fill=fill, outline="#3a3a3a")
                if txt:
                    data_canvas.create_text(x + cell_w / 2, y + row_h / 2, text=txt, fill="#f0f0f0", anchor="center")

        total_h = row_h * (len(teams) + 1)
        teams_canvas.configure(scrollregion=(0, 0, team_w + max_w, total_h), width=team_w + max_w)
        data_canvas.configure(scrollregion=(0, 0, max(1, len(values) * cell_w), total_h))
        data_canvas.update_idletasks()
        view_h = int(data_canvas.winfo_height() or 0)
        _layout_state["can_scroll_y"] = total_h > view_h
        if not _layout_state["can_scroll_y"]:
            teams_canvas.yview_moveto(0.0)
            data_canvas.yview_moveto(0.0)

        # Center fully-contained content for this tab.
        data_canvas.update_idletasks()
        sr = data_canvas.cget("scrollregion")
        try:
            x0, _y0, x1, _y1 = map(float, str(sr).split())
            content_w = max(1.0, x1 - x0)
            view_w = float(max(1, data_canvas.winfo_width()))
            if content_w <= view_w:
                data_canvas.xview_moveto(0.0)
            else:
                data_canvas.xview_moveto(0.5)
        except Exception:
            pass

    def set_idx(i: int) -> None:
        state["idx"] = max(0, min(len(labels) - 1, int(i)))
        _draw()

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

    _draw()

    def redraw() -> None:
        _draw()

    def reset() -> None:
        try:
            teams_canvas.yview_moveto(0.0)
            data_canvas.yview_moveto(0.0)
            state["sort"] = "max"
            set_idx(len(labels) - 1)
        except Exception:
            pass

    def _click_sort_team(_event=None):
        state["sort"] = "team"
        _draw()

    def _click_sort_max(_event=None):
        state["sort"] = "max"
        _draw()

    teams_canvas.bind("<Button-1>", lambda e: (_click_sort_team() if e.x < team_w else _click_sort_max()))

    return {"redraw": redraw, "reset": reset}
