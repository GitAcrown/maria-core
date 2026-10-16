"""Une date d'anniversaire : jour et mois seulement, rangés en « JJ/MM »."""

import re
import unicodedata

_MONTHS = (
    "janvier",
    "fevrier",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "aout",
    "septembre",
    "octobre",
    "novembre",
    "decembre",
)
_SHOWN = (
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
_DAYS = (31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
_NUMERIC = re.compile(r"^(\d{1,2})\s*[/.-]\s*(\d{1,2})(?:\s*[/.-]\s*\d{2,4})?$")
_WRITTEN = re.compile(r"^(\d{1,2})\s*(?:er)?\s+([a-z]+)(?:\s+\d{4})?$")
HELP = "Écris une date comme « 22 juillet » ou « 22/07 »."


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(char for char in decomposed if not unicodedata.combining(char)).casefold()


def normalize(value: str) -> str:
    """« 22 juillet 1999 », « 1er mai » ou « 22/07/99 » deviennent « 22/07 », « 01/05 »."""
    plain = " ".join(_fold(value).split())
    numeric = _NUMERIC.match(plain)
    written = _WRITTEN.match(plain)
    if numeric:
        day, month = int(numeric.group(1)), int(numeric.group(2))
    elif written and written.group(2) in _MONTHS:
        day, month = int(written.group(1)), _MONTHS.index(written.group(2)) + 1
    else:
        raise ValueError(f"Date d'anniversaire illisible. {HELP}")
    if not 1 <= month <= 12 or not 1 <= day <= _DAYS[month - 1]:
        raise ValueError(f"Cette date n'existe pas. {HELP}")
    return f"{day:02d}/{month:02d}"


def show(value: str) -> str:
    """« 22/07 » s'affiche « 22 juillet » (« 1er mai » pour le premier du mois)."""
    try:
        day, month = (int(part) for part in value.split("/"))
        name = _SHOWN[month - 1]
    except (ValueError, IndexError):
        return value
    return f"{'1er' if day == 1 else day} {name}"
