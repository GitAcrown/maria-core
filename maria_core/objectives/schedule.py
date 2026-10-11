"""Prochaine échéance, en heure de Paris. Un changement d'heure ne décale pas l'heure locale."""

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

PARIS = ZoneInfo("Europe/Paris")

EVENT_TRIGGERS = frozenset({"on_message", "on_topic", "on_voice", "on_member_join", "on_reply_to"})
_DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_ALIASES = {
    "lundi": "mon",
    "mardi": "tue",
    "mercredi": "wed",
    "jeudi": "thu",
    "vendredi": "fri",
    "samedi": "sat",
    "dimanche": "sun",
    "monday": "mon",
    "tuesday": "tue",
    "wednesday": "wed",
    "thursday": "thu",
    "friday": "fri",
    "saturday": "sat",
    "sunday": "sun",
}
_MIN_INTERVAL = 60


def first_due(trigger: Mapping[str, Any], now: datetime) -> datetime | None:
    """Première échéance. Un `at` déjà passé reste dû : le moteur décidera s'il est manqué."""
    kind = str(trigger.get("type") or "")
    if kind in EVENT_TRIGGERS:
        return None
    if kind == "at":
        return _moment(trigger.get("at"))
    return next_due(trigger, after=now)


def next_due(trigger: Mapping[str, Any], *, after: datetime) -> datetime | None:
    """Occurrence strictement après `after`. `at` et les événements n'ont pas de suite."""
    kind = str(trigger.get("type") or "")
    if kind in EVENT_TRIGGERS or kind == "at":
        return None
    if kind == "interval":
        every = max(_MIN_INTERVAL, _int(trigger.get("every_s"), 3600))
        return after + timedelta(seconds=every)
    if kind == "daily":
        return _next_clock(trigger, after, weekdays=None)
    if kind == "weekly":
        return _next_clock(trigger, after, weekdays=weekdays(trigger.get("weekdays")))
    raise ValueError(f"Déclencheur inconnu : {kind}")


def clock_text(raw: object) -> str:
    hour, minute = _hhmm(str(raw or "09:00"))
    return f"{hour:02d}:{minute:02d}"


def weekdays(raw: object) -> tuple[str, ...]:
    if raw is None:
        return ()
    if isinstance(raw, str):
        pieces = raw.replace(";", ",").split(",")
    elif isinstance(raw, list | tuple):
        pieces = [str(item) for item in raw]
    else:
        return ()
    found: list[str] = []
    for piece in pieces:
        token = _ALIASES.get(piece.strip().casefold(), piece.strip().casefold()[:3])
        if token in _DAYS and token not in found:
            found.append(token)
    return tuple(found)


def describe(trigger: Mapping[str, Any]) -> str:
    kind = str(trigger.get("type") or "")
    if kind == "daily":
        return f"tous les jours à {trigger.get('time', '09:00')}"
    if kind == "weekly":
        days = ", ".join(weekdays(trigger.get("weekdays"))) or "un jour"
        return f"chaque {days} à {trigger.get('time', '09:00')}"
    if kind == "interval":
        return f"toutes les {max(1, _int(trigger.get('every_s'), 3600) // 60)} min"
    if kind == "at":
        return f"le {trigger.get('at', '')}"
    return kind


def time_key(moment: datetime | None) -> str:
    if moment is None:
        return "event"
    return moment.astimezone(UTC).isoformat()


def _next_clock(
    trigger: Mapping[str, Any],
    after: datetime,
    *,
    weekdays: tuple[str, ...] | None,
) -> datetime | None:
    hour, minute = _hhmm(str(trigger.get("time") or "09:00"))
    allowed = set(weekdays) if weekdays else set(_DAYS)
    if not allowed:
        return None
    day = after.astimezone(PARIS).date()
    for _ in range(400):
        local = datetime(day.year, day.month, day.day, hour, minute, tzinfo=PARIS)
        moment = local.astimezone(UTC)
        if _DAYS[local.weekday()] in allowed and moment > after:
            return moment
        day += timedelta(days=1)
    return None


def _hhmm(text: str) -> tuple[int, int]:
    cleaned = text.strip().lower().replace("h", ":")
    parts = cleaned.split(":")
    try:
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 and parts[1] != "" else 0
    except (ValueError, IndexError) as exc:
        raise ValueError(f"Heure illisible : {text}") from exc
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError(f"Heure hors limites : {text}")
    return hour, minute


def _moment(raw: object) -> datetime:
    if isinstance(raw, datetime):
        moment = raw
    else:
        try:
            moment = datetime.fromisoformat(str(raw))
        except ValueError as exc:
            raise ValueError(f"Date illisible : {raw}") from exc
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


def _int(raw: object, default: int) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int | float | str):
        return default
    try:
        return int(raw)
    except ValueError:
        return default
