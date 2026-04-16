from __future__ import annotations

import os
import time
from dataclasses import dataclass, field


def _enabled_from_env() -> bool:
    v = os.getenv("HOCKEY_PROFILE_STARTUP", "").strip().lower()
    return v in {"1", "true", "yes", "on"}


@dataclass
class StartupProfiler:
    enabled: bool = field(default_factory=_enabled_from_env)
    _t0: float = field(default_factory=time.perf_counter)
    _last: float = field(default_factory=time.perf_counter)
    _rows: list[tuple[str, float]] = field(default_factory=list)

    def mark(self, label: str) -> None:
        if not self.enabled:
            return
        now = time.perf_counter()
        self._rows.append((label, now - self._last))
        self._last = now

    def emit(self, prefix: str = "[startup]") -> None:
        if not self.enabled:
            return
        total = time.perf_counter() - self._t0
        print(f"{prefix} total={total:.3f}s")
        for label, dt_s in self._rows:
            print(f"{prefix} {label}: {dt_s:.3f}s")
