from __future__ import annotations

import datetime as dt
import io
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import pandas as pd

from hockey_app.data.paths import cache_dir


def _xml_season_dir(season: str) -> Path:
    p = cache_dir() / "online" / "xml" / str(season)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _xml_path(season: str, lump: str) -> Path:
    return _xml_season_dir(season) / f"{lump}.xml"


def _now_iso() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _to_int(v: Any) -> int | None:
    try:
        return int(float(v))
    except Exception:
        return None


def _to_text(v: Any) -> str:
    if v is None:
        return ""
    return str(v).strip()


def _season_start_anchor(season: Any) -> dt.date | None:
    txt = _to_text(season)
    if not txt:
        return None
    parts = txt.split("-")
    if parts and parts[0].isdigit():
        try:
            # NHL/PWHL seasons span years; use July as rollover pivot anchor.
            return dt.date(int(parts[0]), 7, 1)
        except Exception:
            return None
    return None


def _parse_iso_date(v: Any) -> dt.date | None:
    txt = _to_text(v)
    if not txt:
        return None
    try:
        return dt.date.fromisoformat(txt[:10])
    except Exception:
        return None


def _parse_label_date(v: Any, *, season_start: dt.date | None = None) -> dt.date | None:
    d = _parse_iso_date(v)
    if d is not None:
        return d
    txt = _to_text(v)
    for sep in ("/", "-"):
        parts = txt.split(sep)
        if len(parts) != 2:
            continue
        if not parts[0].isdigit() or not parts[1].isdigit():
            continue
        m = _to_int(parts[0])
        d2 = _to_int(parts[1])
        if m is None or d2 is None:
            continue
        if not (1 <= m <= 12 and 1 <= d2 <= 31):
            continue
        if season_start is None:
            return None
        yr = season_start.year + (1 if m < season_start.month else 0)
        try:
            return dt.date(yr, m, d2)
        except Exception:
            continue
    return None


def _date_sort_key(v: Any, *, season_start: dt.date | None = None) -> tuple[int, str]:
    d = _parse_label_date(v, season_start=season_start)
    if d is not None:
        return (0, d.isoformat())
    return (1, _to_text(v))


def _ordered_labels_by_date(labels: list[str], *, season_start: dt.date | None = None) -> list[str]:
    if not labels:
        return []
    original = [str(x) for x in labels]
    dated: list[tuple[str, str]] = []
    non_dated: list[str] = []
    for lbl in original:
        d = _parse_label_date(lbl, season_start=season_start)
        if d is None:
            non_dated.append(lbl)
        else:
            dated.append((d.isoformat(), lbl))
    if not dated:
        return original
    dated_sorted = [lbl for _, lbl in sorted(dated, key=lambda t: (t[0], t[1]))]
    if non_dated:
        return non_dated + dated_sorted
    return dated_sorted


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
    i = "\n" + level * "  "
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = i + "  "
        for child in elem:
            _indent(child, level + 1)
        if not child.tail or not child.tail.strip():
            child.tail = i
    if level and (not elem.tail or not elem.tail.strip()):
        elem.tail = i


def _tree_bytes(tree: ET.ElementTree) -> bytes:
    out = io.BytesIO()
    tree.write(out, encoding="utf-8", xml_declaration=True)
    return out.getvalue()


def _write_text_if_changed(path: Path, text: str) -> bool:
    try:
        if path.exists() and path.read_text(encoding="utf-8") == text:
            return False
    except Exception:
        pass
    path.write_text(text, encoding="utf-8")
    return True


def _safe_write(tree: ET.ElementTree, path: Path) -> bool:
    # Compare against existing bytes while ignoring `updated_at` churn.
    root = tree.getroot()
    candidate_updated_at = root.get("updated_at") if "updated_at" in root.attrib else None
    old_updated_at = None
    if path.exists():
        try:
            old_updated_at = ET.parse(path).getroot().get("updated_at")
        except Exception:
            old_updated_at = None
    if candidate_updated_at is not None and old_updated_at is not None:
        root.set("updated_at", old_updated_at)

    _indent(tree.getroot())
    new_bytes = _tree_bytes(tree)
    if path.exists():
        try:
            if path.read_bytes() == new_bytes:
                return False
        except Exception:
            pass

    if candidate_updated_at is not None:
        root.set("updated_at", candidate_updated_at or _now_iso())
        _indent(tree.getroot())
        new_bytes = _tree_bytes(tree)

    path.write_bytes(new_bytes)
    return True


