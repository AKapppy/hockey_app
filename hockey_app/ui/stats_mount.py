from __future__ import annotations

from tkinter import messagebox
from typing import Any, Callable

from hockey_app.ui.tabs.goal_differential import populate_goal_differential_tab
from hockey_app.ui.tabs.game_stats import populate_game_stats_tab
from hockey_app.ui.tabs.games_host import populate_games_tab
from hockey_app.ui.tabs.player_stats import populate_player_stats_tab
from hockey_app.ui.tabs.points import populate_points_tab
from hockey_app.ui.tabs.team_stats import populate_team_stats_tab


def mount_games_tab(
    games_holder,
    logo_bank,
    *,
    team_names: dict[str, str],
    dark_window_bg: str,
    dark_canvas_bg: str,
    dark_hilite: str,
    on_data_refresh: Callable[[], None] | None = None,
) -> None:
    populate_games_tab(
        games_holder,
        logo_bank,
        team_names=team_names,
        bg=dark_window_bg,
        card_bg=dark_canvas_bg,
        accent=dark_hilite,
        on_data_refresh=on_data_refresh,
    )


def mount_points_tab(
    points_holder,
    points_tab,
    *,
    logo_bank,
    team_colors: dict[str, str],
    team_col_width: int,
    cell_width: int,
    league: str,
    get_selected_team_code: Callable[[], str | None],
    set_selected_team_code: Callable[[str | None], None],
    render_heatmap_with_graph: Callable[..., dict[str, Callable[[], None]]],
    controllers: dict[str, dict[str, Callable[[], None]]],
) -> None:
    try:
        ctrl_points = populate_points_tab(
            points_holder,
            logo_bank,
            team_colors=team_colors,
            team_col_width=team_col_width,
            cell_width=cell_width,
            league=league,
            get_selected_team_code=get_selected_team_code,
            set_selected_team_code=set_selected_team_code,
            render_heatmap_with_graph=render_heatmap_with_graph,
        )
        controllers[str(points_tab)] = ctrl_points
    except Exception as e:
        messagebox.showerror("UI Error", f"Failed to render Points tab:\n{e}")


def mount_goal_differential_tab(
    goal_diff_holder,
    goal_diff_tab,
    *,
    logo_bank,
    team_colors: dict[str, str],
    team_col_width: int,
    cell_width: int,
    league: str,
    get_selected_team_code: Callable[[], str | None],
    set_selected_team_code: Callable[[str | None], None],
    render_heatmap_with_graph: Callable[..., dict[str, Callable[[], None]]],
    controllers: dict[str, dict[str, Callable[[], None]]],
) -> None:
    try:
        ctrl_goal_diff = populate_goal_differential_tab(
            goal_diff_holder,
            logo_bank,
            team_colors=team_colors,
            team_col_width=team_col_width,
            cell_width=cell_width,
            league=league,
            get_selected_team_code=get_selected_team_code,
            set_selected_team_code=set_selected_team_code,
            render_heatmap_with_graph=render_heatmap_with_graph,
        )
        controllers[str(goal_diff_tab)] = ctrl_goal_diff
    except Exception as e:
        messagebox.showerror("UI Error", f"Failed to render Goal Differential tab:\n{e}")


def mount_team_stats_tab(
    team_stats_holder,
    team_stats_tab,
    *,
    logo_bank=None,
    team_colors: dict[str, str] | None = None,
    team_col_width: int | None = None,
    cell_width: int | None = None,
    league: str,
    get_selected_team_code: Callable[[], str | None],
    set_selected_team_code: Callable[[str | None], None],
    render_heatmap_with_graph: Callable[..., dict[str, Callable[[], None]]] | None = None,
    controllers: dict[str, dict[str, Callable[[], None]]],
) -> None:
    try:
        ctrl = populate_team_stats_tab(
            team_stats_holder,
            league=league,
            get_selected_team_code=get_selected_team_code,
            set_selected_team_code=set_selected_team_code,
            logo_bank=logo_bank,
        )
        controllers[str(team_stats_tab)] = ctrl
    except Exception as e:
        messagebox.showerror("UI Error", f"Failed to render Team Stats tab:\n{e}")


def mount_game_stats_tab(
    game_stats_holder,
    game_stats_tab,
    *,
    logo_bank=None,
    team_colors: dict[str, str] | None = None,
    team_col_width: int | None = None,
    cell_width: int | None = None,
    league: str,
    get_selected_team_code: Callable[[], str | None],
    set_selected_team_code: Callable[[str | None], None],
    render_heatmap_with_graph: Callable[..., dict[str, Callable[[], None]]] | None = None,
    controllers: dict[str, dict[str, Callable[[], None]]],
) -> None:
    try:
        ctrl = populate_game_stats_tab(
            game_stats_holder,
            league=league,
            get_selected_team_code=get_selected_team_code,
            set_selected_team_code=set_selected_team_code,
            logo_bank=logo_bank,
        )
        controllers[str(game_stats_tab)] = ctrl
    except Exception as e:
        messagebox.showerror("UI Error", f"Failed to render Game Stats tab:\n{e}")


def mount_player_stats_tab(
    player_stats_holder,
    player_stats_tab,
    *,
    logo_bank=None,
    league: str,
    get_selected_team_code: Callable[[], str | None],
    set_selected_team_code: Callable[[str | None], None],
    controllers: dict[str, dict[str, Callable[[], None]]],
) -> None:
    try:
        ctrl = populate_player_stats_tab(
            player_stats_holder,
            league=league,
            logo_bank=logo_bank,
            get_selected_team_code=get_selected_team_code,
            set_selected_team_code=set_selected_team_code,
        )
        controllers[str(player_stats_tab)] = ctrl
    except Exception as e:
        messagebox.showerror("UI Error", f"Failed to render Player Stats tab:\n{e}")
