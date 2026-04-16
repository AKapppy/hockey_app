from __future__ import annotations

import errno
import importlib.util
import os
import re
import subprocess
import sys
import time
from pathlib import Path

# iCloud-backed folders can intermittently deadlock on import/pyc I/O.
# Disable bytecode writes and allow one short retry for transient EDEADLK.
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
sys.dont_write_bytecode = True


def _load_main():
    try:
        from .app import main

        return main
    except OSError as e:
        if e.errno != errno.EDEADLK:
            raise
        time.sleep(0.25)
        from .app import main

        return main


def _run_cli(argv: list[str]) -> int | None:
    if not argv:
        return None
    if len(argv) >= 2 and argv[0] == "cache" and argv[1] == "doctor":
        from .tools.cache_doctor import cli_main

        return cli_main(argv[2:])
    if argv[0] in {"-h", "--help"}:
        print("Usage:")
        print("  python3 -m hockey_app")
        print("  python3 -m hockey_app cache doctor [--clean]")
        return 0
    return None

if __name__ == "__main__":
    def _parse_requirements(path: Path) -> list[str]:
        requirements: list[str] = []
        for raw in path.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            line = line.split(";", 1)[0].strip()
            if not line:
                continue
            name = re.split(r"[<>=!~\[]", line, maxsplit=1)[0].strip()
            if name:
                requirements.append(name)
        return requirements

    def _module_name_for_dist(dist_name: str) -> str:
        mapping = {
            "pillow": "PIL",
        }
        return mapping.get(dist_name.lower(), dist_name)

    def _ensure_requirements() -> None:
        project_root = Path(__file__).resolve().parents[1]
        req_path = project_root / "requirements.txt"
        if not req_path.exists():
            return
        requirements = _parse_requirements(req_path)
        if not requirements:
            return
        missing = [
            name
            for name in requirements
            if importlib.util.find_spec(_module_name_for_dist(name)) is None
        ]
        if not missing:
            return
        print(
            "Missing required packages: "
            + ", ".join(missing)
            + ". Installing via pip..."
        )
        try:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "-r", str(req_path)],
                check=True,
            )
        except Exception as exc:
            print(f"Failed to install requirements: {exc}", file=sys.stderr)
            sys.exit(1)

    _ensure_requirements()
    rc = _run_cli(sys.argv[1:])
    if rc is None:
        _load_main()()
    else:
        raise SystemExit(int(rc))