def _reorder_children(parent: ET.Element, children: list[ET.Element]) -> None:
    for ch in list(parent):
        parent.remove(ch)
    for ch in children:
        parent.append(ch)


def _sort_games_root(root: ET.Element) -> None:
    day_nodes = list(root.findall("day"))
    if day_nodes:
        _reorder_children(root, sorted(day_nodes, key=lambda n: _date_sort_key(n.get("date"))))
    for dnode in root.findall("day"):
        games = list(dnode.findall("game"))
        if not games:
            continue
        _reorder_children(
            dnode,
            sorted(
                games,
                key=lambda g: (
                    _to_text(g.get("start_utc")),
                    _to_int(g.get("id")) or 0,
                ),
            ),
        )


def _sort_team_stats_root(root: ET.Element) -> None:
    for pnode in root.findall("phase"):
        days = list(pnode.findall("day"))
        if days:
            _reorder_children(pnode, sorted(days, key=lambda n: _date_sort_key(n.get("date"))))
        for dnode in pnode.findall("day"):
            teams = list(dnode.findall("team"))
            if teams:
                _reorder_children(dnode, sorted(teams, key=lambda n: _to_text(n.get("code")).upper()))


def _sort_indexed_columns(
    *,
    columns_node: ET.Element | None,
    teams_node: ET.Element | None,
    value_tag: str,
    idx_attr: str,
    season_start: dt.date | None = None,
) -> None:
    if columns_node is None:
        return
    col_nodes = sorted(columns_node.findall("col"), key=lambda n: _to_int(n.get("idx")) or 0)
    labels_old = [str(n.get("label") or "") for n in col_nodes]
    if not labels_old:
        return
    labels_new = _ordered_labels_by_date(labels_old, season_start=season_start)
    old_by_label = {label: idx for idx, label in enumerate(labels_old)}
    new_by_label = {label: idx for idx, label in enumerate(labels_new)}

    for n in list(columns_node.findall("col")):
        columns_node.remove(n)
    for idx, label in enumerate(labels_new):
        ET.SubElement(columns_node, "col", {"idx": str(idx), "label": str(label)})

    if teams_node is None:
        return
    teams = list(teams_node.findall("team"))
    _reorder_children(teams_node, sorted(teams, key=lambda n: _to_text(n.get("code")).upper()))
    for tnode in teams_node.findall("team"):
        vals = list(tnode.findall(value_tag))
        for vnode in vals:
            old_idx = _to_int(vnode.get(idx_attr))
            if old_idx is None or old_idx < 0 or old_idx >= len(labels_old):
                continue
            label = labels_old[old_idx]
            vnode.set(idx_attr, str(new_by_label.get(label, old_by_label.get(label, old_idx))))
        vals2 = list(tnode.findall(value_tag))
        _reorder_children(tnode, sorted(vals2, key=lambda n: _to_int(n.get(idx_attr)) or 0))


def _sort_game_stats_root(root: ET.Element) -> None:
    season_start = _season_start_anchor(root.get("season"))
    for pnode in root.findall("phase"):
        _sort_indexed_columns(
            columns_node=pnode.find("columns"),
            teams_node=pnode.find("teams"),
            value_tag="g",
            idx_attr="cidx",
            season_start=season_start,
        )


def _sort_table_root(root: ET.Element) -> None:
    season_start = _parse_iso_date(root.get("start")) or _season_start_anchor(root.get("season"))
    _sort_indexed_columns(
        columns_node=root.find("columns"),
        teams_node=root.find("teams"),
        value_tag="v",
        idx_attr="cidx",
        season_start=season_start,
    )


def _sort_player_stats_root(root: ET.Element) -> None:
    groups = [n for n in root.findall("group")]
    desired = []
    for gname in ("skaters", "goalies"):
        desired.extend([n for n in groups if _to_text(n.get("name")) == gname])
    desired.extend([n for n in groups if _to_text(n.get("name")) not in {"skaters", "goalies"}])
    if desired:
        _reorder_children(root, desired)
    for gnode in root.findall("group"):
        players = list(gnode.findall("player"))
        _reorder_children(gnode, sorted(players, key=lambda n: _to_text(n.get("name")).casefold()))


