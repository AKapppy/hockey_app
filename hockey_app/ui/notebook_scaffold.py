from __future__ import annotations

from dataclasses import dataclass
import tkinter as tk
from tkinter import ttk
from typing import Callable

from hockey_app.ui.style_notebook import apply_ttk_style


@dataclass
class NotebookScaffold:
    root: tk.Tk
    content: tk.Frame
    main_notebook: ttk.Notebook
    scoreboard_page: ttk.Frame
    scoreboard_holder: tk.Frame | None
    pred_notebook: ttk.Notebook
    stats_notebook: ttk.Notebook
    models_notebook: ttk.Notebook
    predictions_page: ttk.Frame
    stats_page: ttk.Frame
    models_page: ttk.Frame
    games_tab: ttk.Frame | None
    games_holder: tk.Frame | None
    team_stats_holder: tk.Frame | None
    team_stats_tab: ttk.Frame | None
    game_stats_holder: tk.Frame | None
    game_stats_tab: ttk.Frame | None
    player_stats_holder: tk.Frame | None
    player_stats_tab: ttk.Frame | None
    goal_diff_holder: tk.Frame | None
    goal_diff_tab: ttk.Frame | None
    points_holder: tk.Frame | None
    points_tab: ttk.Frame | None
    playoff_picture_holder: tk.Frame | None
    playoff_picture_tab: ttk.Frame | None
    magic_tragic_holder: tk.Frame | None
    magic_tragic_tab: ttk.Frame | None
    point_probabilities_holder: tk.Frame | None
    point_probabilities_tab: ttk.Frame | None
    playoff_win_probabilities_holder: tk.Frame | None
    playoff_win_probabilities_tab: ttk.Frame | None
    add_gap_tab: Callable[[ttk.Notebook], None]


