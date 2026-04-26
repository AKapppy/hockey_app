from __future__ import annotations

import datetime as dt
import tkinter as tk
import xml.etree.ElementTree as ET
from tkinter import ttk
from typing import Any, Callable

from hockey_app.config import SEASON, TEAM_NAMES, TEAM_TO_CONF, TEAM_TO_DIV
from hockey_app.data.paths import cache_dir
from hockey_app.ui.tabs.models_data import (
    games_played_snapshot,
    load_points_history,
    points_snapshot,
    regular_season_reference_day,
    standings_tiebreak_snapshot,
)
from hockey_app.ui.tabs.models_logos import get_model_logo
from hockey_app.ui.tabs.models_playoff_math import (
    live_playoff_series_probabilities,
    pick_series_winner,
    series_key,
    team_strength_snapshot,
)


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        try:
            return int(float(value))
        except Exception:
            return int(default)


def _team_sort_key(
    code: str,
    pts: dict[str, float],
    standings: dict[str, dict[str, Any]] | None,
    *,
    scope: str,
) -> tuple[Any, ...]:
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
    if 1 <= seq < 900:
        return (0, seq, -pts_v, -row_v, -rw_v, TEAM_NAMES.get(code, code), code)
    return (1, -pts_v, -row_v, -rw_v, TEAM_NAMES.get(code, code), code)


def _sorted_codes(
    codes: list[str],
    pts: dict[str, float],
    standings: dict[str, dict[str, Any]] | None,
    *,
    scope: str,
) -> list[str]:
    return sorted(codes, key=lambda code: _team_sort_key(code, pts, standings, scope=scope))


def _wildcard_columns_snapshot(
    pts: dict[str, float],
    standings: dict[str, dict[str, Any]] | None = None,
) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {k: [] for k in ("Pacific", "Central", "Atlantic", "Metro", "WestWC", "EastWC")}
    for div in ("Pacific", "Central", "Atlantic", "Metro"):
        pool = [c for c in pts if TEAM_TO_DIV.get(c) == div]
        out[div] = _sorted_codes(pool, pts, standings, scope="div")

    west_taken = set(out["Pacific"][:3] + out["Central"][:3])
    east_taken = set(out["Atlantic"][:3] + out["Metro"][:3])

    west_all = _sorted_codes([c for c in pts if TEAM_TO_CONF.get(c) == "West"], pts, standings, scope="conf")
    east_all = _sorted_codes([c for c in pts if TEAM_TO_CONF.get(c) == "East"], pts, standings, scope="conf")

    out["WestWC"] = [c for c in west_all if c not in west_taken]
    out["EastWC"] = [c for c in east_all if c not in east_taken]
    return out


def _conference_bracket_slots(
    pts: dict[str, float],
    standings: dict[str, dict[str, Any]] | None,
    *,
    conference: str,
    layout_divisions: tuple[str, str],
) -> list[str]:
    cols = _wildcard_columns_snapshot(pts, standings)
    first_div = cols.get(layout_divisions[0], [])
    second_div = cols.get(layout_divisions[1], [])
    wc_key = "WestWC" if conference == "West" else "EastWC"
    wildcards = cols.get(wc_key, [])
    better_wc = wildcards[0] if len(wildcards) > 0 else ""
    lesser_wc = wildcards[1] if len(wildcards) > 1 else ""

    division_winners = [codes[0] for codes in (first_div, second_div) if codes]
    ordered_winners = _sorted_codes(division_winners, pts, standings, scope="conf")
    best_div_winner = ordered_winners[0] if ordered_winners else ""

    first_winner = first_div[0] if len(first_div) > 0 else ""
    second_winner = second_div[0] if len(second_div) > 0 else ""
    first_wc = lesser_wc if first_winner and first_winner == best_div_winner else better_wc
    second_wc = lesser_wc if second_winner and second_winner == best_div_winner else better_wc

    return [
        first_winner,
        first_wc,
        first_div[1] if len(first_div) > 1 else "",
        first_div[2] if len(first_div) > 2 else "",
        second_winner,
        second_wc,
        second_div[1] if len(second_div) > 1 else "",
        second_div[2] if len(second_div) > 2 else "",
    ]


