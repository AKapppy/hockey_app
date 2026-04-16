from __future__ import annotations

from pathlib import Path
from typing import Callable

import requests


def logo_url(*, team_code: str, canon_team_code: Callable[[str], str], url_base: str) -> str:
    code = canon_team_code(team_code)
    return f"{url_base}{code}.png"


def logo_path(*, team_code: str, canon_team_code: Callable[[str], str], logos_dir: Path) -> Path:
    code = canon_team_code(team_code)
    return logos_dir / f"{code}.png"


def ensure_logo_cached(
    *,
    team_code: str,
    canon_team_code: Callable[[str], str],
    logos_dir: Path,
    url_base: str,
    headers: dict[str, str],
) -> None:
    logos_dir.mkdir(parents=True, exist_ok=True)
    code = canon_team_code(team_code)
    p = logo_path(team_code=code, canon_team_code=canon_team_code, logos_dir=logos_dir)
    if p.exists():
        return
    try:
        r = requests.get(logo_url(team_code=code, canon_team_code=canon_team_code, url_base=url_base), headers=headers, timeout=20)
        r.raise_for_status()
        p.write_bytes(r.content)
    except Exception:
        pass
