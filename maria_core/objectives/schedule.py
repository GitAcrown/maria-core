"""Prochaine échéance, en heure de Paris. Un changement d'heure ne décale pas l'heure locale.

Une date sans fuseau est une heure de Paris : c'est ainsi que les gens et le modèle l'écrivent.
"""

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

PARIS = ZoneInfo("Europe/Paris")

EVENT_TRIGGERS = frozenset(
    {
        "on_topic",
        "on_mention",
        "on_post",
        "on_link",
        "on_attachment",
        "on_reaction",
        "on_voice",
        "on_member_join",
        "on_reply_to",
    }
)
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


_FR_DAYS = {
    "mon": "lundi",
    "tue": "mardi",
    "wed": "mercredi",
    "thu": "jeudi",
    "fri": "vendredi",
    "sat": "samedi",
    "sun": "dimanche",
}
_SIGNALS = {
    "join": "quand quelqu'un rejoint un vocal",
    "leave": "quand quelqu'un quitte un vocal",
    "stream": "quand quelqu'un lance un stream",
}


def describe(trigger: Mapping[str, Any]) -> str:
    kind = str(trigger.get("type") or "")
    if kind == "daily":
        return f"tous les jours à {trigger.get('time', '09:00')}"
    if kind == "weekly":
        days = ", ".join(_FR_DAYS.get(day, day) for day in weekdays(trigger.get("weekdays")))
        return f"chaque {days or 'semaine'} à {trigger.get('time', '09:00')}"
    if kind == "interval":
        return _every(_int(trigger.get("every_s"), 3600))
    if kind == "at":
        return f"le {local_text(trigger.get('at'))}"
    return _describe_event(kind, trigger)


def local_text(raw: object) -> str:
    try:
        moment = _moment(raw).astimezone(PARIS)
    except ValueError:
        return str(raw or "")
    return f"{moment:%d/%m/%Y à %H:%M}"


def _every(seconds: int) -> str:
    minutes = max(1, seconds // 60)
    if minutes % 1440 == 0:
        return f"tous les {minutes // 1440} j"
    if minutes % 60 == 0:
        return f"toutes les {minutes // 60} h"
    return f"toutes les {minutes} min"


_MEDIA = {"image": "une image", "video": "une vidéo", "audio": "un son", "file": "un fichier"}
_DESCRIPTIONS = {
    "on_mention": lambda t: (
        f"quand <@{t['user_id']}> est mentionné" if t.get("user_id") else "quand on te mentionne"
    ),
    "on_post": lambda t: f"quand <@{t.get('user_id')}> écrit",
    "on_link": lambda t: (
        "quand un lien est posté" + (f" ({t['pattern']})" if t.get("pattern") else "")
    ),
    "on_attachment": lambda t: (
        f"quand {_MEDIA.get(str(t.get('media')), 'un fichier ou une image')} est posté"
    ),
    "on_reaction": lambda t: f"quand quelqu'un réagit avec {t.get('emoji') or '?'}",
}


def _describe_event(kind: str, trigger: Mapping[str, Any]) -> str:
    if kind == "on_topic":
        topic = trigger.get("topic") or trigger.get("pattern") or "?"
        return f"quand on parle de « {topic} »"
    if kind == "on_voice":
        return _SIGNALS.get(str(trigger.get("signal") or "join"), "vocal")
    if kind == "on_member_join":
        return "quand un membre arrive"
    if kind in _DESCRIPTIONS:
        return _DESCRIPTIONS[kind](trigger)
    if kind == "on_reply_to":
        return "quand on répond à MARIA"
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


def moment_of(raw: object) -> datetime:
    """Date ISO ; sans fuseau, c'est l'heure de Paris."""
    return _moment(raw)


def _moment(raw: object) -> datetime:
    if isinstance(raw, datetime):
        moment = raw
    else:
        text = str(raw or "").strip().replace(" ", "T", 1)
        try:
            moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"Date illisible : {raw}. Format attendu : 2026-10-12T20:00") from exc
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=PARIS)
    return moment.astimezone(UTC)


def _int(raw: object, default: int) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int | float | str):
        return default
    try:
        return int(raw)
    except ValueError:
        return default
