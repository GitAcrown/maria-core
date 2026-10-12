"""Matchs API-Football ou TheSportsDB -> données compactes et cartes."""

import unicodedata
from collections.abc import Mapping
from typing import Any

from maria_core.ui.widgets import Card, Rendered, card, footer, heading, stats, text

_LIVE = frozenset({"1H", "2H", "ET", "BT", "P", "LIVE", "INT"})
_DONE = frozenset({"FT", "AET", "PEN"})
_STATUS = {
    "HT": "Mi-temps",
    "NS": "À venir",
    "TBD": "À venir",
    "PST": "Reporté",
    "CANC": "Annulé",
    "ABD": "Abandonné",
    "SUSP": "Suspendu",
    "AWD": "Forfait",
    "WO": "Forfait",
}
_STATS = (
    ("Ball Possession", "Possession"),
    ("Total Shots", "Tirs"),
    ("Shots on Goal", "Cadrés"),
    ("Corner Kicks", "Corners"),
)
_GREEN = 0x2E7D32


def name_matches(target: str, candidate: str) -> bool:
    wanted, found = _fold(target), _fold(candidate)
    return bool(wanted) and (wanted in found or found in wanted)


def normalize(data: Mapping[str, Any]) -> dict[str, Any]:
    mode = str(data.get("mode") or "")
    if mode == "match":
        return {"mode": "match", "match": _api_match(data.get("match") or {})}
    if mode in {"list", "live"}:
        rows = [_api_match(item) for item in data.get("matches") or []]
        return {"mode": mode, "title": str(data.get("title") or "En direct"), "matches": rows}
    rows = [_tsdb_match(item) for item in data.get("matches") or []]
    return {"mode": "list", "title": str(data.get("title") or ""), "matches": rows}


def render_football(data: Mapping[str, Any]) -> Rendered:
    if data.get("mode") == "match":
        match = data.get("match") or {}
        return Rendered(cards=(_match_card(match),), note=_line(match))
    matches = [item for item in data.get("matches") or [] if isinstance(item, dict)]
    title = str(data.get("title") or "Matchs")
    lines = [f"- {_line(item)}" for item in matches[:10]]
    built = card(heading(f"⚽ {title}"), text("\n".join(lines) or "Aucun match."), accent=_GREEN)
    return Rendered(cards=(built,), note=f"{title} : " + " ; ".join(_line(m) for m in matches[:5]))


def _match_card(match: Mapping[str, Any]) -> Card:
    head = f"{match.get('home')} {match.get('score')} {match.get('away')}"
    meta = " · ".join(part for part in (match.get("status"), match.get("league")) if part)
    blocks = [heading(f"⚽ {head}", meta)]
    scorers = match.get("scorers") or {}
    lines = [f"**{team}** : {', '.join(names)}" for team, names in scorers.items() if names]
    if lines:
        blocks.append(text("\n".join(lines)))
    if match.get("stats"):
        blocks.append(stats(list(match["stats"])))
    if match.get("kickoff"):
        blocks.append(footer(f"Coup d'envoi {match['kickoff']}"))
    return card(*blocks, accent=_GREEN)


def _api_match(raw: Mapping[str, Any]) -> dict[str, Any]:
    fixture = raw.get("fixture") or {}
    teams = raw.get("teams") or {}
    goals = raw.get("goals") or {}
    home = str((teams.get("home") or {}).get("name") or "?")
    away = str((teams.get("away") or {}).get("name") or "?")
    return {
        "home": home,
        "away": away,
        "score": _score(goals.get("home"), goals.get("away")),
        "status": _status(fixture.get("status") or {}),
        "league": str((raw.get("league") or {}).get("name") or ""),
        "kickoff": _kickoff(fixture.get("timestamp")),
        "scorers": _scorers(raw.get("events") or []),
        "stats": _stats(raw.get("statistics") or [], home, away),
    }


def _tsdb_match(raw: Mapping[str, Any]) -> dict[str, Any]:
    when = " ".join(str(part) for part in (raw.get("dateEvent"), raw.get("strTime")) if part)
    return {
        "home": str(raw.get("strHomeTeam") or "?"),
        "away": str(raw.get("strAwayTeam") or "?"),
        "score": _score(raw.get("intHomeScore"), raw.get("intAwayScore")),
        "status": str(raw.get("strStatus") or ""),
        "league": str(raw.get("strLeague") or ""),
        "kickoff": when,
        "scorers": {},
        "stats": [],
    }


def _status(status: Mapping[str, Any]) -> str:
    short = str(status.get("short") or "")
    elapsed = status.get("elapsed")
    if short in _LIVE:
        return f"🔴 EN DIRECT · {elapsed}'" if elapsed else "🔴 EN DIRECT"
    if short in _DONE:
        return "Terminé" + {"AET": " (a.p.)", "PEN": " (t.a.b.)"}.get(short, "")
    return _STATUS.get(short, short)


def _scorers(events: list[Any]) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for event in events:
        if not isinstance(event, dict) or event.get("type") != "Goal":
            continue
        detail = str(event.get("detail") or "")
        if detail == "Missed Penalty":
            continue
        team = str((event.get("team") or {}).get("name") or "")
        player = str((event.get("player") or {}).get("name") or "?")
        minute = (event.get("time") or {}).get("elapsed")
        tag = {"Own Goal": " (csc)", "Penalty": " (pen)"}.get(detail, "")
        found.setdefault(team, []).append(f"{player} {minute}'{tag}" if minute else player)
    return found


def _stats(blocks: list[Any], home: str, away: str) -> list[tuple[str, str]]:
    values: dict[str, dict[str, str]] = {}
    for block in blocks:
        if not isinstance(block, dict):
            continue
        team = str((block.get("team") or {}).get("name") or "")
        for item in block.get("statistics") or []:
            if isinstance(item, dict):
                values.setdefault(str(item.get("type")), {})[team] = str(item.get("value") or 0)
    pairs = []
    for key, label in _STATS:
        found = values.get(key)
        if found:
            pairs.append((label, f"{found.get(home, '?')} - {found.get(away, '?')}"))
    return pairs


def _line(match: Mapping[str, Any]) -> str:
    status = f" ({match.get('status')})" if match.get("status") else ""
    when = f"{match.get('kickoff')} " if match.get("kickoff") and match.get("score") == "-" else ""
    return f"{when}{match.get('home')} {match.get('score')} {match.get('away')}{status}"


def _score(home: object, away: object) -> str:
    if home in {None, ""} or away in {None, ""}:
        return "-"
    return f"{home}-{away}"


def _kickoff(raw: object) -> str:
    if not isinstance(raw, int):
        return ""
    return f"<t:{raw}:F>" if raw > 0 else ""


def _fold(name: str) -> str:
    decomposed = unicodedata.normalize("NFKD", name or "")
    letters = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(letters.casefold().replace("fc", " ").split())
