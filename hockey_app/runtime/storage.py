from __future__ import annotations

import os
from pathlib import Path


def ensure_dir_writable(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if not path.exists() or not path.is_dir():
        raise RuntimeError(f"Path is not a directory: {path}")
    test_file = path / ".write_test"
    test_file.write_text("ok", encoding="utf-8")
    test_file.unlink()


def pick_base_dir(base_name: str) -> tuple[Path, bool]:
    """Return a project-local base directory and never probe outside the project tree."""
    project_root = Path(__file__).resolve().parents[2]

    def _inside_project(p: Path) -> bool:
        try:
            return p.resolve().is_relative_to(project_root.resolve())
        except Exception:
            return False

    # Explicit override is accepted only when it stays inside the project tree.
    override = os.environ.get("HOCKEY_BASE_DIR", "").strip()
    if override:
        p = Path(override).expanduser()
        if _inside_project(p):
            try:
                ensure_dir_writable(p)
                return p, False
            except Exception:
                pass

    default = project_root / base_name
    ensure_dir_writable(default)
    return default, False
