"""Onglets d'un widget, retrouvés après redémarrage."""

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from maria_core.db import Database

_KEEP = 40


@dataclass(frozen=True, slots=True)
class SavedTabs:
    id: str
    channel_id: int
    message_id: int | None
    tabs: tuple[tuple[str, str], ...]


class TabStore:
    def __init__(self, database: Database) -> None:
        self._database = database

    def save(self, channel_id: int, tabs: tuple[tuple[str, str], ...]) -> SavedTabs:
        saved = SavedTabs(
            id=uuid.uuid4().hex[:12],
            channel_id=channel_id,
            message_id=None,
            tabs=tabs[:8],
        )
        self._database.execute(
            """
            INSERT INTO widget_tabs (id, channel_id, message_id, tabs_json, created_at)
            VALUES (?, ?, NULL, ?, ?)
            """,
            (saved.id, channel_id, _dump(saved.tabs), datetime.now(UTC).isoformat()),
        )
        self._trim()
        return saved

    def attach(self, tab_id: str, message_id: int) -> None:
        self._database.execute(
            "UPDATE widget_tabs SET message_id = ? WHERE id = ?",
            (message_id, tab_id),
        )

    def get(self, tab_id: str) -> SavedTabs | None:
        row = self._database.fetchone(
            "SELECT id, channel_id, message_id, tabs_json FROM widget_tabs WHERE id = ?",
            (tab_id,),
        )
        if row is None:
            return None
        return _saved(row["id"], row["channel_id"], row["message_id"], row["tabs_json"])

    def recent(self, limit: int = 30) -> tuple[SavedTabs, ...]:
        rows = self._database.fetchall(
            """
            SELECT id, channel_id, message_id, tabs_json FROM widget_tabs
            WHERE message_id IS NOT NULL
            ORDER BY created_at DESC LIMIT ?
            """,
            (limit,),
        )
        return tuple(
            _saved(row["id"], row["channel_id"], row["message_id"], row["tabs_json"])
            for row in rows
        )

    def _trim(self) -> None:
        self._database.execute(
            """
            DELETE FROM widget_tabs WHERE id NOT IN (
                SELECT id FROM widget_tabs ORDER BY created_at DESC LIMIT ?
            )
            """,
            (_KEEP,),
        )


def _dump(tabs: tuple[tuple[str, str], ...]) -> str:
    return json.dumps(list(tabs), ensure_ascii=False)


def _saved(
    tab_id: str,
    channel_id: int,
    message_id: int | None,
    payload: str,
) -> SavedTabs:
    loaded = json.loads(payload)
    tabs = tuple((str(label), str(body)) for label, body in loaded)
    return SavedTabs(id=tab_id, channel_id=channel_id, message_id=message_id, tabs=tabs)
