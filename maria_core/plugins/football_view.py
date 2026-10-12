"""Matchs API-Football ou TheSportsDB -> données compactes et cartes, comme dans MARIA_R."""

import unicodedata
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from maria_core.ui.emojis import DIRECT, FOOTBALL, FOOTBALL_PLAYER
from maria_core.ui.widgets import Card, Rendered, card, footer, separator, text

_LIVE = frozenset({"1H", "2H", "ET", "BT", "P", "LIVE", "INT"})
_DONE = frozenset({"FT", "AET", "PEN"})
_STARTED = _LIVE | _DONE | {"HT"}
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
    ("Shots on Goal", "Tirs cadrés"),
    ("Corner Kicks", "Corners"),
    ("Yellow Cards", "Cartons jaunes"),
    ("Red Cards", "Cartons rouges"),
)
_TSDB_DONE = frozenset({"Match Finished", "FT", "AET", "After Extra Time", "Pen", "PEN"})


def name_matches(target: str, candidate: str) -> bool:
    wanted, found = _fold(target), _fold(candidate)
    return bool(wanted) and bool(found) and (wanted == found or wanted in found or found in wanted)


def normalize(data: Mapping[str, Any]) -> dict[str, Any]:
    mode = str(data.get("mode") or "")
    if mode == "match":
        return {"mode": "match", "match": _api_match(data.get("match") or {})}
    if mode == "live":
        rows = [_api_match(item) for item in data.get("matches") or []]
        return {"mode": "live", "matches": rows}
    if mode == "list":
        rows = [_api_match(item) for item in data.get("matches") or []]
        return {"mode": "list", "title": str(data.get("title") or ""), "matches": rows}
    rows = [_tsdb_match(item) for item in data.get("matches") or []]
    if data.get("single") and rows:
        return {"mode": "match", "match": rows[0]}
    return {"mode": "list", "title": str(data.get("title") or ""), "matches": rows}


def render_football(data: Mapping[str, Any]) -> Rendered:
    mode = data.get("mode")
    matches = [item for item in data.get("matches") or [] if isinstance(item, dict)]
    if mode == "match":
        match = data.get("match") or {}
        return Rendered(cards=(_match_card(match),), note=_line(match))
    if mode == "live":
        return Rendered(cards=(_live_card(matches),), note=_notes("En direct", matches))
    title = str(data.get("title") or "")
    return Rendered(cards=(_list_card(title, matches),), note=_notes(title, matches))


def _match_card(match: Mapping[str, Any]) -> Card:
    round_name = f"  ·  {match['round']}" if match.get("round") else ""
    blocks = [
        text(
            f"## {FOOTBALL} {match.get('league') or 'Football'}\n-# {match['status']}{round_name}"
        ),
        separator(wide=True),
        text(_score_line(match)),
    ]
    scorers = match.get("scorers") or {}
    lines = [
        f"**{team}**  ·  {', '.join(scorers[team])}"
        for team in (match["home"], match["away"])
        if scorers.get(team)
    ]
    if lines:
        blocks += [separator(), text(f"{FOOTBALL_PLAYER} " + f"\n{FOOTBALL_PLAYER} ".join(lines))]
    if match.get("stats"):
        stat_lines = [f"-# {label} · {home} — {away}" for label, home, away in match["stats"]]
        blocks += [separator(), text("\n".join(stat_lines))]
    blocks.append(footer(str(match.get("source") or "API-Football")))
    return card(*blocks)


def _list_card(title: str, matches: list[dict[str, Any]]) -> Card:
    lines = []
    for match in matches[:5]:
        score = match["score"] if match.get("started") else "vs"
        date = f"  `{match['day']}`" if match.get("day") else ""
        lines.append(f"{match['home']} **{score}** {match['away']}{date}")
    source = matches[0].get("source") if matches else "TheSportsDB"
    return card(
        text(f"## {FOOTBALL} Derniers matchs · {title}"),
        separator(wide=True),
        text("\n".join(lines) if lines else "-# Aucun match récent."),
        footer(str(source)),
    )


def _live_card(matches: list[dict[str, Any]]) -> Card:
    lines = []
    for match in matches[:10]:
        minute = f"`{match['elapsed']}'`" if match.get("elapsed") else "`live`"
        lines.append(f"{minute}  {match['home']} **{match['score']}** {match['away']}")
    return card(
        text(f"## {FOOTBALL} Matchs en direct"),
        separator(wide=True),
        text("\n".join(lines) if lines else "-# Aucun match en direct pour le moment."),
        footer("API-Football"),
    )