def _bracket_snapshot(
    pts: dict[str, float],
    standings: dict[str, dict[str, Any]] | None = None,
) -> dict[str, list[str]]:
    # Match NHL wildcard assignment rules: the stronger division winner in each
    # conference gets the lower-seeded wildcard, regardless of layout order.
    return {
        "West_R1": _conference_bracket_slots(
            pts,
            standings,
            conference="West",
            layout_divisions=("Pacific", "Central"),
        ),
        "East_R1": _conference_bracket_slots(
            pts,
            standings,
            conference="East",
            layout_divisions=("Atlantic", "Metro"),
        ),
    }


def _bracket_snapshot_conf_1v8(
    pts: dict[str, float],
    standings: dict[str, dict[str, Any]] | None = None,
) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for conf in ("West", "East"):
        conf_codes = [c for c in pts if TEAM_TO_CONF.get(c) == conf]
        conf_sorted = _sorted_codes(conf_codes, pts, standings, scope="conf")[:8]
        # 1v8, 4v5, 2v7, 3v6
        pairs = [(0, 7), (3, 4), (1, 6), (2, 5)]
        out[f"{conf}_R1"] = [conf_sorted[i] if i < len(conf_sorted) else "" for a, b in pairs for i in (a, b)]
    return out


def _bracket_snapshot_league_1v16(
    pts: dict[str, float],
    standings: dict[str, dict[str, Any]] | None = None,
) -> dict[str, list[str]]:
    league_sorted = _sorted_codes(list(pts.keys()), pts, standings, scope="league")[:16]
    pairs = [(0, 15), (7, 8), (3, 12), (4, 11), (1, 14), (6, 9), (2, 13), (5, 10)]
    ordered = [league_sorted[i] if i < len(league_sorted) else "" for a, b in pairs for i in (a, b)]
    return {"West_R1": ordered[:8], "East_R1": ordered[8:16]}


def _bracket_snapshot_league_1v8(
    pts: dict[str, float],
    standings: dict[str, dict[str, Any]] | None = None,
) -> dict[str, list[str]]:
    # Standard league seeding for 8-team fields:
    # 1v8, 4v5 on one side; 2v7, 3v6 on the other.
    league_sorted = _sorted_codes(list(pts.keys()), pts, standings, scope="league")[:8]
    pairs = [(0, 7), (3, 4), (1, 6), (2, 5)]
    ordered = [league_sorted[i] if i < len(league_sorted) else "" for a, b in pairs for i in (a, b)]
    return {
        "West_R1": ordered[:4] + ["", "", "", ""],
        "East_R1": ordered[4:8] + ["", "", "", ""],
    }


def _series_wins(
    a: str,
    b: str,
    series_scores: dict[tuple[str, str], dict[str, int]] | None = None,
) -> tuple[int, int]:
    if not a or not b:
        return (0, 0)
    wins = (series_scores or {}).get(series_key(a, b), {})
    return (int(wins.get(a, 0)), int(wins.get(b, 0)))


def _pick_bracket_winner(
    a: str,
    b: str,
    pts: dict[str, float],
    series_scores: dict[tuple[str, str], dict[str, int]] | None = None,
    team_strength: dict[str, float] | None = None,
    live_series_probs: dict[tuple[str, str], dict[str, Any]] | None = None,
) -> str:
    if not a and not b:
        return ""
    if a and not b:
        return a
    if b and not a:
        return b

    a_wins, b_wins = _series_wins(a, b, series_scores)
    if a_wins >= 4 or b_wins >= 4:
        if a_wins == b_wins:
            return a if str(a) <= str(b) else b
        return a if a_wins > b_wins else b

    if team_strength:
        return pick_series_winner(
            a,
            b,
            team_strength=team_strength,
            series_scores=series_scores,
            live_series_probs=live_series_probs,
        )

    pa = float(pts.get(a, 0.0))
    pb = float(pts.get(b, 0.0))
    if pa == pb:
        return a if str(a) <= str(b) else b
    return a if pa > pb else b


