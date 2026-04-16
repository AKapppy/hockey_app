from __future__ import annotations

import os
from pathlib import Path

def base_dir() -> Path:
    """
    Project root: .../hockey_app_folder (the folder that contains /hockey_app).
    """
    return Path(__file__).resolve().parents[2]


def cache_dir() -> Path:
    """
    Central runtime cache location, constrained to project-local paths only.
    Default:
      - <project>/cache
    Optional overrides (only if they resolve inside <project>):
      - HOCKEY_CACHE_DIR
      - HOCKEY_BASE_DIR/cache
    """
    project = base_dir().resolve()

    def _inside_project(p: Path) -> bool:
        try:
            return p.resolve().is_relative_to(project)
        except Exception:
            return False

    override = os.environ.get("HOCKEY_CACHE_DIR", "").strip()
    if override:
        p = Path(override).expanduser()
        if _inside_project(p):
            p.mkdir(parents=True, exist_ok=True)
            return p

    base_override = os.environ.get("HOCKEY_BASE_DIR", "").strip()
    if base_override:
        p = Path(base_override).expanduser() / "cache"
        if _inside_project(p):
            p.mkdir(parents=True, exist_ok=True)
            return p

    p = project / "cache"
    p.mkdir(parents=True, exist_ok=True)
    return p


def online_dir() -> Path:
    p = cache_dir() / "online"
    p.mkdir(parents=True, exist_ok=True)
    return p


def sims_dir(season: str) -> Path:
    p = online_dir() / "moneypuck" / str(season) / "simulations"
    p.mkdir(parents=True, exist_ok=True)
    return p


def nhl_dir(season: str) -> Path:
    p = online_dir() / "nhl" / str(season)
    p.mkdir(parents=True, exist_ok=True)
    return p


def pwhl_dir(season: str) -> Path:
    p = online_dir() / "pwhl" / str(season)
    p.mkdir(parents=True, exist_ok=True)
    return p


def espn_dir(season: str) -> Path:
    p = online_dir() / "espn" / str(season)
    p.mkdir(parents=True, exist_ok=True)
    return p


def logos_dir() -> Path:
    (cache_dir() / "logos").mkdir(parents=True, exist_ok=True)
    return cache_dir() / "logos"


def imgs_dir() -> Path:
    (cache_dir() / "images").mkdir(parents=True, exist_ok=True)
    return cache_dir() / "images"
