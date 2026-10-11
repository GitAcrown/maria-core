"""Personnalité par défaut et repères de temps. Un serveur peut précéder la personnalité."""

from collections.abc import Callable
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

PARIS = ZoneInfo("Europe/Paris")

_DAYS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
_MONTHS = (
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
)


def default_personality() -> str:
    return (
        "Tu es MARIA, dans un salon Discord. "
        "Tu parles comme quelqu'un du salon, pas comme un mode d'emploi. "
        "Tu es directe, tu n'inventes pas de faits, et tu le dis quand tu ne sais pas. "
        "S'il existe un outil utile, tu l'utilises au lieu de deviner."
    )


def clock_section(now: Callable[[], datetime] | None = None) -> Callable[[], str]:
    """Rendu à chaque tour, pour que l'heure du prompt ne vieillisse pas."""
    clock = now or _utc_now

    def render() -> str:
        local = clock().astimezone(PARIS)
        day = _DAYS[local.weekday()]
        month = _MONTHS[local.month - 1]
        return f"Nous sommes le {day} {local.day} {month} {local.year}, {local:%H:%M} à Paris."

    return render


def _utc_now() -> datetime:
    return datetime.now(UTC)