def _series_score_snapshot(day: dt.date, *, league: str) -> dict[tuple[str, str], dict[str, int]]:
    if str(league or "").upper() != "NHL":
        return {}
    path = cache_dir() / "online" / "xml" / str(SEASON) / "games.xml"
    if not path.exists():
        return {}
    try:
        root = ET.parse(path).getroot()
    except Exception:
        return {}

    out: dict[tuple[str, str], dict[str, int]] = {}
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
            gid = str(game.get("id") or "").strip()
            game_type = str(game.get("game_type") or game.get("game_type_id") or game.get("game_type_code") or "").strip()
            is_playoff = game_type in {"3", "P"} or gid.startswith("202503")
            if not is_playoff:
                continue
            state = str(game.get("state") or "").upper().strip()
            if state not in {"FINAL", "OFF"} and not state.startswith("FINAL"):
                continue
            away = str(game.get("away_code") or "").upper().strip()
            home = str(game.get("home_code") or "").upper().strip()
            if not away or not home:
                continue
            try:
                away_score = int(str(game.get("away_score") or "0"))
                home_score = int(str(game.get("home_score") or "0"))
            except Exception:
                continue
            if away_score == home_score:
                continue
            winner = away if away_score > home_score else home
            key = series_key(away, home)
            bucket = out.setdefault(key, {away: 0, home: 0})
            bucket.setdefault(away, 0)
            bucket.setdefault(home, 0)
            bucket[winner] = int(bucket.get(winner, 0)) + 1
    return out


