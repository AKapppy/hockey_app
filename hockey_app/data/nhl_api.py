from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo

import requests

from .. import config as cfg
from .cache import DiskCache


# -----------------------------
# Models
# -----------------------------

@dataclass(frozen=True)
class GameSummary:
    game_id: int
    game_date: date

    away_abbrev: str
    home_abbrev: str

    away_score: int
    home_score: int

    game_state: str
    start_time_local: Optional[datetime]  # timezone-aware (local)
    status_text: str


@dataclass(frozen=True)
class GoalEvent:
    game_id: int
    period: str               # e.g., "1", "2", "3", "OT"
    time_in_period: str       # e.g., "12:34"
    team_abbrev: str          # scoring team

    scorer: str
    assists: list[str]

    strength: str             # EV/PP/SH etc (best effort)
    away_score: int
    home_score: int


@dataclass(frozen=True)
class SeasonBoundaries:
    preseason_start: Optional[date]
    regular_start: Optional[date]
    regular_end: Optional[date]
    playoffs_start: Optional[date]
    playoffs_end: Optional[date]
    first_scheduled_game: Optional[date]
    last_scheduled_game: Optional[date]


# -----------------------------
# NHL API wrapper (api-web.nhle.com)
# -----------------------------

class NHLApi:
    """
    Uses (documented in Zmalski NHL API Reference):
      - /v1/score/{date}
      - /v1/gamecenter/{game-id}/play-by-play
      - optional: /v1/schedule-calendar/{date}, /v1/schedule/{date}
    """

    def __init__(self, cache: DiskCache) -> None:
        self.cache = cache

        self.base_url: str = getattr(cfg, "NHL_API_BASE_URL", "https://api-web.nhle.com")
        self.headers: dict[str, str] = getattr(
            cfg,
            "HEADERS",
            {"User-Agent": "hockey_app/1.0 (+https://api-web.nhle.com)"},
        )
        self.timeout_s: int = int(getattr(cfg, "REQUEST_TIMEOUT_S", 20))

        self.tz_name: str = getattr(cfg, "TIMEZONE", "America/New_York")
        self.tz = ZoneInfo(self.tz_name)

        # default TTLs (tweak in config.py if you want)
        self.score_live_ttl_s: int = int(getattr(cfg, "NHL_SCORE_LIVE_TTL_S", 90))
        self.pbp_live_ttl_s: int = int(getattr(cfg, "NHL_PBP_LIVE_TTL_S", 180))
        self.boxscore_live_ttl_s: int = int(getattr(cfg, "NHL_BOXSCORE_LIVE_TTL_S", 120))
        self.landing_live_ttl_s: int = int(getattr(cfg, "NHL_LANDING_LIVE_TTL_S", 120))
        self.standings_live_ttl_s: int = int(getattr(cfg, "NHL_STANDINGS_LIVE_TTL_S", 120))

    # ---------- public ----------

    def get_games_for_date(self, d: date) -> list[GameSummary]:
        raw = self.score(d)
        games = raw.get("games") or []
        out: list[GameSummary] = []
        for g in games:
            out.append(self._parse_game_summary(d, g))
        return out

    def get_goal_events(self, game_id: int) -> list[GoalEvent]:
        pbp = self.play_by_play(game_id)
        plays = pbp.get("plays") or pbp.get("allPlays") or []

        goals: list[GoalEvent] = []
        for p in plays:
            # New NHL JSON often uses "typeDescKey" == "goal"
            tkey = str(p.get("typeDescKey") or p.get("result", {}).get("eventTypeId") or "").lower()
            if tkey != "goal":
                # Some older shapes: p["result"]["eventTypeId"] == "GOAL"
                if str(p.get("result", {}).get("eventTypeId") or "").upper() != "GOAL":
                    continue
            ge = self._parse_goal_event(game_id, p)
            if ge:
                goals.append(ge)

        # Chronological order is usually already correct; keep as-is.
        return goals

    def warm_past_finals(
        self,
        season_start: date,
        up_to: date,
        progress: Optional[Callable[[date, int, int], None]] = None,
    ) -> None:
        """
        Populates FINAL scoreboard caches from season_start through up_to,
        but skips any day already pinned as FINAL.

        WARNING: This can be a lot of calls if you run it for the whole season.
        Use sparingly (or on-demand).
        """
        if up_to < season_start:
            return

        total = (up_to - season_start).days + 1
        for i in range(total):
            d = season_start + timedelta(days=i)
            if self._has_final_day_pinned(d):
                if progress:
                    progress(d, i + 1, total)
                continue
            _ = self.score(d)  # score() will pin if it detects final day
            if progress:
                progress(d, i + 1, total)

    def get_season_boundaries(self, probe_date: Optional[date] = None) -> SeasonBoundaries:
        """
        Best-effort season boundaries pulled from schedule metadata.
        Uses whichever fields NHL returns for the current season and falls back
        gracefully when some fields are absent.
        """
        d = probe_date or date.today()
        payloads: list[dict[str, Any]] = []

        for fetch in (self.schedule_by_date, self.schedule_calendar):
            try:
                raw = fetch(d)
            except Exception:
                continue
            if isinstance(raw, dict):
                payloads.append(raw)

        pre = self._pick_date(payloads, (
            "preSeasonStartDate",
            "preseasonStartDate",
            "exhibitionStartDate",
        ), prefer="min")
        reg_start = self._pick_date(payloads, (
            "regularSeasonStartDate",
            "regSeasonStartDate",
            "regularStartDate",
        ), prefer="min")
        reg_end = self._pick_date(payloads, (
            "regularSeasonEndDate",
            "regSeasonEndDate",
            "regularEndDate",
        ), prefer="max")
        po_start = self._pick_date(payloads, (
            "playoffStartDate",
            "playoffsStartDate",
            "postSeasonStartDate",
        ), prefer="min")
        po_end = self._pick_date(payloads, (
            "playoffEndDate",
            "playoffsEndDate",
            "postSeasonEndDate",
            "stanleyCupFinalEndDate",
        ), prefer="max")

        season_start = self._pick_date(payloads, ("seasonStartDate", "startDate"), prefer="min")
        season_end = self._pick_date(payloads, ("seasonEndDate", "endDate", "lastGameDate"), prefer="max")

        first_game, last_game = self._scan_gameweek_bounds(payloads)

        # Fallback composition for missing segments.
        if pre is None:
            pre = season_start or first_game
        if reg_start is None:
            reg_start = season_start or first_game
        if po_end is None:
            po_end = season_end or last_game
        if reg_end is None:
            reg_end = po_start or season_end or last_game
        if po_start is None and reg_end is not None:
            po_start = reg_end + timedelta(days=1)

        # Prefer full-season metadata for range bounds; gameWeek is fallback only.
        first_game = pre or reg_start or season_start or first_game
        last_game = po_end or reg_end or season_end or last_game

        return SeasonBoundaries(
            preseason_start=pre,
            regular_start=reg_start,
            regular_end=reg_end,
            playoffs_start=po_start,
            playoffs_end=po_end,
            first_scheduled_game=first_game,
            last_scheduled_game=last_game,
        )

    # ---------- endpoints ----------

    def score(self, d: date, *, force_network: bool = False) -> dict[str, Any]:
        """
        Returns /v1/score/{date} with smart caching:
          - If a day is detected as "all final" (or has no games), we also pin it to a FINAL cache key.
          - Today/future uses a short TTL.
        """
        today = date.today()
        day_str = d.isoformat()

        if force_network:
            day_str = d.isoformat()
            raw_force = self._get_json(
                f"/v1/score/{day_str}",
                self._key_score_live(d),
                ttl_s=-1,  # always stale => force network fetch
            )
            if self._day_is_final(raw_force):
                self.cache.set_json(self._key_score_final(d), raw_force)
            return raw_force

        # If day < today, prefer pinned final data if present
        if d < today:
            pinned = self.cache.get_json(self._key_score_final(d), ttl_s=None)
            if isinstance(pinned, dict):
                return pinned

            # not pinned yet: fetch with a reasonable TTL and then pin if final
            raw = self._get_json(f"/v1/score/{day_str}", self._key_score_live(d), ttl_s=max(self.score_live_ttl_s, 300))
            if self._day_is_final(raw):
                self.cache.set_json(self._key_score_final(d), raw)
            return raw

        # today/future
        raw = self._get_json(f"/v1/score/{day_str}", self._key_score_live(d), ttl_s=self.score_live_ttl_s)
        # if somehow final (late night), pin it too
        if self._day_is_final(raw):
            self.cache.set_json(self._key_score_final(d), raw)
        return raw

    def play_by_play(self, game_id: int, *, force_network: bool = False) -> dict[str, Any]:
        """
        Returns /v1/gamecenter/{game-id}/play-by-play with caching.
        If the game is final, we pin forever; else short TTL.
        """
        key_live = f"nhl/pbp/live/{game_id}"
        key_final = f"nhl/pbp/final/{game_id}"

        if not force_network:
            pinned = self.cache.get_json(key_final, ttl_s=None)
            if isinstance(pinned, dict):
                return pinned

        raw = self._get_json(
            f"/v1/gamecenter/{game_id}/play-by-play",
            key_live,
            ttl_s=(-1 if force_network else self.pbp_live_ttl_s),
        )

        # best-effort final detection inside pbp
        if self._pbp_is_final(raw):
            self.cache.set_json(key_final, raw)

        return raw

    def boxscore(self, game_id: int, *, force_network: bool = False) -> dict[str, Any]:
        """
        Returns /v1/gamecenter/{game-id}/boxscore with smart pinning for finals.
        """
        key_live = f"nhl/boxscore/{game_id}"
        key_final = f"nhl/boxscore/final/{game_id}"
        if not force_network:
            pinned = self.cache.get_json(key_final, ttl_s=None)
            if isinstance(pinned, dict):
                return pinned
        raw = self._get_json(
            f"/v1/gamecenter/{game_id}/boxscore",
            key_live,
            ttl_s=(-1 if force_network else self.boxscore_live_ttl_s),
        )
        if self._gamecenter_is_final(raw):
            self.cache.set_json(key_final, raw)
        return raw

    def landing(self, game_id: int, *, force_network: bool = False) -> dict[str, Any]:
        """
        Returns /v1/gamecenter/{game-id}/landing with smart pinning for finals.
        """
        key_live = f"nhl/landing/{game_id}"
        key_final = f"nhl/landing/final/{game_id}"
        if not force_network:
            pinned = self.cache.get_json(key_final, ttl_s=None)
            if isinstance(pinned, dict):
                return pinned
        raw = self._get_json(
            f"/v1/gamecenter/{game_id}/landing",
            key_live,
            ttl_s=(-1 if force_network else self.landing_live_ttl_s),
        )
        if self._gamecenter_is_final(raw):
            self.cache.set_json(key_final, raw)
        return raw

    def standings(
        self,
        d: Optional[date] = None,
        *,
        force_network: bool = False,
    ) -> dict[str, Any]:
        """
        Returns /v1/standings/{date} (or /v1/standings/now when date is omitted).
        """
        if d is None:
            cache_key = "nhl/standings/now"
            return self._get_json(
                "/v1/standings/now",
                cache_key,
                ttl_s=(-1 if force_network else self.standings_live_ttl_s),
            )
        today = date.today()
        cache_key = f"nhl/standings/{d.isoformat()}"
        ttl = (-1 if force_network else (self.standings_live_ttl_s if d >= today else None))
        return self._get_json(f"/v1/standings/{d.isoformat()}", cache_key, ttl_s=ttl)

    def player_landing(self, player_id: int, *, force_network: bool = False) -> dict[str, Any]:
        key = f"nhl/player/landing/{int(player_id)}"
        return self._get_json(
            f"/v1/player/{int(player_id)}/landing",
            key,
            ttl_s=(-1 if force_network else 3600),
        )

    def club_stats(
        self,
        team_abbrev: str,
        *,
        season: int | str | None = None,
        game_type: int = 2,
        force_network: bool = False,
    ) -> dict[str, Any]:
        team = str(team_abbrev or "").upper().strip()
        if not team:
            return {}
        if season is None:
            key = f"nhl/club_stats/{team}/now"
            path = f"/v1/club-stats/{team}/now"
        else:
            season_txt = str(int(season)) if isinstance(season, int) else str(season).strip()
            key = f"nhl/club_stats/{team}/{season_txt}/{int(game_type)}"
            path = f"/v1/club-stats/{team}/{season_txt}/{int(game_type)}"
        return self._get_json(path, key, ttl_s=(-1 if force_network else 6 * 3600))

    def roster(
        self,
        team_abbrev: str,
        *,
        season: int | str | None = None,
        force_network: bool = False,
    ) -> dict[str, Any]:
        team = str(team_abbrev or "").upper().strip()
        if not team:
            return {}
        if season is None:
            season_txt = "current"
        else:
            season_txt = str(int(season)) if isinstance(season, int) else str(season).strip()
        key = f"nhl/roster/{team}/{season_txt}"
        path = f"/v1/roster/{team}/{season_txt}"
        return self._get_json(path, key, ttl_s=(-1 if force_network else 6 * 3600))

    def schedule_by_date(self, d: date) -> dict[str, Any]:
        """
        Optional helper: /v1/schedule/{date}
        """
        return self._get_json(f"/v1/schedule/{d.isoformat()}", f"nhl/schedule/{d.isoformat()}", ttl_s=12 * 3600)

    def schedule_calendar(self, d: date) -> dict[str, Any]:
        """
        Optional helper: /v1/schedule-calendar/{date}
        """
        return self._get_json(f"/v1/schedule-calendar/{d.isoformat()}", f"nhl/schedule_calendar/{d.isoformat()}", ttl_s=24 * 3600)

    # ---------- internals ----------

    def _get_json(self, path: str, cache_key: str, ttl_s: Optional[int]) -> dict[str, Any]:
        cached = self.cache.get_json(cache_key, ttl_s=ttl_s)
        if isinstance(cached, dict):
            return cached

        url = self.base_url.rstrip("/") + path
        r = requests.get(url, headers=self.headers, timeout=self.timeout_s)
        r.raise_for_status()
        data = r.json()
        self.cache.set_json(cache_key, data)
        return data

    def _key_score_live(self, d: date) -> str:
        return f"nhl/score/live/{d.isoformat()}"

    def _key_score_final(self, d: date) -> str:
        return f"nhl/score/final/{d.isoformat()}"

    def _has_final_day_pinned(self, d: date) -> bool:
        pinned = self.cache.get_json(self._key_score_final(d), ttl_s=None)
        return isinstance(pinned, dict)

    def _day_is_final(self, score_json: dict[str, Any]) -> bool:
        games = score_json.get("games") or []
        if not games:
            return True  # no games => safe to pin; avoids re-fetching forever

        return all(self._game_is_final(g) for g in games)

    def _game_is_final(self, g: dict[str, Any]) -> bool:
        state = str(g.get("gameState") or g.get("gameStatus") or "").upper()
        # Common seen values: "FINAL", "OFF", "LIVE", "FUT"
        return state in {"FINAL", "OFF"} or state.startswith("FINAL")

    def _pbp_is_final(self, pbp: dict[str, Any]) -> bool:
        # Best effort: some shapes include gameState in "game" or top-level
        state = str(
            pbp.get("gameState")
            or pbp.get("game", {}).get("gameState")
            or ""
        ).upper()
        if state:
            return state in {"FINAL", "OFF"} or state.startswith("FINAL")

        # Fallback: if we see an "endTimeUTC" or similar marker
        game = pbp.get("game") or {}
        return bool(game.get("endTimeUTC") or pbp.get("endTimeUTC"))

    def _gamecenter_is_final(self, payload: dict[str, Any]) -> bool:
        state = str(payload.get("gameState") or payload.get("game", {}).get("gameState") or "").upper()
        if not state:
            return False
        return state in {"FINAL", "OFF"} or state.startswith("FINAL")

    def _parse_game_summary(self, d: date, g: dict[str, Any]) -> GameSummary:
        game_id = int(g.get("id") or g.get("gameId") or 0)

        away = g.get("awayTeam") or {}
        home = g.get("homeTeam") or {}

        away_abbrev = str(away.get("abbrev") or away.get("abbreviation") or away.get("teamAbbrev") or "AWY")
        home_abbrev = str(home.get("abbrev") or home.get("abbreviation") or home.get("teamAbbrev") or "HOM")

        away_score = int(away.get("score") or 0)
        home_score = int(home.get("score") or 0)

        state = str(g.get("gameState") or g.get("gameStatus") or "").upper()
        start_local = self._parse_start_time_local(g.get("startTimeUTC") or g.get("startTime") or None)

        status_text = self._format_status(g, start_local)

        return GameSummary(
            game_id=game_id,
            game_date=d,
            away_abbrev=away_abbrev,
            home_abbrev=home_abbrev,
            away_score=away_score,
            home_score=home_score,
            game_state=state,
            start_time_local=start_local,
            status_text=status_text,
        )

    def _format_status(self, g: dict[str, Any], start_local: Optional[datetime]) -> str:
        state = str(g.get("gameState") or g.get("gameStatus") or "").upper()

        if state in {"FINAL", "OFF"} or state.startswith("FINAL"):
            # Try to show OT/SO if available
            pd = g.get("periodDescriptor") or {}
            ptype = str(pd.get("periodType") or "").upper()
            if ptype in {"OT", "SO"}:
                return f"Final/{ptype}"
            return "Final"

        if state in {"LIVE", "CRIT"}:
            clock = g.get("clock") or {}
            time_rem = str(clock.get("timeRemaining") or clock.get("time") or "").strip()
            in_int = bool(clock.get("inIntermission"))
            pd = g.get("periodDescriptor") or {}
            pnum = pd.get("number")
            ptype = str(pd.get("periodType") or "").upper()

            period_label = ""
            if ptype in {"OT", "SO"}:
                period_label = ptype
            elif pnum:
                period_label = str(pnum)

            if in_int and period_label:
                return f"INT ({period_label})"
            if period_label and time_rem:
                return f"{period_label} {time_rem}"
            if time_rem:
                return time_rem
            return "Live"

        # scheduled / future
        if start_local:
            return start_local.strftime("%-I:%M %p ET")
        return "Scheduled"

    def _parse_start_time_local(self, iso_utc: Optional[str]) -> Optional[datetime]:
        if not iso_utc:
            return None
        s = str(iso_utc).strip()
        # handle 'Z'
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            return None
        if dt.tzinfo is None:
            # assume UTC if missing
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))
        return dt.astimezone(self.tz)

    def _parse_goal_event(self, game_id: int, play: dict[str, Any]) -> Optional[GoalEvent]:
        pd = play.get("periodDescriptor") or {}
        pnum = pd.get("number")
        ptype = str(pd.get("periodType") or "").upper()
        period = ptype if ptype in {"OT", "SO"} else (str(pnum) if pnum is not None else "?")

        time_in = str(play.get("timeInPeriod") or play.get("about", {}).get("periodTime") or "").strip()
        if not time_in:
            # sometimes the key is "timeRemaining"
            time_in = str(play.get("timeRemaining") or "").strip()

        details = play.get("details") or {}

        team_abbrev = str(
            details.get("eventOwnerTeamAbbrev")
            or details.get("teamAbbrev")
            or (play.get("team") or {}).get("abbrev")
            or ""
        ).strip() or "UNK"

        scorer = str(details.get("scoringPlayerName") or details.get("scorerName") or details.get("scoringPlayer") or "").strip()
        if not scorer:
            # Some shapes keep players under "players"
            scorer = self._best_effort_find_player(play, want="Scorer")

        assists: list[str] = []
        a1 = str(details.get("assist1PlayerName") or details.get("assist1Name") or "").strip()
        a2 = str(details.get("assist2PlayerName") or details.get("assist2Name") or "").strip()
        if a1:
            assists.append(a1)
        if a2:
            assists.append(a2)

        strength = str(details.get("strength") or details.get("strengthCode") or details.get("situationCode") or "").strip() or "EV"

        away_score = int(details.get("awayScore") or 0)
        home_score = int(details.get("homeScore") or 0)

        # If we somehow got here without a scorer, ignore this entry.
        if not scorer:
            return None

        return GoalEvent(
            game_id=game_id,
            period=period,
            time_in_period=time_in,
            team_abbrev=team_abbrev,
            scorer=scorer,
            assists=assists,
            strength=strength,
            away_score=away_score,
            home_score=home_score,
        )

    def _to_date(self, value: Any) -> Optional[date]:
        if isinstance(value, date):
            return value
        if not value:
            return None
        s = str(value).strip()
        if not s:
            return None
        s = s[:10]
        try:
            return date.fromisoformat(s)
        except Exception:
            return None

    def _pick_date(
        self,
        payloads: list[dict[str, Any]],
        keys: tuple[str, ...],
        *,
        prefer: str = "min",
    ) -> Optional[date]:
        out: list[date] = []
        for p in payloads:
            for k in keys:
                d = self._to_date(p.get(k))
                if d is not None:
                    out.append(d)
        if not out:
            return None
        return max(out) if prefer == "max" else min(out)

    def _scan_gameweek_bounds(self, payloads: list[dict[str, Any]]) -> tuple[Optional[date], Optional[date]]:
        seen: list[date] = []
        for p in payloads:
            for wk in p.get("gameWeek") or []:
                d = self._to_date((wk or {}).get("date"))
                if d is not None:
                    seen.append(d)
        if not seen:
            return None, None
        return min(seen), max(seen)

    def _best_effort_find_player(self, play: dict[str, Any], want: str) -> str:
        # Some older feed shapes: play["players"] = [{"player": {"fullName": ...}, "playerType": "Scorer"}, ...]
        players = play.get("players") or []
        for p in players:
            if str(p.get("playerType") or "").lower() == want.lower():
                player = p.get("player") or {}
                return str(player.get("fullName") or "").strip()
        return ""