def normalize_season_xml_order(season: str) -> list[Path]:
    out: list[Path] = []
    for path in sorted(_xml_season_dir(season).glob("*.xml")):
        try:
            tree = ET.parse(path)
        except Exception:
            continue
        root = tree.getroot()
        stem = path.stem
        if stem == "games":
            _sort_games_root(root)
        elif stem == "team_stats":
            _sort_team_stats_root(root)
        elif stem == "game_stats":
            _sort_game_stats_root(root)
        elif stem == "player_stats":
            _sort_player_stats_root(root)
        else:
            _sort_table_root(root)
        if _safe_write(tree, path):
            out.append(path)
    if out:
        _write_cache_map(season)
    return out


def ensure_season_xml_scaffold(season: str) -> None:
    season = str(season or "").strip()
    if not season:
        return
    for lump in (
        "games",
        "team_stats",
        "game_stats",
        "player_stats",
        "points_history",
        "goal_differential",
    ):
        p = _xml_path(season, lump)
        if not p.exists():
            root = ET.Element("cache", {"season": season, "lump": lump, "updated_at": _now_iso()})
            _safe_write(ET.ElementTree(root), p)
    for metric in ("madeplayoffs", "round2", "round3", "round4", "woncup"):
        p = _xml_path(season, f"predictions_{metric}")
        if not p.exists():
            root = ET.Element(
                "cache",
                {
                    "season": season,
                    "lump": f"predictions_{metric}",
                    "league": "NHL",
                    "updated_at": _now_iso(),
                },
            )
            ET.SubElement(root, "columns")
            ET.SubElement(root, "teams")
            _safe_write(ET.ElementTree(root), p)
    _write_cache_map(season)


def _write_cache_map(season: str) -> None:
    root_dir = _xml_season_dir(season)
    xml_path = root_dir / "cache_map.xml"
    root = ET.Element("cache_map", {"season": str(season), "updated_at": _now_iso()})

    tabs = ET.SubElement(root, "tabs")
    entries = [
        {
            "name": "Scoreboard",
            "sources": "NHLApi.score + ESPNApi.scoreboard_all_hockey + PWHLApi.get_games_for_date",
            "xml": "games.xml",
        },
        {
            "name": "Stats/Team Stats",
            "sources": "_compute_phase_rows from NHLApi/PWHLApi cached daily games",
            "xml": "team_stats.xml",
        },
        {
            "name": "Stats/Game Stats",
            "sources": "_compute_phase_tables from NHLApi/PWHLApi cached daily games",
            "xml": "game_stats.xml",
        },
        {
            "name": "Stats/Player Stats",
            "sources": "NHL leaders + NHL/PWHL aggregates",
            "xml": "player_stats.xml",
        },
        {
            "name": "Stats/Points",
            "sources": "NHLApi score feed or PWHLApi games feed",
            "xml": "points_history.xml",
        },
        {
            "name": "Stats/Goal Differential",
            "sources": "NHLApi score feed or PWHLApi games feed",
            "xml": "goal_differential.xml",
        },
        {
            "name": "Predictions/Pie + Round Tabs",
            "sources": "MoneyPuck simulation CSV compilation",
            "xml": "predictions_<metric>.xml",
        },
        {
            "name": "Models Tabs",
            "sources": "Points history snapshots",
            "xml": "points_history.xml",
        },
    ]
    for e in entries:
        ET.SubElement(
            tabs,
            "tab",
            {
                "name": e["name"],
                "sources": e["sources"],
                "xml": e["xml"],
            },
        )

    _safe_write(ET.ElementTree(root), xml_path)

    flow_path = root_dir / "cache_flowchart.md"
    flow_text = """```mermaid
flowchart TD
  NHL[(NHL API)] --> SCORE[Scoreboard Merge]
  ESPN[(ESPN API)] --> SCORE
  PWHL[(PWHL API)] --> SCORE
  SCORE --> GAMES_XML[[games.xml]]
  GAMES_XML --> TAB_SCORE[Scoreboard Tab]

  NHL --> TEAM_BUILD[Team Stats Builder]
  PWHL --> TEAM_BUILD
  TEAM_BUILD --> TEAM_XML[[team_stats.xml]]
  TEAM_XML --> TAB_TEAM[Team Stats Tab]

  NHL --> GAME_BUILD[Game Stats Builder]
  PWHL --> GAME_BUILD
  GAME_BUILD --> GAME_XML[[game_stats.xml]]
  GAME_XML --> TAB_GAME[Game Stats Tab]

  NHL --> PLAYER_BUILD[Player Stats Builder]
  PWHL --> PLAYER_BUILD
  PLAYER_BUILD --> PLAYER_XML[[player_stats.xml]]
  PLAYER_XML --> TAB_PLAYER[Player Stats Tab]

  NHL --> POINTS_BUILD[Points Builder]
  PWHL --> POINTS_BUILD
  POINTS_BUILD --> POINTS_XML[[points_history.xml]]
  POINTS_XML --> TAB_POINTS[Points Tab]
  POINTS_XML --> TAB_MODELS[Models Tabs]

  NHL --> GD_BUILD[Goal Diff Builder]
  PWHL --> GD_BUILD
  GD_BUILD --> GD_XML[[goal_differential.xml]]
  GD_XML --> TAB_GD[Goal Differential Tab]

  MP[(MoneyPuck Sim CSVs)] --> PRED_BUILD[Predictions Compiler]
  PRED_BUILD --> PRED_XML[[predictions_<metric>.xml]]
  PRED_XML --> TAB_PRED[Pie + Predictions Tabs]
```"""
    _write_text_if_changed(flow_path, flow_text + "\n")


