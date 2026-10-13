"""Textes Navitia : horaires, perturbations, et la carte affichée. Repris de MARIA_R."""

import html
import re
import unicodedata
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from maria_core.ui.emojis import TRAIN
from maria_core.ui.widgets import Card, Rendered, card, footer, separator, text

PARIS = ZoneInfo("Europe/Paris")
_MODE_RANK = {
    "métro": 0,
    "metro": 0,
    "rer": 1,
    "train": 2,
    "transilien": 2,
    "tramway": 3,
    "tram": 3,
    "bus": 4,
}
_SKIP_CHANNELS = {"pids", "cbiv"}
_TITLE_CHANNELS = {"title", "titre", "notification"}
_NOTE_LIMIT = 900


def parse_time(raw: str) -> datetime | None:
    try:
        return datetime.strptime((raw or "")[:15], "%Y%m%dT%H%M%S").replace(tzinfo=PARIS)
    except ValueError:
        return None


def wait_label(moment: datetime, now: datetime) -> str:
    seconds = (moment - now).total_seconds()
    if seconds < 45:
        return "imminent"
    minutes = round(seconds / 60)
    return moment.strftime("%H:%M") if minutes >= 60 else f"{max(1, minutes)} min"


def mode_rank(mode: str) -> int:
    return _MODE_RANK.get((mode or "").lower(), 5)


def fold(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value or "")
    letters = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(
        letters.lower().replace("'", " ").replace("\u2019", " ").replace("-", " ").split()
    )


def name_bonus(query: str, name: str) -> int:
    wanted, found = fold(query), fold((name or "").split("(")[0])
    if not wanted or not found:
        return 0
    if wanted == found:
        return 80
    if found.startswith(wanted) or wanted.startswith(found):
        return 40 - 8 * len(set(found.split()) - set(wanted.split()))
    return 0


def plain(raw: str, *, breaks: bool = False) -> str:
    value = re.sub(r"(?i)<br\s*/?>|</p\s*>", "\n" if breaks else " ", raw or "")
    value = html.unescape(re.sub(r"<[^>]+>", " " if not breaks else "", value))
    if not breaks:
        return " ".join(value.split())
    lines = [" ".join(line.split()) for line in value.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def disruption_copy(messages: list[Any]) -> str:
    title, body = "", ""
    for message in messages or []:
        if not isinstance(message, Mapping):
            continue
        channel = message.get("channel") or {}
        kinds = {str(item).lower() for item in channel.get("types") or []}
        name = str(channel.get("name") or "").strip().lower()
        if kinds & _SKIP_CHANNELS or name in _SKIP_CHANNELS:
            continue
        content = plain(str(message.get("text") or ""), breaks=True)
        if not content:
            continue
        if "title" in kinds or name in _TITLE_CHANNELS:
            title = title or " ".join(content.split())
        elif len(content) > len(body):
            body = content
    if not body:
        return title
    body = body if len(body) <= _NOTE_LIMIT else body[: _NOTE_LIMIT - 1].rstrip() + "…"
    if title and title.casefold() not in body[: len(title) + 40].casefold():
        return f"**{title}**\n{body}"
    return body


def render_transport(data: Mapping[str, Any]) -> Rendered:
    if data.get("kind") == "departures":
        return Rendered(cards=(_departures(data),), note=_departures_note(data))
    notes = [str(item) for item in data.get("notes") or []]
    blocks = [text(f"## {TRAIN} {data.get('title') or 'Trafic'}")]
    if data.get("status"):
        blocks.append(text(str(data["status"])))
    blocks.append(separator(wide=True))
    for index, note in enumerate(notes or ["Trafic normal."]):
        if index:
            blocks.append(separator())
        blocks.append(text(note))
    blocks.append(footer(str(data.get("source") or "IDFM")))
    summary = f"{data.get('title')} : {data.get('status')}. " + " | ".join(
        n[:160] for n in notes[:3]
    )
    return Rendered(cards=(card(*blocks),), note=summary)


def _departures(data: Mapping[str, Any]) -> Card:
    lines = []
    for row in data.get("rows") or []:
        if not isinstance(row, dict):
            continue
        head = f"**{row.get('code') or '?'}**"
        mode = str(row.get("mode") or "")
        if mode and mode.lower() not in str(row.get("code") or "").lower():
            head = f"{head} · {mode}"
        line = f"{head}  {row['direction']}" if row.get("direction") else head
        if row.get("waits"):
            line = f"{line}  ·  {' · '.join(row['waits'])}"
        lines.append(line)
    stamp = "temps réel" if data.get("realtime") else "horaire"
    return card(
        text(f"## {TRAIN} {data.get('stop') or 'Arrêt'}\n-# Prochains passages"),
        separator(wide=True),
        text("\n".join(lines) if lines else "-# Aucun passage proche."),
        footer(f"{stamp} · {data.get('source') or 'IDFM'}"),
    )


def _departures_note(data: Mapping[str, Any]) -> str:
    rows = [row for row in data.get("rows") or [] if isinstance(row, dict)]
    bits = [f"{row['code']} {row['direction']} ({', '.join(row['waits'])})" for row in rows[:5]]
    return f"Prochains passages à {data.get('stop')} : " + "; ".join(bits)
