from __future__ import annotations

import math
from pathlib import Path
import tkinter as tk
from typing import Any, Callable, TypeAlias

from hockey_app.domain.colors import _hex_to_rgb

try:
    from PIL import Image, ImageTk  # type: ignore

    PIL_OK = True
except Exception:
    Image = None
    ImageTk = None
    PIL_OK = False

TkImg: TypeAlias = Any
RawImg: TypeAlias = Any


def _apply_dim_rgba(img: RawImg, dim_amt: float) -> RawImg:
    if not PIL_OK:
        return img
    amt = max(0.0, min(1.0, float(dim_amt)))
    if amt >= 0.999:
        return img
    try:
        out = img.copy()
        alpha = out.getchannel("A")
        alpha = alpha.point(lambda px: int(round(float(px) * amt)))
        out.putalpha(alpha)
        return out
    except Exception:
        return img


class LogoBank:
    """
    Loads original PNGs once and returns resized Tk images on demand.
    Uses Pillow if available; otherwise falls back to tk.PhotoImage subsample.
    Also exposes raw aspect ratios so we can size logos without overlap.
    """

    def __init__(
        self,
        root: tk.Tk,
        bg_hex: str,
        *,
        canon_team_code: Callable[[str], str],
        ensure_logo_cached: Callable[[str], None],
        logo_path: Callable[[str], Path],
    ):
        self.root = root
        self.bg_hex = bg_hex
        self._canon_team_code = canon_team_code
        self._ensure_logo_cached = ensure_logo_cached
        self._logo_path = logo_path

        self._raw: dict[str, RawImg] = {}
        self._tk_cache: dict[tuple[str, int, bool, int], TkImg] = {}
        self._ar_cache: dict[str, float] = {}

    def _load_code_if_needed(self, code: str) -> bool:
        code = self._canon_team_code(code)
        if code in self._raw:
            return True
        self._ensure_logo_cached(code)
        p = self._logo_path(code)
        if not p.exists():
            return False
        if PIL_OK:
            try:
                img = Image.open(str(p)).convert("RGBA")  # type: ignore
                self._raw[code] = img
                return True
            except Exception:
                return False
        try:
            img = tk.PhotoImage(master=self.root, file=str(p))
            self._raw[code] = img
            return True
        except Exception:
            return False

    def load_codes(self, codes: list[str]) -> None:
        for c in codes:
            code = self._canon_team_code(c)
            self._load_code_if_needed(code)

    def _get_bg_rgba(self, size: tuple[int, int]):
        r, g, b = _hex_to_rgb(self.bg_hex)
        return Image.new("RGBA", size, (r, g, b, 255))  # type: ignore

    def aspect_ratio(self, code: str) -> float | None:
        code = self._canon_team_code(code)
        if code in self._ar_cache:
            return self._ar_cache[code]
        if not self._load_code_if_needed(code):
            return None
        raw = self._raw.get(code)
        if raw is None:
            return None
        try:
            if PIL_OK:
                w, h = raw.size
            else:
                w, h = raw.width(), raw.height()
            if h <= 0:
                return None
            ar = float(w) / float(h)
            self._ar_cache[code] = ar
            return ar
        except Exception:
            return None

    def get(self, code: str, height: int, dim: bool = False, dim_amt: float = 0.55) -> TkImg | None:
        code = self._canon_team_code(code)
        h = int(max(1, height))
        dim_key = int(round(float(dim_amt) * 100))
        key = (code, h, bool(dim), dim_key)
        if key in self._tk_cache:
            return self._tk_cache[key]

        if not self._load_code_if_needed(code):
            return None
        raw = self._raw.get(code)
        if raw is None:
            return None

        if PIL_OK:
            try:
                w0, h0 = raw.size
                if h0 <= 0:
                    return None
                scale = float(h) / float(h0)
                w = max(1, int(round(w0 * scale)))
                try:
                    resample = Image.Resampling.LANCZOS  # type: ignore
                except Exception:
                    resample = Image.LANCZOS  # type: ignore
                out = raw.resize((w, h), resample=resample)
                if dim:
                    out = _apply_dim_rgba(out, dim_amt)

                tkimg = ImageTk.PhotoImage(out)  # type: ignore
                self._tk_cache[key] = tkimg
                return tkimg
            except Exception:
                return None

        try:
            h0 = raw.height()
            if h0 <= 0:
                return None
            if h0 > h:
                factor = max(1, int(math.ceil(h0 / h)))
                out = raw.subsample(factor)
            else:
                out = raw
            self._tk_cache[key] = out
            return out
        except Exception:
            return None
