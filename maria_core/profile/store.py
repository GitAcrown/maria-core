"""Lecture et écriture du profil. Le réglage de la personne l'emporte sur ce qui est appris."""

from dataclasses import dataclass
from datetime import datetime

from maria_core.db import Database
from maria_core.profile.slots import BY_KEY


@dataclass(frozen=True, slots=True)
class Entry:
    value: str
    source: str  # "user" : réglé par la personne, "auto" : appris par MARIA


class ProfileStore:
    def __init__(self, database: Database) -> None:
        self._database = database

    def all(self, user_id: int) -> dict[str, Entry]:
        rows = self._database.fetchall(
            "SELECT key, value, source FROM user_profile WHERE user_id = ?", (user_id,)
        )
        return {row["key"]: Entry(row["value"], row["source"]) for row in rows}

    def value(self, user_id: int, key: str) -> str:
        row = self._database.fetchone(
            "SELECT value FROM user_profile WHERE user_id = ? AND key = ?", (user_id, key)
        )
        return "" if row is None else str(row["value"])

    def set(self, user_id: int, key: str, value: str, now: datetime) -> str:
        """Réglage de la personne. Renvoie la valeur gardée."""
        clean = self._clean(key, value)
        self._write(user_id, key, clean, "user", now)
        return clean

    def learn(self, user_id: int, key: str, value: str, now: datetime) -> bool:
        """Valeur apprise : écrit seulement si la personne n'a rien réglé elle-même."""
        clean = self._clean(key, value)
        row = self._database.fetchone(
            "SELECT source, value FROM user_profile WHERE user_id = ? AND key = ?", (user_id, key)
        )
        if row is not None and (row["source"] == "user" or row["value"] == clean):
            return False
        self._write(user_id, key, clean, "auto", now)
        return True

    def clear(self, user_id: int, key: str) -> None:
        self._database.execute(
            "DELETE FROM user_profile WHERE user_id = ? AND key = ?", (user_id, key)
        )

    def _write(self, user_id: int, key: str, value: str, source: str, now: datetime) -> None:
        self._database.execute(
            """
            INSERT INTO user_profile (user_id, key, value, source, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id, key) DO UPDATE SET
                value = excluded.value, source = excluded.source, updated_at = excluded.updated_at
            """,
            (user_id, key, value, source, now.isoformat()),
        )

    @staticmethod
    def _clean(key: str, value: str) -> str:
        slot = BY_KEY.get(key)
        if slot is None:
            raise ValueError(f"Champ inconnu : {key}.")
        text = " ".join(str(value).split())[:60]
        if not text:
            raise ValueError("Valeur vide.")
        if slot.normalize is not None:
            return slot.normalize(text)
        if slot.is_choice and text not in dict(slot.choices):
            allowed = ", ".join(dict(slot.choices))
            raise ValueError(f"Valeur possible pour {slot.label} : {allowed}.")
        return text
