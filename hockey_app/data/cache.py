from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


@dataclass
class CacheStore:
    """
    Simple disk cache with TTL.
    Stores:
      - JSON: <key>.json
      - bytes: <key>.bin + <key>.meta.json
    """
    root: Path

    def __post_init__(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def _path_for(self, key: str, ext: str) -> Path:
        h = _sha(key)
        sub = self.root / h[:2] / h[2:4]
        sub.mkdir(parents=True, exist_ok=True)
        return sub / f"{h}{ext}"

    # ---------- JSON ----------
    def get_json_with_meta(
        self,
        key: str,
        *,
        ttl_seconds: Optional[int] = None,
    ) -> tuple[Optional[Any], Optional[float]]:
        p = self._path_for(key, ".json")
        if not p.exists():
            return None, None
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
            ts = float(obj.get("_ts", 0.0))
            if ttl_seconds is not None and (time.time() - ts) > float(ttl_seconds):
                return None, ts
            return obj.get("data", None), ts
        except Exception:
            return None, None

    def get_json(self, key: str, *, ttl_seconds: Optional[int] = None) -> Optional[Any]:
        data, _ts = self.get_json_with_meta(key, ttl_seconds=ttl_seconds)
        return data

    def set_json(self, key: str, data: Any) -> None:
        p = self._path_for(key, ".json")
        payload = {"_ts": time.time(), "data": data}
        p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def get_or_set_json(
        self,
        key: str,
        fetch_fn: Callable[[], Any],
        *,
        ttl_seconds: Optional[int] = None,
    ) -> Any:
        hit = self.get_json(key, ttl_seconds=ttl_seconds)
        if hit is not None:
            return hit
        data = fetch_fn()
        self.set_json(key, data)
        return data

    # ---------- BYTES ----------
    def get_bytes(self, key: str, *, ttl_seconds: Optional[int] = None) -> Optional[bytes]:
        binp = self._path_for(key, ".bin")
        metap = self._path_for(key, ".meta.json")
        if not binp.exists() or not metap.exists():
            return None
        try:
            meta = json.loads(metap.read_text(encoding="utf-8"))
            ts = float(meta.get("_ts", 0.0))
            if ttl_seconds is not None and (time.time() - ts) > float(ttl_seconds):
                return None
            return binp.read_bytes()
        except Exception:
            return None

    def set_bytes(self, key: str, data: bytes) -> None:
        binp = self._path_for(key, ".bin")
        metap = self._path_for(key, ".meta.json")
        binp.write_bytes(data)
        metap.write_text(json.dumps({"_ts": time.time()}), encoding="utf-8")


class DiskCache(CacheStore):
    """Compatibility wrapper.

    Some modules import `DiskCache` (older name). Keep it as an alias to the
    current on-disk implementation.
    """

    # Older call sites use ttl_s... keep that API.
    def get_json(
        self,
        key: str,
        ttl_s: Optional[int] = None,
        *,
        ttl_seconds: Optional[int] = None,
    ) -> Optional[Any]:
        ttl = ttl_seconds if ttl_seconds is not None else ttl_s
        return super().get_json(key, ttl_seconds=ttl)

    def get_json_with_meta(
        self,
        key: str,
        ttl_s: Optional[int] = None,
        *,
        ttl_seconds: Optional[int] = None,
    ) -> tuple[Optional[Any], Optional[float]]:
        ttl = ttl_seconds if ttl_seconds is not None else ttl_s
        return super().get_json_with_meta(key, ttl_seconds=ttl)

    def get_bytes(
        self,
        key: str,
        ttl_s: Optional[int] = None,
        *,
        ttl_seconds: Optional[int] = None,
    ) -> Optional[bytes]:
        ttl = ttl_seconds if ttl_seconds is not None else ttl_s
        return super().get_bytes(key, ttl_seconds=ttl)

    def get_or_set_json(
        self,
        key: str,
        fetch_fn: Callable[[], Any],
        ttl_s: Optional[int] = None,
        *,
        ttl_seconds: Optional[int] = None,
    ) -> Any:
        ttl = ttl_seconds if ttl_seconds is not None else ttl_s
        return super().get_or_set_json(key, fetch_fn, ttl_seconds=ttl)
