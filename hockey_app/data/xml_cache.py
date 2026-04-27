from __future__ import annotations

import datetime as dt
import io
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from hockey_app.data.paths import cache_dir


def _xml_season_dir(season: str) -> Path:
    path = cache_dir() / "online" / "xml" / str(season)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _xml_path(season: str, lump: str) -> Path:
    return _xml_season_dir(season) / f"{lump}.xml"


def _now_iso() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _to_text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _to_int(value: Any) -> Optional[int]:
    try:
        return int(float(value))
    except Exception:
        return None


def _to_bool(value: Any) -> bool:
    text = _to_text(value).lower()
    return text in {"1", "true", "yes", "y", "on"}


def _status_time_sort_value(day: dt.date, status_text: Any) -> str:
    stxt = _to_text(status_text).upper()
    m = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*([AP]M)\b", stxt)
    if not m:
        return ""
    hour = int(m.group(1))
    minute = int(m.group(2) or 0)
    ampm = m.group(3)
    if hour == 12:
        hour = 0
    if ampm == "PM":
        hour += 12
    try:
        return dt.datetime(day.year, day.month, day.day, hour, minute).isoformat()
    except Exception:
        return ""


def _read_or_new(path: Path, root_tag: str = "cache") -> tuple[ET.ElementTree, ET.Element]:
    if path.exists():
        try:
            tree = ET.parse(path)
            root = tree.getroot()
            if root.tag == root_tag:
                return tree, root
        except Exception:
            pass
    root = ET.Element(root_tag)
    return ET.ElementTree(root), root


def _indent(elem: ET.Element, level: int = 0) -> None:
    indent = "\n" + "  " * level
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = indent + "  "
        for child in elem:
            _indent(child, level + 1)
        if not child.tail or not child.tail.strip():
            child.tail = indent
    if level and (not elem.tail or not elem.tail.strip()):
        elem.tail = indent


def _safe_write(tree: ET.ElementTree, path: Path) -> bool:
    _indent(tree.getroot())
    output = io.BytesIO()
    tree.write(output, encoding="utf-8", xml_declaration=True)
    new_bytes = output.getvalue()
    try:
        if path.exists() and path.read_bytes() == new_bytes:
            return False
    except Exception:
        pass
    path.write_bytes(new_bytes)
    return True


def _ordered_labels(labels: list[str]) -> list[str]:
    def key(label: str) -> tuple[int, str]:
        raw = str(label or "").strip()
        try:
            return (0, dt.date.fromisoformat(raw[:10]).isoformat())
        except Exception:
            return (1, raw)
    return sorted([str(x) for x in labels], key=key)


def _write_cache_map(season: str) -> None:
    path = _xml_season_dir(season) / "cache_map.xml"
    root = ET.Element("cache_map", {"season": str(season), "updated_at": _now_iso()})
    tabs = ET.SubElement(root, "tabs")
    entries = [
        ("Scoreboard", "games.xml"),
        ("Team Stats", "team_stats.xml"),
        ("Game Stats", "game_stats.xml"),
        ("Player Stats", "player_stats.xml"),
        ("Points", "points_history.xml"),
        ("Goal Differential", "goal_differential.xml"),
        ("Predictions", "predictions_<metric>.xml"),
    ]
    for name, xml in entries:
        ET.SubElement(tabs, "tab", {"name": name, "xml": xml})
    _safe_write(ET.ElementTree(root), path)


def normalize_season_xml_order(season: str) -> list[Path]:
    changed: list[Path] = []
    root_dir = _xml_season_dir(season)
    for path in sorted(root_dir.glob("*.xml")):
        try:
            tree = ET.parse(path)
        except Exception:
            continue
        if _safe_write(tree, path):
            changed.append(path)
    if changed:
        _write_cache_map(season)
    return changed


