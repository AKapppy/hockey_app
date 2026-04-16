from __future__ import annotations

import tkinter as tk
from typing import Any, Callable, Literal, TypeAlias

Anchor: TypeAlias = Literal["nw", "n", "ne", "w", "center", "e", "sw", "s", "se"]
Compound: TypeAlias = Literal["top", "left", "center", "right", "bottom", "none"]
TakeFocus: TypeAlias = bool | Callable[[str], bool | None] | Literal[0, 1, ""]

_BTN_UNSET = object()


class FlatButton(tk.Frame):
    def __init__(
        self,
        parent: tk.Misc,
        *,
        text: str = "",
        image: Any = None,
        command=None,
        bg: str = "#333333",
        fg: str = "#ffffff",
        hover_bg: str = "#444444",
        padx: int = 10,
        pady: int = 6,
        anchor: Anchor = "w",
        takefocus: TakeFocus = 0,
    ):
        super().__init__(parent, bg=bg, bd=0, highlightthickness=0, takefocus=takefocus)
        self._bg = bg
        self._hover_bg = hover_bg
        self._command = command
        self._image_ref = image

        self.label = tk.Label(
            self,
            text=text,
            image=image if image else "",
            compound="left" if image else "none",
            bg=bg,
            fg=fg,
            bd=0,
            highlightthickness=0,
            padx=padx,
            pady=pady,
            anchor=anchor,
        )
        self.label.pack(fill="both", expand=True)

        def set_bg(c: str):
            self.configure(bg=c)
            self.label.configure(bg=c)

        def on_enter(_e=None):
            set_bg(self._hover_bg)

        def on_leave(_e=None):
            set_bg(self._bg)

        def on_click(_e=None):
            if callable(self._command):
                self._command()

        for w in (self, self.label):
            w.bind("<Enter>", on_enter)
            w.bind("<Leave>", on_leave)
            w.bind("<Button-1>", on_click)

    def set(self, *, text: str | None = None, image: Any = _BTN_UNSET, compound: Compound | None = None):
        if text is not None:
            self.label.configure(text=text)
        if image is not _BTN_UNSET:
            if image is None:
                self.label.configure(image="")
                self._image_ref = None
            else:
                self.label.configure(image=image)
                self._image_ref = image
        if compound is not None:
            self.label.configure(compound=compound)

    def set_command(self, command):
        self._command = command