def _score_line(match: Mapping[str, Any]) -> str:
    if match.get("started"):
        return f"### {match['home']}  **{match['score']}**  {match['away']}"
    line = f"### {match['home']}  vs  {match['away']}"
    return f"{line}\n-# {match['kickoff']}" if match.get("kickoff") else line


def _api_match(raw: Mapping[str, Any]) -> dict[str, Any]:
    fixture = raw.get("fixture") or {}
    teams = raw.get("teams") or {}
    goals = raw.get("goals") or {}
    status = fixture.get("status") or {}
    home = str((teams.get("home") or {}).get("name") or "?")
    away = str((teams.get("away") or {}).get("name") or "?")
    short = str(status.get("short") or "")
    timestamp = fixture.get("timestamp")
    return {
        "home": home,
        "away": away,
        "score": f"{goals.get('home')} - {goals.get('away')}",
        "started": short in _STARTED,
        "status": _status(short, status.get("elapsed")),
        "elapsed": status.get("elapsed") if short in _LIVE else None,
        "league": str((raw.get("league") or {}).get("name") or ""),
        "round": str((raw.get("league") or {}).get("round") or ""),
        "kickoff": f"<t:{timestamp}:F>" if isinstance(timestamp, int) else "",
        "day": datetime.fromtimestamp(timestamp).strftime("%d/%m")
        if isinstance(timestamp, int)
        else "",
        "scorers": _scorers(raw.get("events") or []),
        "stats": _stats(raw.get("statistics") or [], home, away) if short in _LIVE else [],
        "source": "API-Football",
    }


def _tsdb_match(raw: Mapping[str, Any]) -> dict[str, Any]:
    home_goals, away_goals = raw.get("intHomeScore"), raw.get("intAwayScore")
    started = home_goals not in {None, ""} and away_goals not in {None, ""}
    day = str(raw.get("dateEvent") or "")
    return {
        "home": str(raw.get("strHomeTeam") or "?"),
        "away": str(raw.get("strAwayTeam") or "?"),
        "score": f"{home_goals} - {away_goals}" if started else "vs",
        "started": started,
        "status": "Terminé" if str(raw.get("strStatus") or "") in _TSDB_DONE else "À venir",
        "elapsed": None,
        "league": str(raw.get("strLeague") or ""),
        "round": "",
        "kickoff": " ".join(part for part in (day, str(raw.get("strTime") or "")[:5]) if part),
        "day": f"{day[8:10]}/{day[5:7]}" if len(day) == 10 else "",
        "scorers": {},
        "stats": [],
        "source": "TheSportsDB",
    }


def _status(short: str, elapsed: object) -> str:
    if short in _LIVE:
        return f"{DIRECT} EN DIRECT · {elapsed}'" if elapsed else f"{DIRECT} EN DIRECT"
    if short in _DONE:
        return "Terminé" + {"AET": " (a.p.)", "PEN": " (t.a.b.)"}.get(short, "")
    return _STATUS.get(short, short or "?")


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
        timing = event.get("time") or {}
        minute = f"{timing.get('elapsed')}'" if timing.get("elapsed") else ""
        if timing.get("extra"):
            minute += f"+{timing['extra']}"
        tag = {"Own Goal": " (csc)", "Penalty": " (pen)"}.get(detail, "")
        found.setdefault(team, []).append(f"{player} {minute}{tag}".strip())
    return found


def _stats(blocks: list[Any], home: str, away: str) -> list[tuple[str, str, str]]:
    values: dict[str, dict[str, str]] = {}
    for block in blocks:
        if not isinstance(block, dict):
            continue
        team = str((block.get("team") or {}).get("name") or "")
        for item in block.get("statistics") or []:
            if isinstance(item, dict) and item.get("value") is not None:
                values.setdefault(str(item.get("type")), {})[team] = str(item["value"])
    return [
        (label, values[key].get(home, "0"), values[key].get(away, "0"))
        for key, label in _STATS
        if key in values
    ]


def _line(match: Mapping[str, Any]) -> str:
    score = match.get("score") if match.get("started") else "vs"
    return f"{match.get('home')} {score} {match.get('away')} ({match.get('status')})"


def _notes(title: str, matches: list[dict[str, Any]]) -> str:
    return f"{title} : " + " ; ".join(_line(match) for match in matches[:5])


def _fold(name: str) -> str:
    decomposed = unicodedata.normalize("NFKD", name or "")
    letters = "".join(char for char in decomposed if not unicodedata.combining(char))
    return "".join(char for char in letters.casefold() if char.isalnum())