def _game_code(team_obj: dict[str, Any]) -> str:
    return _to_text(
        team_obj.get("abbrev")
        or team_obj.get("abbreviation")
        or team_obj.get("teamAbbrev")
        or ""
    ).upper()


def _game_score(team_obj: dict[str, Any]) -> str:
    n = _to_int(team_obj.get("score"))
    return "" if n is None else str(n)


def _game_shots(team_obj: dict[str, Any]) -> str:
    for k in ("shotsOnGoal", "sog", "shots"):
        n = _to_int(team_obj.get(k))
        if n is not None:
            return str(n)
    return ""


def write_games_day_xml(
    *,
    season: str,
    day: dt.date,
    games: list[dict[str, Any]],
) -> Path:
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
    games_sorted = sorted(
        [g for g in games if isinstance(g, dict)],
        key=lambda g: (
            _to_text(g.get("startTimeUTC") or g.get("startTime")),
            _to_int(g.get("id") or g.get("gameId")) or 0,
        ),
    )
    for g in games_sorted:
        away = g.get("awayTeam") if isinstance(g.get("awayTeam"), dict) else {}
        home = g.get("homeTeam") if isinstance(g.get("homeTeam"), dict) else {}
        gid = _to_text(g.get("id") or g.get("gameId"))
        start_utc = _to_text(g.get("startTimeUTC") or g.get("startTime"))
        game = ET.SubElement(
            day_node,
            "game",
            {
                "id": gid,
                "league": _to_text(g.get("league")),
                "state": _to_text(g.get("gameState") or g.get("gameStatus")).upper(),
                "status_text": _to_text(g.get("statusText")),
                "stage": _to_text(g.get("displayStage")),
                "division": _to_text(g.get("olympicsDivision")),
                "start_utc": start_utc,
                "away_code": _game_code(away),
                "home_code": _game_code(home),
                "away_score": _game_score(away),
                "home_score": _game_score(home),
                "away_shots": _game_shots(away),
                "home_shots": _game_shots(home),
            },
        )
        ET.SubElement(
            game,
            "teams",
            {
                "away_name": _to_text((away.get("name") or {}).get("default") if isinstance(away.get("name"), dict) else away.get("name")),
                "home_name": _to_text((home.get("name") or {}).get("default") if isinstance(home.get("name"), dict) else home.get("name")),
            },
        )

    _sort_games_root(root)
    if _safe_write(tree, path):
        _write_cache_map(season)
    return path


