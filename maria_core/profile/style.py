"""Style d'écriture d'une personne, déduit de ses messages sans appeler le modèle.

Moyennes glissantes de quatre mesures simples. Rien n'est gardé du contenu des messages.
"""

import re
from dataclasses import dataclass
from datetime import datetime

from maria_core.db import Database

MIN_SAMPLES = 8
_SHORT_WORDS = 7
_LONG_WORDS = 28
_MIN_ALPHA = 0.08
_LAUGH = re.compile(r"\b(?:mdr|ptdr|lol|xd|haha+|hihi|lmao)\b", re.IGNORECASE)
_POLITE = re.compile(
    r"\b(?:bonjour|bonsoir|s'il (?:vous|te) pla[iî]t|merci beaucoup|"
    r"cordialement|auriez-vous|pourriez-vous|veuillez)\b",
    re.IGNORECASE,
)
_MENTION = re.compile(r"<[@#!&:\w]+\d*>|https?://\S+")


@dataclass(frozen=True, slots=True)
class Sample:
    words: int
    lower: bool
    laugh: bool
    polite: bool


def sample(text: str) -> Sample | None:
    clean = _MENTION.sub(" ", (text or "").replace(chr(0x2019), "'")).strip()
    first = next((char for char in clean if char.isalpha()), "")
    if not first:
        return None
    return Sample(
        words=len(clean.split()),
        lower=first.islower(),
        laugh=_LAUGH.search(clean) is not None,
        polite=_POLITE.search(clean) is not None,
    )


def verdict(
    samples: int, avg_words: float, lower: float, laugh: float, polite: float
) -> dict[str, str]:
    """Ce qu'on peut dire du style, seulement quand il s'écarte du réglage par défaut."""
    if samples < MIN_SAMPLES:
        return {}
    found: dict[str, str] = {}
    if avg_words <= _SHORT_WORDS:
        found["length"] = "short"
    elif avg_words >= _LONG_WORDS:
        found["length"] = "long"
    if polite >= 0.2 and lower <= 0.3:
        found["tone"] = "polished"
    elif lower >= 0.6 or laugh >= 0.1:
        found["tone"] = "casual"
    return found


class StyleTracker:
    def __init__(self, database: Database) -> None:
        self._database = database

    def observe(self, user_id: int, text: str, now: datetime) -> None:
        seen = sample(text)
        if seen is None:
            return
        row = self._database.fetchone("SELECT * FROM user_style WHERE user_id = ?", (user_id,))
        count = 0 if row is None else int(row["samples"])
        alpha = max(1 / (count + 1), _MIN_ALPHA)
        values = (seen.words, float(seen.lower), float(seen.laugh), float(seen.polite))
        before = (0.0, 0.0, 0.0, 0.0) if row is None else _averages(row)
        after = [old + alpha * (new - old) for old, new in zip(before, values, strict=True)]
        self._database.execute(
            """
            INSERT INTO user_style (
                user_id, samples, avg_words, lower_rate, laugh_rate, polite_rate, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                samples = excluded.samples, avg_words = excluded.avg_words,
                lower_rate = excluded.lower_rate, laugh_rate = excluded.laugh_rate,
                polite_rate = excluded.polite_rate, updated_at = excluded.updated_at
            """,
            (user_id, count + 1, *after, now.isoformat()),
        )

    def learned(self, user_id: int) -> dict[str, str]:
        row = self._database.fetchone("SELECT * FROM user_style WHERE user_id = ?", (user_id,))
        if row is None:
            return {}
        return verdict(int(row["samples"]), *_averages(row))

    def reset(self, user_id: int) -> None:
        self._database.execute("DELETE FROM user_style WHERE user_id = ?", (user_id,))


def _averages(row: object) -> tuple[float, float, float, float]:
    data = dict(row)  # type: ignore[call-overload]
    return (
        float(data["avg_words"]),
        float(data["lower_rate"]),
        float(data["laugh_rate"]),
        float(data["polite_rate"]),
    )