def ensure_season_xml_scaffold(season: str) -> None:
    for lump in (
        "games",
        "team_stats",
        "game_stats",
        "player_stats",
        "points_history",
        "goal_differential",
    ):
        path = _xml_path(season, lump)
        if not path.exists():
            root = ET.Element("cache", {"season": str(season), "lump": lump, "updated_at": _now_iso()})
            if lump not in {"games", "player_stats", "team_stats", "game_stats"}:
                ET.SubElement(root, "columns")
                ET.SubElement(root, "teams")
            _safe_write(ET.ElementTree(root), path)
    for metric in ("madeplayoffs", "round2", "round3", "round4", "woncup"):
        path = _xml_path(season, f"predictions_{metric}")
        if not path.exists():
            root = ET.Element("cache", {"season": str(season), "lump": f"predictions_{metric}", "league": "NHL", "updated_at": _now_iso()})
            ET.SubElement(root, "columns")
            ET.SubElement(root, "teams")
            _safe_write(ET.ElementTree(root), path)
    _write_cache_map(season)


def _game_code(team_obj: dict[str, Any]) -> str:
    if not isinstance(team_obj, dict):
        return ""
    for key in ("abbrev", "abbreviation", "teamAbbrev", "code"):
        value = _to_text(team_obj.get(key)).upper()
        if value:
            return value
    return ""


def _game_score(team_obj: dict[str, Any]) -> str:
    value = _to_int(team_obj.get("score") if isinstance(team_obj, dict) else None)
    return "" if value is None else str(value)


def _game_shots(team_obj: dict[str, Any]) -> str:
    if not isinstance(team_obj, dict):
        return ""
    for key in ("shotsOnGoal", "sog", "shots"):
        value = _to_int(team_obj.get(key))
        if value is not None:
            return str(value)
    return ""


def _game_clock_remaining(game_obj: dict[str, Any]) -> str:
    if not isinstance(game_obj, dict):
        return ""
    clock = game_obj.get("clock")
    if not isinstance(clock, dict):
        return ""
    return _to_text(clock.get("timeRemaining") or clock.get("time"))


def _game_clock_intermission(game_obj: dict[str, Any]) -> str:
    if not isinstance(game_obj, dict):
        return ""
    clock = game_obj.get("clock")
    if not isinstance(clock, dict):
        return ""
    return "1" if bool(clock.get("inIntermission")) else ""


def _game_period_number(game_obj: dict[str, Any]) -> str:
    if not isinstance(game_obj, dict):
        return ""
    pd = game_obj.get("periodDescriptor")
    if not isinstance(pd, dict):
        return ""
    value = _to_int(pd.get("number"))
    return "" if value is None else str(value)


def _game_period_type(game_obj: dict[str, Any]) -> str:
    if not isinstance(game_obj, dict):
        return ""
    pd = game_obj.get("periodDescriptor")
    if not isinstance(pd, dict):
        return ""
    return _to_text(pd.get("periodType")).upper()


def write_games_day_xml(*, season: str, day: dt.date, games: list[dict[str, Any]]) -> Path:
    path = _xml_path(season, "games")
    tree, root = _read_or_new(path)
    root.set("season", str(season))
    root.set("lump", "games")
    root.set("updated_at", _now_iso())

    day_iso = day.isoformat()
    for node in list(root.findall("day")):
        if node.get("date") == day_iso:
            root.remove(node)
    day_node = ET.SubElement(root, "day", {"date": day_iso})

    def sort_key(game: dict[str, Any]) -> tuple[int, str, int]:
        start_key = _to_text(game.get("startTimeUTC") or game.get("startTime"))
        if not start_key:
            start_key = _status_time_sort_value(day, game.get("statusText"))
        has_start = 0 if start_key else 1
        return (has_start, start_key, _to_int(game.get("id") or game.get("gameId")) or 0)

    for game in sorted([g for g in games if isinstance(g, dict)], key=sort_key):
        away = game.get("awayTeam") if isinstance(game.get("awayTeam"), dict) else {}
        home = game.get("homeTeam") if isinstance(game.get("homeTeam"), dict) else {}
        attrs = {
            "id": _to_text(game.get("id") or game.get("gameId")),
            "league": _to_text(game.get("league")),
            "state": _to_text(game.get("gameState") or game.get("gameStatus") or game.get("state")).upper(),
            "status_text": _to_text(game.get("statusText")),
            "stage": _to_text(game.get("displayStage")),
            "division": _to_text(game.get("olympicsDivision")),
            "start_utc": _to_text(game.get("startTimeUTC") or game.get("startTime")),
            "away_code": _game_code(away),
            "home_code": _game_code(home),
            "away_score": _game_score(away),
            "home_score": _game_score(home),
            "away_shots": _game_shots(away),
            "home_shots": _game_shots(home),
            "clock_remaining": _game_clock_remaining(game),
            "clock_intermission": _game_clock_intermission(game),
            "period_number": _game_period_number(game),
            "period_type": _game_period_type(game),
            # Preserve postseason metadata so cached/web fallbacks keep playoff labels.
            "season_value": _to_text(game.get("season")),
            "game_type": _to_text(game.get("gameType")),
            "game_type_id": _to_text(game.get("gameTypeId")),
            "game_type_code": _to_text(game.get("gameTypeCode")),
            "playoff_round": _to_text(game.get("playoffRound") or game.get("round")),
            "schedule_state": _to_text(game.get("gameScheduleState")),
        }
        node = ET.SubElement(day_node, "game", attrs)
        teams = ET.SubElement(node, "teams")
        away_name = away.get("name") if isinstance(away.get("name"), dict) else away.get("name")
        home_name = home.get("name") if isinstance(home.get("name"), dict) else home.get("name")
        teams.set("away_name", _to_text(away_name.get("default") if isinstance(away_name, dict) else away_name))
        teams.set("home_name", _to_text(home_name.get("default") if isinstance(home_name, dict) else home_name))

    if _safe_write(tree, path):
        _write_cache_map(season)
    return path


