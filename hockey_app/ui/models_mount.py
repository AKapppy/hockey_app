from __future__ import annotations

from tkinter import messagebox
from typing import Callable

from hockey_app.ui.tabs.models_magic_tragic import populate_magic_tragic_tab
from hockey_app.ui.tabs.models_playoff_picture import populate_playoff_picture_tab
from hockey_app.ui.tabs.models_point_probabilities import populate_point_probabilities_tab
from hockey_app.ui.tabs.models_playoff_win_probabilities import populate_playoff_win_probabilities_tab


def mount_playoff_picture_tab(
    holder,
    tab,
    *,
    logo_bank,
    league: str = "NHL",
    get_selected_team_code: Callable[[], str | None],
    set_selected_team_code: Callable[[str | None], None],
    controllers: dict[str, dict[str, Callable[[], None]]],
) -> None:
    try:
        ctrl = populate_playoff_picture_tab(
            holder,
            logo_bank=logo_bank,
            league=league,
            get_selected_team_code=get_selected_team_code,
            set_selected_team_code=set_selected_team_code,
        )
        controllers[str(tab)] = ctrl
    except Exception as e:
        messagebox.showerror("UI Error", f"Failed to render Playoff Picture tab:\n{e}")


def mount_magic_tragic_tab(
    holder,
    tab,
    *,
    logo_bank,
    league: str = "NHL",
    controllers: dict[str, dict[str, Callable[[], None]]],
) -> None:
    try:
        ctrl = populate_magic_tragic_tab(holder, logo_bank=logo_bank, league=league)
        controllers[str(tab)] = ctrl
    except Exception as e:
        messagebox.showerror("UI Error", f"Failed to render Magic/Tragic tab:\n{e}")


def mount_point_probabilities_tab(
    holder,
    tab,
    *,
    logo_bank,
    league: str = "NHL",
    controllers: dict[str, dict[str, Callable[[], None]]],
) -> None:
    try:
        ctrl = populate_point_probabilities_tab(holder, logo_bank=logo_bank, league=league)
        controllers[str(tab)] = ctrl
    except Exception as e:
        messagebox.showerror("UI Error", f"Failed to render Point Probabilities tab:\n{e}")


def mount_playoff_win_probabilities_tab(
    holder,
    tab,
    *,
    logo_bank,
    league: str = "NHL",
    controllers: dict[str, dict[str, Callable[[], None]]],
) -> None:
    try:
        ctrl = populate_playoff_win_probabilities_tab(holder, logo_bank=logo_bank, league=league)
        controllers[str(tab)] = ctrl
    except Exception as e:
        messagebox.showerror("UI Error", f"Failed to render Playoff Win Probabilities tab:\n{e}")
