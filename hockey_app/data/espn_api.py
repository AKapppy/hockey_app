from __future__ import annotations

from datetime import date
from typing import Any, Optional

import requests

from .. import config as cfg
from .cache import DiskCache


class ESPNApi:
    """Small cached client for ESPN's public scoreboard JSON endpoints."""

    def __init__(self, cache: DiskCache) -> None:
        self.cache = cache
        self.base_url: str = getattr(cfg, "ESPN_API_BASE_URL", "https://site.api.espn.com/apis/site/v2")
        self.headers: dict[str, str] = getattr(
            cfg,
            "HEADERS",
            {"User-Agent": "hockey_app/1.0 (+https://site.api.espn.com)"},
        )
        self.timeout_s: int = int(getattr(cfg, "REQUEST_TIMEOUT_S", 20))
        self.live_ttl_s: int = int(getattr(cfg, "ESPN_SCOREBOARD_LIVE_TTL_S", 120))

    def _scoreboard_key(self, sport: str, league: str, d: date) -> str:
        return f"espn/{sport}/{league}/scoreboard/{d.strftime('%Y%m%d')}"

    def _ttl_for_date(self, d: date) -> Optional[int]:
        today = date.today()
        if d < today:
            return None
        if d == today:
            return self.live_ttl_s
        return 6 * 3600

    def get_cached_scoreboard(self, sport: str, league: str, d: date) -> Optional[dict[str, Any]]:
        key = self._scoreboard_key(sport, league, d)
        ttl = self._ttl_for_date(d)
        cached = self.cache.get_json(key, ttl_s=ttl)
        if isinstance(cached, dict):
            return cached
        return None

    def scoreboard(
        self,
        sport: str,
        league: str,
        d: date,
        *,
        allow_network: bool = True,
        force_network: bool = False,
    ) -> dict[str, Any]:
        dstr = d.strftime("%Y%m%d")
        key = self._scoreboard_key(sport, league, d)
        ttl = self._ttl_for_date(d)

        # When network is disallowed, treat cache as authoritative regardless of TTL.
        read_ttl = (-1 if (allow_network and force_network) else (ttl if allow_network else None))
        cached = self.cache.get_json(key, ttl_s=read_ttl)
        if isinstance(cached, dict):
            return cached
        if not allow_network:
            return {}

        urls = [
            f"{self.base_url.rstrip('/')}/sports/{sport}/{league}/scoreboard?dates={dstr}&limit=200",
            f"{self.base_url.rstrip('/')}/sports/{sport}/{league}/scoreboard?dates={dstr}",
        ]
        last_err: Exception | None = None
        for url in urls:
            try:
                r = requests.get(url, headers=self.headers, timeout=self.timeout_s)
                r.raise_for_status()
                data = r.json()
                self.cache.set_json(key, data)
                return data
            except Exception as e:
                last_err = e
                continue
        if last_err is not None:
            raise last_err
        return {}

    def get_cached_scoreboard_all_hockey(self, d: date) -> Optional[dict[str, Any]]:
        dstr = d.strftime("%Y%m%d")
        key = f"espn/hockey/all/scoreboard/{dstr}"
        ttl = self._ttl_for_date(d)
        cached = self.cache.get_json(key, ttl_s=ttl)
        if isinstance(cached, dict):
            return cached
        return None

    def scoreboard_all_hockey(
        self,
        d: date,
        *,
        allow_network: bool = True,
        force_network: bool = False,
    ) -> dict[str, Any]:
        dstr = d.strftime("%Y%m%d")
        key = f"espn/hockey/all/scoreboard/{dstr}"
        ttl = self._ttl_for_date(d)

        # When network is disallowed, treat cache as authoritative regardless of TTL.
        read_ttl = (-1 if (allow_network and force_network) else (ttl if allow_network else None))
        cached = self.cache.get_json(key, ttl_s=read_ttl)
        if isinstance(cached, dict):
            return cached
        if not allow_network:
            return {}

        urls = [
            f"{self.base_url.rstrip('/')}/sports/hockey/scoreboard?dates={dstr}&limit=400",
            f"{self.base_url.rstrip('/')}/sports/hockey/scoreboard?dates={dstr}",
        ]
        last_err: Exception | None = None
        for url in urls:
            try:
                r = requests.get(url, headers=self.headers, timeout=self.timeout_s)
                r.raise_for_status()
                data = r.json()
                self.cache.set_json(key, data)
                return data
            except Exception as e:
                last_err = e
                continue
        if last_err is not None:
            raise last_err
        return {}

    def discover_hockey_leagues(self) -> list[dict[str, str]]:
        """
        Returns best-effort league metadata from ESPN hockey index.
        Each item can contain keys: slug, name, abbreviation, id.
        """
        key = "espn/hockey/leagues/index"
        cached = self.cache.get_json(key, ttl_s=24 * 3600)
        if isinstance(cached, list):
            return [x for x in cached if isinstance(x, dict)]

        url = f"{self.base_url.rstrip('/')}/sports/hockey"
        r = requests.get(url, headers=self.headers, timeout=self.timeout_s)
        r.raise_for_status()
        raw = r.json()
        out: list[dict[str, str]] = []
        leagues = raw.get("leagues") or []
        for lg in leagues:
            if not isinstance(lg, dict):
                continue
            item = {
                "slug": str(lg.get("slug") or "").strip(),
                "name": str(lg.get("name") or "").strip(),
                "abbreviation": str(lg.get("abbreviation") or "").strip(),
                "id": str(lg.get("id") or "").strip(),
            }
            if item["slug"] or item["name"]:
                out.append(item)
        self.cache.set_json(key, out)
        return out