def read_games_day_xml(*, season: str, day: dt.date) -> list[dict[str, Any]]:
    path = _xml_path(season, "games")
    if not path.exists():
        return []
    try:
        tree = ET.parse(path)
    except Exception:
        return []
    root = tree.getroot()
    day_node = None
    for node in root.findall("day"):
        if node.get("date") == day.isoformat():
            day_node = node
            break
    if day_node is None:
        return []

    out: list[dict[str, Any]] = []
    for game in day_node.findall("game"):
        away = {"abbrev": _to_text(game.get("away_code")).upper(), "score": _to_int(game.get("away_score")) or 0}
        home = {"abbrev": _to_text(game.get("home_code")).upper(), "score": _to_int(game.get("home_score")) or 0}
        away_shots = _to_int(game.get("away_shots"))
        home_shots = _to_int(game.get("home_shots"))
        if away_shots is not None:
            away["shotsOnGoal"] = away_shots
        if home_shots is not None:
            home["shotsOnGoal"] = home_shots
        teams = game.find("teams")
        if teams is not None:
            away_name = _to_text(teams.get("away_name"))
            home_name = _to_text(teams.get("home_name"))
            if away_name:
                away["name"] = {"default": away_name}
            if home_name:
                home["name"] = {"default": home_name}
        row: dict[str, Any] = {
            "id": _to_int(game.get("id")) or 0,
            "league": _to_text(game.get("league")),
            "gameState": _to_text(game.get("state")).upper(),
            "statusText": _to_text(game.get("status_text")),
            "displayStage": _to_text(game.get("stage")),
            "olympicsDivision": _to_text(game.get("division")),
            "startTimeUTC": _to_text(game.get("start_utc")),
            "awayTeam": away,
            "homeTeam": home,
        }
        clock_remaining = _to_text(game.get("clock_remaining"))
        clock_intermission = _to_bool(game.get("clock_intermission"))
        if clock_remaining or clock_intermission:
            clock: dict[str, Any] = {}
            if clock_remaining:
                clock["timeRemaining"] = clock_remaining
            if clock_intermission:
                clock["inIntermission"] = True
            row["clock"] = clock
        period_number = _to_int(game.get("period_number"))
        period_type = _to_text(game.get("period_type")).upper()
        if (period_number is not None and period_number > 0) or period_type:
            pd: dict[str, Any] = {}
            if period_number is not None and period_number > 0:
                pd["number"] = period_number
            if period_type:
                pd["periodType"] = period_type
            row["periodDescriptor"] = pd
        season_value = _to_int(game.get("season_value"))
        if season_value is not None:
            row["season"] = season_value
        for src_key, dst_key in (("game_type", "gameType"), ("game_type_id", "gameTypeId"), ("game_type_code", "gameTypeCode"), ("schedule_state", "gameScheduleState")):
            raw = _to_text(game.get(src_key))
            if raw:
                maybe_int = _to_int(raw)
                row[dst_key] = maybe_int if maybe_int is not None and raw.isdigit() else raw
        playoff_round = _to_int(game.get("playoff_round"))
        if playoff_round is not None:
            row["playoffRound"] = playoff_round
        out.append(row)
    return out