def read_games_day_xml(
    *,
    season: str,
    day: dt.date,
) -> list[dict[str, Any]]:
    path = _xml_path(season, "games")
    if not path.exists():
        return []
    try:
        tree = ET.parse(path)
    except Exception:
        return []
    root = tree.getroot()
    day_node = None
    day_iso = day.isoformat()
    for dnode in root.findall("day"):
        if dnode.get("date") == day_iso:
            day_node = dnode
            break
    if day_node is None:
        return []

    out: list[dict[str, Any]] = []
    for g in day_node.findall("game"):
        away = {
            "abbrev": _to_text(g.get("away_code")).upper(),
            "score": _to_int(g.get("away_score")) or 0,
        }
        home = {
            "abbrev": _to_text(g.get("home_code")).upper(),
            "score": _to_int(g.get("home_score")) or 0,
        }
        ashot = _to_int(g.get("away_shots"))
        hshot = _to_int(g.get("home_shots"))
        if ashot is not None:
            away["shotsOnGoal"] = ashot
        if hshot is not None:
            home["shotsOnGoal"] = hshot
        teams = g.find("teams")
        if teams is not None:
            aname = _to_text(teams.get("away_name"))
            hname = _to_text(teams.get("home_name"))
            if aname:
                away["name"] = {"default": aname}
            if hname:
                home["name"] = {"default": hname}

        row: dict[str, Any] = {
            "id": _to_int(g.get("id")) or 0,
            "league": _to_text(g.get("league")),
            "gameState": _to_text(g.get("state")).upper(),
            "statusText": _to_text(g.get("status_text")),
            "displayStage": _to_text(g.get("stage")),
            "olympicsDivision": _to_text(g.get("division")),
            "startTimeUTC": _to_text(g.get("start_utc")),
            "awayTeam": away,
            "homeTeam": home,
        }
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
) -> Path:
    path = _xml_path(season, lump)
    tree, root = _read_or_new(path)
    root.set("season", str(season))
    root.set("lump", str(lump))
    root.set("league", str(league).upper())
    root.set("start", start.isoformat())
    root.set("end", end.isoformat())
    root.set("updated_at", _now_iso())

    for node in list(root):
        root.remove(node)

    ordered_cols = _ordered_labels_by_date([str(c) for c in list(df.columns)], season_start=start)
    if ordered_cols and ordered_cols != [str(c) for c in list(df.columns)]:
        try:
            df = df.loc[:, ordered_cols]
        except Exception:
            pass

    cols = ET.SubElement(root, "columns")
    for idx, col in enumerate([str(c) for c in list(df.columns)]):
        ET.SubElement(cols, "col", {"idx": str(idx), "label": str(col)})

    teams = ET.SubElement(root, "teams")
    for team_code in [str(i) for i in list(df.index)]:
        team_node = ET.SubElement(teams, "team", {"code": team_code})
        row = df.loc[team_code]
        values = row.tolist() if hasattr(row, "tolist") else []
        for idx, v in enumerate(values):
            if pd.isna(v):
                continue
            ET.SubElement(team_node, "v", {"cidx": str(idx), "value": f"{float(v):.6f}"})

    _sort_table_root(root)
    if _safe_write(tree, path):
        _write_cache_map(season)
    return path


def read_table_xml(
    *,
    season: str,
    lump: str,
    league: str | None = None,
) -> pd.DataFrame | None:
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

    col_nodes = list((root.find("columns") or ET.Element("columns")).findall("col"))
    if not col_nodes:
        return None
    columns = [str(n.get("label") or "") for n in sorted(col_nodes, key=lambda n: _to_int(n.get("idx")) or 0)]
    if not columns:
        return None

    rows: list[list[float]] = []
    idx: list[str] = []
    for tnode in (root.find("teams") or ET.Element("teams")).findall("team"):
        code = _to_text(tnode.get("code")).upper()
        if not code:
            continue
        vals: list[float] = [float("nan")] * len(columns)
        for vnode in tnode.findall("v"):
            cidx = _to_int(vnode.get("cidx"))
            if cidx is None or cidx < 0 or cidx >= len(columns):
                continue
            try:
                vals[cidx] = float(_to_text(vnode.get("value")))
            except Exception:
                continue
        idx.append(code)
        rows.append(vals)
    if not idx:
        return None
    try:
        return pd.DataFrame(rows, index=idx, columns=columns, dtype="float64")
    except Exception:
        return None