def build_notebook_scaffold(*, season: str, dark_window_bg: str) -> NotebookScaffold:
    root = tk.Tk()
    root.title(f"Predictions - {season}")

    apply_ttk_style(root, bg=dark_window_bg)

    root.update_idletasks()
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(f"{sw}x{sh}+0+0")

    root.update_idletasks()
    root.lift()
    try:
        root.attributes("-topmost", True)
        root.after(250, lambda: root.attributes("-topmost", False))
    except Exception:
        pass
    try:
        root.focus_force()
    except Exception:
        pass

    pad = 2

    chrome = tk.Frame(root, bg=dark_window_bg, bd=0, highlightthickness=0)
    chrome.pack(fill="both", expand=True)
    chrome.grid_rowconfigure(0, weight=1)
    chrome.grid_columnconfigure(0, weight=1)

    content = tk.Frame(chrome, bg=chrome["bg"], bd=0, highlightthickness=0)
    content.grid(row=0, column=0, sticky="nsew")
    content.grid_rowconfigure(0, weight=1)
    content.grid_columnconfigure(0, weight=1)
    content.configure(padx=pad, pady=pad)

    notebook_host = ttk.Frame(content, padding=0)
    notebook_host.grid(row=0, column=0, sticky="nsew")
    notebook_host.grid_rowconfigure(0, weight=1)
    notebook_host.grid_columnconfigure(0, weight=1)

    main_notebook = ttk.Notebook(notebook_host, style="NB.TNotebook")
    main_notebook.grid(row=0, column=0, sticky="nsew")

    gap_text = " "
    gap_pad = (2, 3)

    def add_gap_tab(nb: ttk.Notebook) -> None:
        gap = ttk.Frame(nb, padding=0)
        nb.add(gap, text=gap_text)
        nb.tab(gap, state="disabled", padding=gap_pad)

    scoreboard_page = ttk.Frame(main_notebook, padding=0)
    predictions_page = ttk.Frame(main_notebook, padding=0)
    stats_page = ttk.Frame(main_notebook, padding=0)
    models_page = ttk.Frame(main_notebook, padding=0)

    for p in (scoreboard_page, predictions_page, stats_page, models_page):
        p.grid_rowconfigure(0, weight=1)
        p.grid_columnconfigure(0, weight=1)

    predictions_page.grid_rowconfigure(1, weight=0)

    main_notebook.add(scoreboard_page, text="Scoreboard")
    add_gap_tab(main_notebook)
    main_notebook.add(stats_page, text="Stats")
    add_gap_tab(main_notebook)
    main_notebook.add(predictions_page, text="Predictions")
    add_gap_tab(main_notebook)
    main_notebook.add(models_page, text="Models")

    pred_notebook = ttk.Notebook(predictions_page, style="NB.TNotebook")
    pred_notebook.grid(row=0, column=0, sticky="nsew", pady=(0, 0))
    tk.Label(
        predictions_page,
        text="Data collected from MoneyPuck.com",
        bg=dark_window_bg,
        fg="#9a9a9a",
        font=("TkDefaultFont", 9),
        anchor="e",
        padx=8,
        pady=2,
    ).grid(row=1, column=0, sticky="se")

    stats_notebook = ttk.Notebook(stats_page, style="NB.TNotebook")
    stats_notebook.grid(row=0, column=0, sticky="nsew", pady=(0, 0))

    stats_labels: list[str | None] = [
        "Team Stats",
        "Game Stats",
        "Player Stats",
        None,
        "Goal Differential",
        "Points",
    ]

    scoreboard_holder: tk.Frame | None = None
    games_tab: ttk.Frame | None = None
    games_holder: tk.Frame | None = None
    scoreboard_frame = tk.Frame(scoreboard_page, bg=dark_window_bg, bd=0, highlightthickness=0)
    scoreboard_frame.grid(row=0, column=0, sticky="nsew")
    scoreboard_holder = scoreboard_frame

    points_holder: tk.Frame | None = None
    points_tab: ttk.Frame | None = None
    team_stats_holder: tk.Frame | None = None
    team_stats_tab: ttk.Frame | None = None
    game_stats_holder: tk.Frame | None = None
    game_stats_tab: ttk.Frame | None = None
    player_stats_holder: tk.Frame | None = None
    player_stats_tab: ttk.Frame | None = None
    goal_diff_holder: tk.Frame | None = None
    goal_diff_tab: ttk.Frame | None = None

    for label in stats_labels:
        if label is None:
            add_gap_tab(stats_notebook)
            continue

        tab = ttk.Frame(stats_notebook, padding=0)
        tab.grid_rowconfigure(0, weight=1)
        tab.grid_columnconfigure(0, weight=1)
        stats_notebook.add(tab, text=label)

        holder = tk.Frame(tab, bg=dark_window_bg, bd=0, highlightthickness=0)
        holder.grid(row=0, column=0, sticky="nsew")

        if label == "Goal Differential":
            goal_diff_holder = holder
            goal_diff_tab = tab
        if label == "Points":
            points_holder = holder
            points_tab = tab
        if label == "Team Stats":
            team_stats_holder = holder
            team_stats_tab = tab
        if label == "Game Stats":
            game_stats_holder = holder
            game_stats_tab = tab
        if label == "Player Stats":
            player_stats_holder = holder
            player_stats_tab = tab

    models_notebook = ttk.Notebook(models_page, style="NB.TNotebook")
    models_notebook.grid(row=0, column=0, sticky="nsew", pady=(0, 0))
    playoff_picture_holder: tk.Frame | None = None
    playoff_picture_tab: ttk.Frame | None = None
    magic_tragic_holder: tk.Frame | None = None
    magic_tragic_tab: ttk.Frame | None = None
    point_probabilities_holder: tk.Frame | None = None
    point_probabilities_tab: ttk.Frame | None = None
    playoff_win_probabilities_holder: tk.Frame | None = None
    playoff_win_probabilities_tab: ttk.Frame | None = None

    model_labels: list[str | None] = [
        "Playoff Picture",
        None,
        "Magic/Tragic",
        None,
        "Point Probabilities",
        None,
        "Playoff Win Probabilities",
    ]

    for label in model_labels:
        if label is None:
            add_gap_tab(models_notebook)
            continue

        tab = ttk.Frame(models_notebook, padding=0)
        tab.grid_rowconfigure(0, weight=1)
        tab.grid_columnconfigure(0, weight=1)
        models_notebook.add(tab, text=label)

        holder = tk.Frame(tab, bg=dark_window_bg, bd=0, highlightthickness=0)
        holder.grid(row=0, column=0, sticky="nsew")
        if label == "Playoff Picture":
            playoff_picture_holder = holder
            playoff_picture_tab = tab
        if label == "Magic/Tragic":
            magic_tragic_holder = holder
            magic_tragic_tab = tab
        if label == "Point Probabilities":
            point_probabilities_holder = holder
            point_probabilities_tab = tab
        if label == "Playoff Win Probabilities":
            playoff_win_probabilities_holder = holder
            playoff_win_probabilities_tab = tab

    return NotebookScaffold(
        root=root,
        content=content,
        main_notebook=main_notebook,
        scoreboard_page=scoreboard_page,
        scoreboard_holder=scoreboard_holder,
        pred_notebook=pred_notebook,
        stats_notebook=stats_notebook,
        models_notebook=models_notebook,
        predictions_page=predictions_page,
        stats_page=stats_page,
        models_page=models_page,
        games_tab=games_tab,
        games_holder=games_holder,
        team_stats_holder=team_stats_holder,
        team_stats_tab=team_stats_tab,
        game_stats_holder=game_stats_holder,
        game_stats_tab=game_stats_tab,
        player_stats_holder=player_stats_holder,
        player_stats_tab=player_stats_tab,
        goal_diff_holder=goal_diff_holder,
        goal_diff_tab=goal_diff_tab,
        points_holder=points_holder,
        points_tab=points_tab,
        playoff_picture_holder=playoff_picture_holder,
        playoff_picture_tab=playoff_picture_tab,
        magic_tragic_holder=magic_tragic_holder,
        magic_tragic_tab=magic_tragic_tab,
        point_probabilities_holder=point_probabilities_holder,
        point_probabilities_tab=point_probabilities_tab,
        playoff_win_probabilities_holder=playoff_win_probabilities_holder,
        playoff_win_probabilities_tab=playoff_win_probabilities_tab,
        add_gap_tab=add_gap_tab,
    )