def write_table_xml(
    *,
    season: str,
    lump: str,
    league: str,
    start: dt.date,
    end: dt.date,
    df: pd.DataFrame,
    phase: str | None = None,
) -> Path:
    path = _xml_path(season, lump)
    tree, root = _read_or_new(path)
    root.set("season", str(season))
    root.set("lump", str(lump))
    root.set("league", str(league).upper())
    root.set("phase", _to_text(phase))
    root.set("start", start.isoformat())
    root.set("end", end.isoformat())
    root.set("updated_at", _now_iso())
    for node in list(root):
        root.remove(node)
    columns = ET.SubElement(root, "columns")
    ordered_cols = _ordered_labels([str(c) for c in list(df.columns)])
    if ordered_cols and ordered_cols != [str(c) for c in list(df.columns)]:
        try:
            df = df.loc[:, ordered_cols]
        except Exception:
            pass
    for idx, col in enumerate([str(c) for c in list(df.columns)]):
        ET.SubElement(columns, "col", {"idx": str(idx), "label": col})
    teams = ET.SubElement(root, "teams")
    for code in [str(i) for i in list(df.index)]:
        tnode = ET.SubElement(teams, "team", {"code": code})
        row = df.loc[code]
        values = row.tolist() if hasattr(row, "tolist") else []
        for idx, value in enumerate(values):
            if pd.isna(value):
                continue
            ET.SubElement(tnode, "v", {"cidx": str(idx), "value": f"{float(value):.6f}"})
    if _safe_write(tree, path):
        _write_cache_map(season)
    return path


def read_table_xml(
    *,
    season: str,
    lump: str,
    league: str | None = None,
    phase: str | None = None,
) -> Optional[pd.DataFrame]:
    path = _xml_path(season, lump)
    if not path.exists():
        return None
    try:
        tree = ET.parse(path)
    except Exception:
        return None
    root = tree.getroot()
    if league:
        xml_league = _to_text(root.get("league")).upper()
        if xml_league and xml_league != str(league).upper():
            return None
    if phase:
        xml_phase = _to_text(root.get("phase"))
        if xml_phase and xml_phase != str(phase):
            return None
    col_nodes = sorted((root.find("columns") or ET.Element("columns")).findall("col"), key=lambda n: _to_int(n.get("idx")) or 0)
    columns = [str(node.get("label") or "") for node in col_nodes]
    if not columns:
        return None
    rows: list[list[float]] = []
    index: list[str] = []
    for team in (root.find("teams") or ET.Element("teams")).findall("team"):
        code = _to_text(team.get("code")).upper()
        if not code:
            continue
        values = [float("nan")] * len(columns)
        for node in team.findall("v"):
            idx = _to_int(node.get("cidx"))
            if idx is None or not (0 <= idx < len(columns)):
                continue
            try:
                values[idx] = float(_to_text(node.get("value")))
            except Exception:
                pass
        index.append(code)
        rows.append(values)
    if not index:
        return None
    return pd.DataFrame(rows, index=index, columns=columns, dtype="float64")


def write_team_stats_xml(*, season: str, league: str, phase_rows: dict[str, dict[str, Any]]) -> Path:
    path = _xml_path(season, "team_stats")
    tree, root = _read_or_new(path)
    root.set("season", str(season))
    root.set("lump", "team_stats")
    root.set("league", str(league).upper())
    root.set("updated_at", _now_iso())
    for node in list(root):
        root.remove(node)
    for phase in ("preseason", "regular", "postseason"):
        blob = phase_rows.get(phase)
        if not isinstance(blob, dict):
            continue
        pnode = ET.SubElement(root, "phase", {"name": phase})
        rows_by_date = blob.get("rows_by_date") if isinstance(blob.get("rows_by_date"), dict) else {}
        for day, rows in sorted(rows_by_date.items(), key=lambda kv: str(kv[0])):
            dnode = ET.SubElement(pnode, "day", {"date": day.isoformat() if isinstance(day, dt.date) else str(day)})
            for row in sorted([r for r in rows if isinstance(r, dict)], key=lambda r: _to_text(r.get("team")).upper()):
                tnode = ET.SubElement(dnode, "team", {"code": _to_text(row.get("team")).upper(), "record": _to_text(row.get("record"))})
                for key, value in row.items():
                    if key in {"team", "record"} or value is None:
                        continue
                    ET.SubElement(tnode, "stat", {"name": str(key), "value": _to_text(value)})
    if _safe_write(tree, path):
        _write_cache_map(season)
    return path


