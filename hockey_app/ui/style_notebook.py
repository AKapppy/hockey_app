from __future__ import annotations

import tkinter as tk
from tkinter import ttk


def apply_ttk_style(root: tk.Tk, *, bg: str) -> None:
    style = ttk.Style(root)

    root.configure(bg=bg)

    tab_bg = "#2c2c2c"
    tab_sel = "#333333"
    fg = "#f0f0f0"

    # Aggressive: tighten everything around the tab bars
    tab_margins = (0, 0, 0, 0)  # left, top, right, bottom
    tab_padding = (7, 2)  # x, y  (controls tab height)

    try:
        style.configure("TFrame", background=bg)

        # Base notebook
        style.configure(
            "TNotebook",
            tabmargins=tab_margins,
            background=bg,
            borderwidth=0,
        )
        style.configure(
            "TNotebook.Tab",
            padding=tab_padding,
            background=tab_bg,
            foreground=fg,
            borderwidth=0,
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", tab_sel), ("!selected", tab_bg)],
            foreground=[("selected", fg), ("!selected", fg)],
        )

        # Custom notebook style (used everywhere)
        style.configure(
            "NB.TNotebook",
            tabmargins=tab_margins,
            background=bg,
            borderwidth=0,
        )
        style.configure(
            "NB.TNotebook.Tab",
            padding=tab_padding,
            background=tab_bg,
            foreground=fg,
            borderwidth=0,
        )
        style.map(
            "NB.TNotebook.Tab",
            background=[("selected", tab_sel), ("!selected", tab_bg)],
            foreground=[("selected", fg), ("!selected", fg)],
        )

        style.configure("TButton", padding=(8, 3))
    except Exception:
        pass
