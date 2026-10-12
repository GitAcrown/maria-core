"""Déclencheurs MARIA_R -> déclencheurs d'objectif : horloge, veille, écoute, signal vocal."""

import json
import sqlite3

from maria_core.legacy.model import Skip
from maria_core.legacy.read import as_dict, cell, moment
from maria_core.objectives.schedule import PARIS, clock_text, weekdays

_SOURCE = "tâche"
_DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_SIGNALS = frozenset({"voice_join", "voice_leave", "voice_stream", "member_join"})
_SIGNAL_ALIASES = {
    "stream": "voice_stream",
    "golive": "voice_stream",
    "go_live": "voice_stream",
    "live": "voice_stream",
    "join_voice": "voice_join",
    "leave_voice": "voice_leave",
}
_VOICE = {"voice_join": "join", "voice_leave": "leave", "voice_stream": "stream"}
_AUTHORS = {"any": "any", "self": "self", "not_self": "others", "": "others"}
_DEFAULT_WATCH_MINUTES = 6 * 60


def trigger_of(row: sqlite3.Row, kind: str) -> tuple[dict[str, object], str] | Skip:
    if kind == "event":
        return _event_trigger(row)
    if kind == "watch":
        return _watch_trigger(row)
    if kind == "recurring":
        return _clock_trigger(row)
    if kind == "at":
        return _at_trigger(row)
    return skip_task(row, f"type non porté ({kind})")


def _event_trigger(row: sqlite3.Row) -> tuple[dict[str, object], str] | Skip:
    trigger = as_dict(cell(row, "trigger_json", ""))
    signal = _signal(trigger)
    if signal:
        return _signal_trigger(row, trigger, signal)
    pattern = str(trigger.get("pattern") or "").strip()
    topic = str(trigger.get("topic") or "").strip()
    if pattern.split(":", 1)[0] in _SIGNALS or not (pattern or topic):
        return skip_task(row, "écoute sans motif")
    built: dict[str, object] = {"type": "on_topic", "author": _author(trigger)}
    if pattern:
        built["pattern"] = pattern
        aliases = trigger.get("aliases")
        if isinstance(aliases, list):
            built["aliases"] = [str(item).strip() for item in aliases if str(item).strip()][:7]
    if topic:
        built["topic"] = topic[:200]
    built["repeat"] = count(row, "max_fires") != 1
    return built, ""


def _signal_trigger(
    row: sqlite3.Row, trigger: dict[str, object], signal: str
) -> tuple[dict[str, object], str] | Skip:
    if signal == "member_join":
        return {"type": "on_member_join", "repeat": count(row, "max_fires") != 1}, ""
    built: dict[str, object] = {"type": "on_voice", "signal": _VOICE[signal]}
    target = str(trigger.get("user_id") or "").strip()
    if target in {"self", "me", "moi"}:
        target = str(cell(row, "user_id", "") or "")
    if target.isdigit():
        built["user_id"] = int(target)
    place = str(trigger.get("voice_channel_id") or "").strip()
    if place.isdigit() and int(place) > 0:
        built["voice_channel_id"] = int(place)
    built["repeat"] = bool(trigger.get("repeat")) or count(row, "max_fires") != 1
    return built, ""


def _author(trigger: dict[str, object]) -> str:
    raw = str(trigger.get("author") or "").strip().casefold()
    if raw.isdigit():
        return raw
    return _AUTHORS.get(raw, "others")


def _watch_trigger(row: sqlite3.Row) -> tuple[dict[str, object], str] | Skip:
    raw = as_dict(cell(row, "trigger_json", ""))
    minutes = raw.get("interval_minutes")
    notice = ""
    if minutes is None or minutes == "":
        minutes = _DEFAULT_WATCH_MINUTES
        notice = "intervalle par défaut de 6 h"
    try:
        value = int(str(minutes))
    except ValueError:
        return skip_task(row, "intervalle illisible")
    if value < 1:
        return skip_task(row, "intervalle illisible")
    return {"type": "interval", "every_s": value * 60}, notice


def _clock_trigger(row: sqlite3.Row) -> tuple[dict[str, object], str] | Skip:
    schedule = str(cell(row, "schedule_kind", "once") or "once")
    clock = _clock(row)
    if isinstance(clock, Skip):
        return clock
    if schedule == "daily":
        return {"type": "daily", "time": clock}, ""
    if schedule != "weekly":
        return skip_task(row, "récurrence sans rythme")
    days = _days(row)
    if isinstance(days, Skip):
        return days
    found, notice = days
    return {"type": "weekly", "time": clock, "weekdays": list(found)}, notice


def _at_trigger(row: sqlite3.Row) -> tuple[dict[str, object], str] | Skip:
    when = moment(cell(row, "execute_at", ""))
    if when is None:
        return skip_task(row, "date illisible")
    return {"type": "at", "at": when.isoformat()}, ""


def _clock(row: sqlite3.Row) -> str | Skip:
    raw = str(cell(row, "time_of_day", "")).strip()
    if not raw:
        when = moment(cell(row, "execute_at", ""))
        if when is None:
            return skip_task(row, "heure illisible")
        local = when.astimezone(PARIS)
        raw = f"{local.hour:02d}:{local.minute:02d}"
    try:
        return clock_text(raw)
    except ValueError:
        return skip_task(row, "heure illisible")


def _days(row: sqlite3.Row) -> tuple[tuple[str, ...], str] | Skip:
    raw = cell(row, "weekdays", "[]")
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError:
        parsed = []
    found = weekdays(parsed)
    if found:
        return found, ""
    when = moment(cell(row, "execute_at", ""))
    if when is None:
        return skip_task(row, "jours illisibles")
    return (_DAYS[when.astimezone(PARIS).weekday()],), "jour repris de la date d'exécution"


def _signal(trigger: dict[str, object]) -> str:
    for key in ("signal", "type"):
        token = str(trigger.get(key) or "").strip().casefold().replace("-", "_").replace(" ", "_")
        token = _SIGNAL_ALIASES.get(token, token)
        if token in _SIGNALS:
            return token
    return ""


def count(row: sqlite3.Row, key: str) -> int:
    try:
        return max(0, int(str(cell(row, key, 0) or 0)))
    except ValueError:
        return 0


def skip_task(row: sqlite3.Row, reason: str, *, loud: bool = True) -> Skip:
    return Skip(_SOURCE, str(cell(row, "id", "?")), reason, loud)