def write_team_stats_xml(
    *,
    season: str,
    league: str,
    phase_rows: dict[str, dict[str, Any]],
) -> Path:
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
        phase_node = ET.SubElement(root, "phase", {"name": phase})
        rows_by_date = blob.get("rows_by_date")
        if not isinstance(rows_by_date, dict):
            continue
        for d in sorted(rows_by_date.keys(), key=_date_sort_key):
            rows = rows_by_date.get(d) or []
            if not isinstance(rows, list):
                continue
            d_node = ET.SubElement(phase_node, "day", {"date": d.isoformat() if isinstance(d, dt.date) else str(d)})
            rows_sorted = sorted(
                [r for r in rows if isinstance(r, dict)],
                key=lambda r: _to_text(r.get("team")).upper(),
            )
            for row in rows_sorted:
                if not isinstance(row, dict):
                    continue
                r = ET.SubElement(
                    d_node,
                    "team",
                    {
                        "code": _to_text(row.get("team")).upper(),
                        "record": _to_text(row.get("record")),
                    },
                )
                for k, v in row.items():
                    if k in {"team", "record"}:
                        continue
                    if v is None:
                        continue
                    ET.SubElement(r, "stat", {"name": str(k), "value": _to_text(v)})

    _sort_team_stats_root(root)
    if _safe_write(tree, path):
        _write_cache_map(season)
    return path


def read_team_stats_xml(
    *,
    season: str,
    league: str | None = None,
) -> dict[str, dict[str, Any]] | None:
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
    for pnode in root.findall("phase"):
        phase = _to_text(pnode.get("name"))
        if not phase:
            continue
        dates: list[dt.date] = []
        rows_by_date: dict[dt.date, list[dict[str, Any]]] = {}
        for dnode in pnode.findall("day"):
            dtxt = _to_text(dnode.get("date"))
            try:
                dval = dt.date.fromisoformat(dtxt)
            except Exception:
                continue
            rows: list[dict[str, Any]] = []
            for tnode in dnode.findall("team"):
                row: dict[str, Any] = {
                    "team": _to_text(tnode.get("code")).upper(),
                    "record": _to_text(tnode.get("record")),
                }
                for snode in tnode.findall("stat"):
                    nm = _to_text(snode.get("name"))
                    val = _to_text(snode.get("value"))
                    if not nm:
                        continue
                    # Restore numeric fields when possible.
                    try:
                        if "." in val:
                            row[nm] = float(val)
                        else:
                            row[nm] = int(val)
                    except Exception:
                        row[nm] = val
                rows.append(row)
            dates.append(dval)
            rows_by_date[dval] = rows
        out[phase] = {"dates": sorted(dates), "rows_by_date": rows_by_date}
    return out or None


def write_game_stats_xml(
    *,
    season: str,
    league: str,
    phase_tables: dict[str, dict[str, Any]],
) -> Path:
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
        cols = blob.get("date_cols") if isinstance(blob.get("date_cols"), list) else []
        cols = _ordered_labels_by_date(
            [str(c) for c in cols],
            season_start=_season_start_anchor(season),
        )
        rows = blob.get("rows") if isinstance(blob.get("rows"), list) else []
        phase_node = ET.SubElement(root, "phase", {"name": phase})
        cols_node = ET.SubElement(phase_node, "columns")
        for idx, col in enumerate(cols):
            ET.SubElement(cols_node, "col", {"idx": str(idx), "label": str(col)})
        teams_node = ET.SubElement(phase_node, "teams")
        rows_sorted = sorted(
            [r for r in rows if isinstance(r, dict)],
            key=lambda r: _to_text(r.get("team")).upper(),
        )
        for row in rows_sorted:
            if not isinstance(row, dict):
                continue
            code = _to_text(row.get("team")).upper()
            if not code:
                continue
            tnode = ET.SubElement(teams_node, "team", {"code": code})
            for idx, col in enumerate(cols):
                val = _to_text(row.get(col))
                if not val:
                    continue
                ET.SubElement(tnode, "g", {"cidx": str(idx), "result": val})

    _sort_game_stats_root(root)
    if _safe_write(tree, path):
        _write_cache_map(season)
    return path


