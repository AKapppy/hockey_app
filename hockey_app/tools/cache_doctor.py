from __future__ import annotations

import argparse
import shutil
from dataclasses import dataclass
from pathlib import Path

from hockey_app.data.paths import cache_dir


@dataclass
class CacheIssue:
    path: Path
    reason: str
    cleanable: bool


def _is_inside(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False


def _size_bytes(path: Path) -> int:
    try:
        if path.is_file():
            return path.stat().st_size
        total = 0
        for p in path.rglob("*"):
            if p.is_file():
                total += p.stat().st_size
        return total
    except Exception:
        return 0


def _fmt_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    val = float(n)
    for unit in ("KB", "MB", "GB", "TB"):
        val /= 1024.0
        if val < 1024.0:
            return f"{val:.1f} {unit}"
    return f"{val:.1f} PB"


def _detect_redundant_paths(cache_root: Path) -> list[CacheIssue]:
    issues: list[CacheIssue] = []

    old_root_entries = (
        "nhl",
        "pwhl",
        "espn",
        "simulations",
        ".migrated_from_legacy",
        ".migrated_online_layout",
    )
    for name in old_root_entries:
        p = cache_root / name
        if p.exists():
            issues.append(
                CacheIssue(
                    path=p,
                    reason="legacy cache layout artifact",
                    cleanable=True,
                )
            )

    # Old migration could have created nested provider folders under online/nhl/<season>.
    nested_provider_names = ("espn", "espn_probe", "pwhl")
    nhl_online = cache_root / "online" / "nhl"
    if nhl_online.exists() and nhl_online.is_dir():
        for season_dir in sorted([p for p in nhl_online.iterdir() if p.is_dir()], key=lambda p: p.name):
            for name in nested_provider_names:
                p = season_dir / name
                if p.exists():
                    issues.append(
                        CacheIssue(
                            path=p,
                            reason="unexpected nested provider directory under online/nhl/<season>",
                            cleanable=True,
                        )
                    )

    allowed_top = {"online", "images", "season_dates.csv", "meta"}
    for p in sorted(cache_root.iterdir(), key=lambda x: x.name):
        if p.name in allowed_top:
            continue
        if p.name.startswith("."):
            issues.append(
                CacheIssue(
                    path=p,
                    reason="unexpected hidden entry at cache root",
                    cleanable=True,
                )
            )
            continue
        issues.append(
            CacheIssue(
                path=p,
                reason="unexpected top-level cache entry",
                cleanable=False,
            )
        )

    dedup: dict[str, CacheIssue] = {}
    for issue in issues:
        key = str(issue.path.resolve())
        if key in dedup:
            continue
        dedup[key] = issue
    return list(dedup.values())


def _remove_path(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def run_cache_doctor(*, clean: bool = False) -> int:
    root = cache_dir()
    issues = _detect_redundant_paths(root)
    issues = sorted(issues, key=lambda x: str(x.path))

    print(f"Cache root: {root}")
    if not issues:
        print("Status: healthy (no redundant/legacy cache paths found).")
        return 0

    cleanable = [i for i in issues if i.cleanable]
    blocked = [i for i in issues if not i.cleanable]

    print(f"Found {len(issues)} issue(s):")
    for idx, issue in enumerate(issues, start=1):
        size = _fmt_size(_size_bytes(issue.path))
        can = "cleanable" if issue.cleanable else "manual-review"
        print(f"{idx}. [{can}] {issue.path} ({size})")
        print(f"   reason: {issue.reason}")

    if clean:
        removed = 0
        for issue in cleanable:
            if not _is_inside(root, issue.path):
                continue
            if not issue.path.exists():
                continue
            _remove_path(issue.path)
            removed += 1
        print(f"Cleanup: removed {removed} path(s).")
    else:
        if cleanable:
            print("Cleanup: run `python3 -m hockey_app cache doctor --clean` to remove cleanable paths.")

    if blocked:
        print("Manual review needed for some paths (not auto-removed).")
    return 0


def cli_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 -m hockey_app cache doctor",
        description="Inspect cache folder for legacy/redundant paths.",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove only paths that are known-safe legacy artifacts.",
    )
    args = parser.parse_args(argv)
    return run_cache_doctor(clean=bool(args.clean))