def read_team_stats_xml(*, season: str, league: str | None = None) -> Optional[dict[str, dict[str, Any]]]:
    path = _xml_path(season, "team_stats")
    if not path.exists():
        return None
    try:
        tree = ET.parse(path)
    except Exception:
        return None
    root = tree.getroot()
    if league:
        xml_league = _to_text(root.get("league")).upper()
        if xml_league and xml_league != str(league).upper():
            return None
    out: dict[str, dict[str, Any]] = {}
    for phase in root.findall("phase"):
        name = _to_text(phase.get("name"))
        if not name:
            continue
        dates: list[dt.date] = []
        rows_by_date: dict[dt.date, list[dict[str, Any]]] = {}
        for day in phase.findall("day"):
            try:
                date_value = dt.date.fromisoformat(_to_text(day.get("date"))[:10])
            except Exception:
                continue
            rows: list[dict[str, Any]] = []
            for team in day.findall("team"):
                row: dict[str, Any] = {"team": _to_text(team.get("code")).upper(), "record": _to_text(team.get("record"))}
                for stat in team.findall("stat"):
                    key = _to_text(stat.get("name"))
                    value = _to_text(stat.get("value"))
                    if not key:
                        continue
                    try:
                        row[key] = float(value) if "." in value else int(value)
                    except Exception:
                        row[key] = value
                rows.append(row)
            dates.append(date_value)
            rows_by_date[date_value] = rows
        out[name] = {"dates": sorted(dates), "rows_by_date": rows_by_date}
    return out or None


def write_game_stats_xml(*, season: str, league: str, phase_tables: dict[str, dict[str, Any]]) -> Path:
    path = _xml_path(season, "game_stats")
    tree, root = _read_or_new(path)
    root.set("season", str(season))
    root.set("lump", "game_stats")
    root.set("league", str(league).upper())
    root.set("updated_at", _now_iso())
    for node in list(root):
        root.remove(node)
    for phase in ("preseason", "regular", "postseason"):
        blob = phase_tables.get(phase)
        if not isinstance(blob, dict):
            continue
        pnode = ET.SubElement(root, "phase", {"name": phase})
        columns = ET.SubElement(pnode, "columns")
        date_cols = _ordered_labels([str(c) for c in list(blob.get("date_cols") or [])])
        for idx, col in enumerate(date_cols):
            ET.SubElement(columns, "col", {"idx": str(idx), "label": col})
        teams = ET.SubElement(pnode, "teams")
        for row in sorted([r for r in list(blob.get("rows") or []) if isinstance(r, dict)], key=lambda r: _to_text(r.get("team")).upper()):
            tnode = ET.SubElement(teams, "team", {"code": _to_text(row.get("team")).upper()})
            for idx, col in enumerate(date_cols):
                value = _to_text(row.get(col))
                if value:
                    ET.SubElement(tnode, "g", {"cidx": str(idx), "result": value})
    if _safe_write(tree, path):
        _write_cache_map(season)
    return path


def read_game_stats_xml(*, season: str, league: str | None = None) -> Optional[dict[str, dict[str, Any]]]:
    path = _xml_path(season, "game_stats")
    if not path.exists():
        return None
    try:
        tree = ET.parse(path)
    except Exception:
        return None
    root = tree.getroot()
    if league:
        xml_league = _to_text(root.get("league")).upper()
        if xml_league and xml_league != str(league).upper():
            return None
    out: dict[str, dict[str, Any]] = {}
    for phase in root.findall("phase"):
        name = _to_text(phase.get("name"))
        columns = [str(node.get("label") or "") for node in sorted((phase.find("columns") or ET.Element("columns")).findall("col"), key=lambda n: _to_int(n.get("idx")) or 0)]
        rows: list[dict[str, str]] = []
        for team in (phase.find("teams") or ET.Element("teams")).findall("team"):
            row: dict[str, str] = {"team": _to_text(team.get("code")).upper()}
            for game in team.findall("g"):
                idx = _to_int(game.get("cidx"))
                if idx is None or not (0 <= idx < len(columns)):
                    continue
                row[columns[idx]] = _to_text(game.get("result"))
            rows.append(row)
        out[name] = {"date_cols": columns, "rows": rows, "games_by_team_col": {}}
    return out or None