def playoff_status_map(
    day: dt.date,
    pts: dict[str, float],
    standings: dict[str, dict[str, Any]] | None = None,
    *,
    league: str = "NHL",
    series_scores: dict[tuple[str, str], dict[str, int]] | None = None,
) -> dict[str, str]:
    league_u = str(league or "NHL").upper()
    if league_u != "NHL" or not pts:
        return {}

    out: dict[str, str] = {}
    seed_day = regular_season_reference_day(day, league=league_u)
    if day > seed_day:
        bracket = _bracket_snapshot(pts, standings)
        field = {
            str(code)
            for code in (bracket.get("West_R1", []) + bracket.get("East_R1", []))
            if str(code or "").strip()
        }
        for code in pts:
            if code not in field:
                out[str(code)] = "eliminated"
    else:
        gp_map = games_played_snapshot(day, league=league_u)
        conf_groups: dict[str, list[str]] = {"East": [], "West": []}
        for code in pts:
            conf = TEAM_TO_CONF.get(code)
            if conf in conf_groups:
                conf_groups[conf].append(str(code))
        for conf_codes in conf_groups.values():
            current_sorted = sorted((float(pts.get(code, 0.0)) for code in conf_codes), reverse=True)
            if len(current_sorted) < 9:
                continue
            for code in conf_codes:
                gp = max(0, min(82, int(gp_map.get(code, 0))))
                conf_seq = int((standings or {}).get(code, {}).get("conferenceSequence") or 999)
                if gp >= 82 and conf_seq > 8:
                    out[str(code)] = "eliminated"
                    continue
                max_pts = float(pts.get(code, 0.0)) + (2.0 * float(82 - gp))
                others = sorted((float(pts.get(other, 0.0)) for other in conf_codes if other != code), reverse=True)
                if len(others) >= 8 and others[7] > (max_pts + 0.1):
                    out[str(code)] = "eliminated"

    for matchup in (series_scores or {}).values():
        if not isinstance(matchup, dict):
            continue
        wins = {str(team): int(total) for team, total in matchup.items()}
        if len(wins) < 2:
            continue
        winner, win_total = max(wins.items(), key=lambda item: item[1])
        if int(win_total) < 4:
            continue
        for team, total in wins.items():
            if team != winner and int(total) < 4:
                out[str(team)] = "eliminated"
    return out


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
        is_eliminated = state_hint == "eliminated"
        if not logos_only:
            fill = "#2a2a2a"
            if state_hint == "clinched":
                fill = "#234123"
            elif state_hint == "eliminated":
                fill = "#3a3a3a"
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
            dim=is_eliminated,
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
                dim=is_eliminated,
            )
        txt_fill = "#9e9e9e" if is_eliminated else "#f0f0f0"
        if logos_only:
            if img is not None:
                live_imgs.append(img)
                canvas.create_image(x + w / 2, y + h / 2, image=img, anchor="center", tags=("bracket_logo",))
            else:
                canvas.create_text(x + w / 2, y + h / 2, text=code, fill=txt_fill, anchor="center", tags=("bracket_logo",))
            return

        if img is not None:
            live_imgs.append(img)
            gap = 4
            img_w = int(img.width())
            txt_w = 8 * len(code)
            group_w = txt_w + gap + img_w
            tx = x + max(2, (w - group_w) / 2)
            canvas.create_text(tx, y + h / 2, text=code, fill=txt_fill, anchor="w", font=("TkDefaultFont", 10, "bold"), tags=("bracket_logo",))
            canvas.create_image(tx + txt_w + gap + img_w / 2, y + h / 2, image=img, anchor="center", tags=("bracket_logo",))
        else:
            canvas.create_text(x + w / 2, y + h / 2, text=code, fill=txt_fill, anchor="center", font=("TkDefaultFont", 10, "bold"), tags=("bracket_logo",))

    def draw_presidents(
        pts: dict[str, float],
        x0: int,
        y0: int,
        states: dict[str, str],
        standings: dict[str, dict[str, Any]] | None,
    ) -> int:
        row_h = 26
        w = 118
        sorted_all = _sorted_codes(list(pts.keys()), pts, standings, scope="league")
        y = y0
        for code in sorted_all[:32]:
            draw_code_cell(x0, y, code, w=w, h=row_h, state_hint=states.get(code, ""))
            hover_cells.append((x0, y, x0 + w, y + row_h, str(code)))
            y += row_h
        return y

    def draw_wildcard(
        pts: dict[str, float],
        x0: int,
        y0: int,
        states: dict[str, str],
        standings: dict[str, dict[str, Any]] | None,
    ) -> int:
        cols = _wildcard_columns_snapshot(pts, standings)
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

    def draw_side_bracket(
        x0: int,
        y0: int,
        teams_r1: list[str],
        *,
        align: str,
        pts: dict[str, float],
        states: dict[str, str],
        series_scores: dict[tuple[str, str], dict[str, int]],
        team_strength: dict[str, float],
        live_series_probs: dict[tuple[str, str], dict[str, Any]],
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

        def _draw_series_number(code: str, opp: str, y_center: float) -> None:
            if not code or not opp:
                return
            wins = series_scores.get(series_key(code, opp), {})
            code_wins = int(wins.get(code, 0))
            opp_wins = int(wins.get(opp, 0))
            color = "#7fdc7f" if code_wins > opp_wins else "#ff7b7b" if code_wins < opp_wins else "#f0f0f0"
            if align == "right":
                x = x_r0 + col_w + 8
                anchor = "w"
            else:
                x = x_r0 - 8
                anchor = "e"
            canvas.create_text(
                x,
                y_center,
                text=str(code_wins),
                fill=color,
                anchor=anchor,
                font=("TkDefaultFont", 18, "bold"),
                tags=("bracket_series_score",),
            )

        for m in range(4):
            y = y0 + m * (pair_h + pair_gap)
            a = teams_r1[m * 2] if m * 2 < len(teams_r1) else ""
            b = teams_r1[m * 2 + 1] if m * 2 + 1 < len(teams_r1) else ""
            r1_pairs.append((a, b))
            draw_code_cell(x_r0, y, a, w=col_w, h=row_h, logos_only=True, state_hint=states.get(a, ""))
            draw_code_cell(x_r0, y + row_h + intra_pair_gap, b, w=col_w, h=row_h, logos_only=True, state_hint=states.get(b, ""))
            yc_a = y + row_h / 2
            yc_b = y + row_h + intra_pair_gap + row_h / 2
            _draw_series_number(a, b, yc_a)
            _draw_series_number(b, a, yc_b)
            pair_centers.append((yc_a, yc_b))
            mids.append((yc_a + yc_b) / 2)

        d = 1 if align == "right" else -1
        x_r1 = x0 + d * (col_w + stage_gap)
        x_r2 = x_r1 + d * (col_w + stage_gap)
        x_r3 = x_r2 + d * (col_w + stage_gap)

        r1_codes = [
            _pick_bracket_winner(r1_pairs[0][0], r1_pairs[0][1], pts, series_scores, team_strength, live_series_probs),
            _pick_bracket_winner(r1_pairs[1][0], r1_pairs[1][1], pts, series_scores, team_strength, live_series_probs),
            _pick_bracket_winner(r1_pairs[2][0], r1_pairs[2][1], pts, series_scores, team_strength, live_series_probs),
            _pick_bracket_winner(r1_pairs[3][0], r1_pairs[3][1], pts, series_scores, team_strength, live_series_probs),
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
            _pick_bracket_winner(r1_codes[0], r1_codes[1], pts, series_scores, team_strength, live_series_probs),
            _pick_bracket_winner(r1_codes[2], r1_codes[3], pts, series_scores, team_strength, live_series_probs),
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

        r3_code = _pick_bracket_winner(r2_codes[0], r2_codes[1], pts, series_scores, team_strength, live_series_probs)
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

    def draw_bracket(
        pts: dict[str, float],
        x0: int,
        y0: int,
        states: dict[str, str],
        series_scores: dict[tuple[str, str], dict[str, int]],
        standings: dict[str, dict[str, Any]] | None,
        team_strength: dict[str, float],
        live_series_probs: dict[tuple[str, str], dict[str, Any]],
    ) -> int:
        mode = mode_var.get()
        if mode == "Conference 1-8":
            b = _bracket_snapshot_conf_1v8(pts, standings)
        elif mode == "League 1-8":
            b = _bracket_snapshot_league_1v8(pts, standings)
        elif mode == "League 1-16":
            b = _bracket_snapshot_league_1v16(pts, standings)
        else:
            b = _bracket_snapshot(pts, standings)
        west = b.get("West_R1", [])
        east = b.get("East_R1", [])
        east_x0 = x0 + 1060
        west_out_x, west_mid_y, west_champ = draw_side_bracket(
            x0,
            y0,
            west,
            align="right",
            pts=pts,
            states=states,
            series_scores=series_scores,
            team_strength=team_strength,
            live_series_probs=live_series_probs,
        )
        east_out_x, east_mid_y, east_champ = draw_side_bracket(
            east_x0,
            y0,
            east,
            align="left",
            pts=pts,
            states=states,
            series_scores=series_scores,
            team_strength=team_strength,
            live_series_probs=live_series_probs,
        )

        cup_cx = int(round((west_out_x + east_out_x) / 2.0))
        cup_final_y = int(round((west_mid_y + east_mid_y) / 2.0))
        # Cup Finals connector: converge to center and drop vertically only.
        canvas.create_line(int(west_out_x), int(west_mid_y), int(cup_cx), int(cup_final_y), fill="#8a8a8a", width=2, tags=("bracket_line",))
        canvas.create_line(int(east_out_x), int(east_mid_y), int(cup_cx), int(cup_final_y), fill="#8a8a8a", width=2, tags=("bracket_line",))

        cup_win = _pick_bracket_winner(west_champ, east_champ, pts, series_scores, team_strength, live_series_probs)
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
        seed_day = regular_season_reference_day(day, league=league_u)
        pts = points_snapshot(points_df, seed_day)
        if not pts:
            canvas.create_text(20, 20, text="No standings data available.", fill="#d0d0d0", anchor="w")
            canvas.configure(scrollregion=(0, 0, 1200, 400))
            return
        standings = standings_tiebreak_snapshot(seed_day) if league_u == "NHL" else {}

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
        series_scores = _series_score_snapshot(day, league=league_u)
        status = playoff_status_map(day, pts, standings, league=league_u, series_scores=series_scores)
        team_strength = team_strength_snapshot(day, league=league_u)
        live_series_probs = live_playoff_series_probabilities(day, season_text=SEASON, league=league_u)
        p_end = draw_presidents(pts, league_x, data_y, status, standings)
        w_end = draw_wildcard(pts, wc_x, data_y, status, standings)
        b_end = draw_bracket(pts, bracket_left, 62, status, series_scores, standings, team_strength, live_series_probs)
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
                pts = points_snapshot(points_df, regular_season_reference_day(d, league=league_u))
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
