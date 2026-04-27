from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import tkinter as tk

try:
    from PIL import Image, ImageTk  # type: ignore
    _PIL_OK = True
except Exception:
    Image = None  # type: ignore[assignment]
    ImageTk = None  # type: ignore[assignment]
    _PIL_OK = False


PWHL_LOGOS_DIR = Path(__file__).resolve().parents[2] / "assets" / "pwhl_logos"
_PWHL_IMG_CACHE: dict[tuple[str, int], Any] = {}


def _norm_pwhl_code(code: str) -> str:
    c = str(code or "").strip().upper()
    aliases = {"MON": "MTL", "NYC": "NY"}
    return aliases.get(c, c)


def _pwhl_logo_paths(code: str) -> list[Path]:
    c = _norm_pwhl_code(code)
    candidates = [c, c.lower()]
    team_name_aliases: dict[str, tuple[str, ...]] = {
        "BOS": ("boston", "fleet", "boston_fleet"),
        "MIN": ("minnesota", "frost", "minnesota_frost"),
        "MTL": ("montreal", "victoire", "montreal_victoire", "montreal_victorie", "mon"),
        "NY": ("new_york", "sirens", "new_york_sirens", "ny_sirens"),
        "OTT": ("ottawa", "charge", "ottawa_charge"),
        "TOR": ("toronto", "sceptres", "toronto_sceptres"),
        "VAN": ("vancouver", "goldeneyes", "vancouver_goldeneyes"),
        "SEA": ("seattle", "torrent", "seattle_torrent"),
    }
    candidates.extend(team_name_aliases.get(c, ()))
    return [PWHL_LOGOS_DIR / f"{name}.png" for name in candidates]


def _pwhl_logo_get(code: str, *, height: int, master: tk.Misc) -> Any:
    c = _norm_pwhl_code(code)
    h = int(max(1, height))
    key = (c, h)
    if key in _PWHL_IMG_CACHE:
        return _PWHL_IMG_CACHE[key]

    for p in _pwhl_logo_paths(c):
        if not p.exists():
            continue
        try:
            if _PIL_OK:
                pil = Image.open(str(p)).convert("RGBA")  # type: ignore[union-attr]
                w0, h0 = pil.size
                if h0 > 0:
                    scale = float(h) / float(h0)
                    w = max(1, int(round(w0 * scale)))
                    try:
                        resample = Image.Resampling.LANCZOS  # type: ignore[attr-defined,union-attr]
                    except Exception:
                        resample = Image.LANCZOS  # type: ignore[attr-defined,union-attr]
                    pil = pil.resize((w, h), resample=resample)
                img = ImageTk.PhotoImage(pil)  # type: ignore[union-attr]
            else:
                img = tk.PhotoImage(master=master, file=str(p))
                h0 = int(img.height())
                if h0 > h and h0 > 0:
                    factor = max(1, int(math.ceil(h0 / h)))
                    img = img.subsample(factor)
            _PWHL_IMG_CACHE[key] = img
            return img
        except Exception:
            continue
    return None


def get_model_logo(
    code: str,
    *,
    height: int,
    logo_bank: Any | None,
    league: str,
    master: tk.Misc,
    dim: bool = False,
) -> Any:
    league_u = str(league or "NHL").upper().strip()
    if league_u == "PWHL":
        return _pwhl_logo_get(code, height=height, master=master)
    if logo_bank is None:
        return None
    try:
        return logo_bank.get(code, height=height, dim=bool(dim), dim_amt=0.50)
    except Exception:
        return None