def write_player_stats_xml(*, season: str, league: str, payload: dict[str, Any]) -> Path:
    path = _xml_path(season, "player_stats")
    tree, root = _read_or_new(path)
    root.set("season", str(season))
    root.set("lump", "player_stats")
    root.set("league", str(league).upper())
    root.set("phase", _to_text(payload.get("phase")))
    root.set("date", _to_text(payload.get("date")))
    root.set("updated_at", _to_text(payload.get("updated")) or _now_iso())
    for node in list(root):
        root.remove(node)
    for group_name in ("skaters", "goalies"):
        group = payload.get(group_name) if isinstance(payload.get(group_name), dict) else {}
        gnode = ET.SubElement(root, "group", {"name": group_name})
        for name in sorted(group.keys()):
            values = group.get(name)
            if not isinstance(values, dict):
                continue
            pnode = ET.SubElement(gnode, "player", {"name": str(name), "team": _to_text(values.get("team")).upper(), "pid": _to_text(values.get("_pid"))})
            for key, value in sorted(values.items()):
                if key in {"team", "_pid"} or value is None:
                    continue
                ET.SubElement(pnode, "stat", {"name": str(key), "value": _to_text(value)})
    if _safe_write(tree, path):
        _write_cache_map(season)
    return path


def read_player_stats_xml(*, season: str, league: str | None = None, phase: str | None = None) -> Optional[dict[str, Any]]:
    path = _xml_path(season, "player_stats")
    if not path.exists():
        return None
    try:
        tree = ET.parse(path)
    except Exception:
        return None
    root = tree.getroot()
    if league:
        xml_league = _to_text(root.get("league")).upper()
        if xml_league and xml_league != str(league).upper():
            return None
    if phase:
        xml_phase = _to_text(root.get("phase"))
        if xml_phase and xml_phase != str(phase):
            return None
    out: dict[str, Any] = {
        "date": _to_text(root.get("date")),
        "league": _to_text(root.get("league")).upper(),
        "phase": _to_text(root.get("phase")),
        "updated": _to_text(root.get("updated_at")),
        "skaters": {},
        "goalies": {},
    }
    for group in root.findall("group"):
        group_name = _to_text(group.get("name"))
        if group_name not in {"skaters", "goalies"}:
            continue
        bucket: dict[str, dict[str, Any]] = {}
        for player in group.findall("player"):
            name = _to_text(player.get("name"))
            if not name:
                continue
            row: dict[str, Any] = {"team": _to_text(player.get("team")).upper(), "_pid": _to_int(player.get("pid")) or 0}
            for stat in player.findall("stat"):
                key = _to_text(stat.get("name"))
                value = _to_text(stat.get("value"))
                if not key:
                    continue
                try:
                    row[key] = float(value)
                except Exception:
                    row[key] = value
            bucket[name] = row
        out[group_name] = bucket
    return out


def write_predictions_tables_xml(*, season: str, start: dt.date, end: dt.date, tables: dict[str, pd.DataFrame]) -> list[Path]:
    out: list[Path] = []
    for metric, frame in tables.items():
        if isinstance(frame, pd.DataFrame):
            out.append(write_table_xml(season=season, lump=f"predictions_{metric}", league="NHL", start=start, end=end, df=frame))
    return out


def read_predictions_tables_xml(*, season: str, metrics: list[str] | None = None) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    if metrics is None:
        metrics = []
        for path in _xml_season_dir(season).glob("predictions_*.xml"):
            stem = path.stem
            if stem.startswith("predictions_"):
                metrics.append(stem.replace("predictions_", "", 1))
    for metric in metrics:
        frame = read_table_xml(season=season, lump=f"predictions_{metric}")
        if isinstance(frame, pd.DataFrame) and not frame.empty:
            out[metric] = frame
    return out