def read_game_stats_xml(
    *,
    season: str,
    league: str | None = None,
) -> dict[str, dict[str, Any]] | None:
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
    for pnode in root.findall("phase"):
        phase = _to_text(pnode.get("name"))
        if not phase:
            continue
        cols = [str(c.get("label") or "") for c in sorted((pnode.find("columns") or ET.Element("columns")).findall("col"), key=lambda n: _to_int(n.get("idx")) or 0)]
        rows: list[dict[str, str]] = []
        for tnode in (pnode.find("teams") or ET.Element("teams")).findall("team"):
            code = _to_text(tnode.get("code")).upper()
            if not code:
                continue
            row: dict[str, str] = {"team": code}
            for gnode in tnode.findall("g"):
                idx = _to_int(gnode.get("cidx"))
                if idx is None or idx < 0 or idx >= len(cols):
                    continue
                row[cols[idx]] = _to_text(gnode.get("result"))
            rows.append(row)
        out[phase] = {"date_cols": cols, "rows": rows, "games_by_team_col": {}}
    return out or None


def write_player_stats_xml(
    *,
    season: str,
    league: str,
    payload: dict[str, Any],
) -> Path:
    path = _xml_path(season, "player_stats")
    tree, root = _read_or_new(path)
    root.set("season", str(season))
    root.set("lump", "player_stats")
    root.set("league", str(league).upper())
    root.set("date", _to_text(payload.get("date")))
    root.set("updated_at", _to_text(payload.get("updated")) or _now_iso())

    for node in list(root):
        root.remove(node)

    skaters = payload.get("skaters") if isinstance(payload.get("skaters"), dict) else {}
    goalies = payload.get("goalies") if isinstance(payload.get("goalies"), dict) else {}

    for group_name, rows in (("skaters", skaters), ("goalies", goalies)):
        gnode = ET.SubElement(root, "group", {"name": group_name})
        for name in sorted(rows.keys()):
            vals = rows.get(name)
            if not isinstance(vals, dict):
                continue
            pnode = ET.SubElement(
                gnode,
                "player",
                {
                    "name": str(name),
                    "team": _to_text(vals.get("team")).upper(),
                    "pid": _to_text(vals.get("_pid")),
                },
            )
            for k in sorted(vals.keys()):
                v = vals.get(k)
                if k in {"team", "_pid"}:
                    continue
                if v is None:
                    continue
                ET.SubElement(pnode, "stat", {"name": str(k), "value": _to_text(v)})

    _sort_player_stats_root(root)
    if _safe_write(tree, path):
        _write_cache_map(season)
    return path


def read_player_stats_xml(
    *,
    season: str,
    league: str | None = None,
) -> dict[str, Any] | None:
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

    out: dict[str, Any] = {
        "date": _to_text(root.get("date")),
        "league": _to_text(root.get("league")).upper(),
        "updated": _to_text(root.get("updated_at")),
        "skaters": {},
        "goalies": {},
    }
    for gnode in root.findall("group"):
        gname = _to_text(gnode.get("name"))
        if gname not in {"skaters", "goalies"}:
            continue
        group: dict[str, dict[str, Any]] = {}
        for pnode in gnode.findall("player"):
            pname = _to_text(pnode.get("name"))
            if not pname:
                continue
            vals: dict[str, Any] = {
                "team": _to_text(pnode.get("team")).upper(),
                "_pid": _to_int(pnode.get("pid")) or 0,
            }
            for snode in pnode.findall("stat"):
                nm = _to_text(snode.get("name"))
                val = _to_text(snode.get("value"))
                if not nm:
                    continue
                try:
                    vals[nm] = float(val)
                except Exception:
                    vals[nm] = val
            group[pname] = vals
        out[gname] = group
    return out


def write_predictions_tables_xml(
    *,
    season: str,
    start: dt.date,
    end: dt.date,
    tables: dict[str, pd.DataFrame],
) -> list[Path]:
    out: list[Path] = []
    for metric, df in tables.items():
        if not isinstance(df, pd.DataFrame):
            continue
        lump = f"predictions_{str(metric)}"
        out.append(
            write_table_xml(
                season=season,
                lump=lump,
                league="NHL",
                start=start,
                end=end,
                df=df,
            )
        )
    return out


def read_predictions_tables_xml(
    *,
    season: str,
    metrics: list[str] | None = None,
) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    if metrics is None:
        metrics = []
        for p in _xml_season_dir(season).glob("predictions_*.xml"):
            stem = p.stem
            if stem.startswith("predictions_"):
                metrics.append(stem.replace("predictions_", "", 1))
    for metric in metrics:
        lump = f"predictions_{metric}"
        df = read_table_xml(season=season, lump=lump)
        if isinstance(df, pd.DataFrame) and not df.empty and len(df.columns) > 0:
            out[metric] = df
    return out
