"""Persistance des objectifs. Le bail et la clé d'activation empêchent le double envoi."""

import json
import sqlite3
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from maria_core.db import Database
from maria_core.objectives.model import Objective, ObjectiveQuota, StaleObjective
from maria_core.objectives.quota import MAX_OPEN, open_count
from maria_core.objectives.schedule import first_due

LEASE = timedelta(seconds=60)
_DONE = frozenset({"sent", "missed", "skipped"})


class ObjectiveStore:
    def __init__(self, database: Database) -> None:
        self._database = database

    def create(
        self,
        *,
        owner_id: int,
        guild_id: int | None,
        channel_ids: tuple[int, ...],
        deliver: str,
        title: str,
        trigger: Mapping[str, Any],
        condition: Mapping[str, Any] | None,
        action: Mapping[str, Any],
        now: datetime,
        max_fires: int | None = None,
        cooldown_s: int = 0,
        expires_at: datetime | None = None,
        status: str = "active",
        origin_message_id: int | None = None,
        state: Mapping[str, Any] | None = None,
    ) -> tuple[Objective, bool]:
        duplicate = self.find_duplicate(owner_id, trigger, action, condition)
        if duplicate is not None:
            return duplicate, False
        if open_count(self._database, owner_id) >= MAX_OPEN:
            raise ObjectiveQuota(f"Plafond de {MAX_OPEN} objectifs atteint.")
        moment = first_due(trigger, now)
        stamp = now.isoformat()
        result = self._database.execute(
            """
            INSERT INTO objectives (
                owner_id, guild_id, channel_ids, deliver, title, trigger_json,
                condition_json, action_json, status, next_run_at, fires, max_fires,
                cooldown_s, expires_at, state_json, version, last_error, created_at, updated_at,
                origin_message_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, 1, '', ?, ?, ?)
            """,
            (
                owner_id,
                guild_id,
                json.dumps(list(channel_ids)),
                deliver,
                title.strip(),
                _dump(trigger),
                _dump(condition) if condition else None,
                _dump(action),
                status,
                _iso(moment),
                max_fires,
                cooldown_s,
                _iso(expires_at),
                _dump(state or {}),
                stamp,
                stamp,
                origin_message_id,
            ),
        )
        created = self.get(result.lastrowid)
        if created is None:
            raise RuntimeError("Objectif introuvable après insertion.")
        return created, True

    def get(self, objective_id: int) -> Objective | None:
        row = self._database.fetchone("SELECT * FROM objectives WHERE id = ?", (objective_id,))
        if row is None:
            return None
        return _objective(row)

    def list_for(self, owner_id: int) -> tuple[Objective, ...]:
        rows = self._database.fetchall(
            """
            SELECT * FROM objectives
            WHERE owner_id = ? AND status IN ('draft', 'active', 'paused')
            ORDER BY id
            """,
            (owner_id,),
        )
        return tuple(_objective(row) for row in rows)

    def find_duplicate(
        self,
        owner_id: int,
        trigger: Mapping[str, Any],
        action: Mapping[str, Any],
        condition: Mapping[str, Any] | None = None,
    ) -> Objective | None:
        """Même déclencheur, même condition, même action : c'est le même objectif."""
        signature = _signature(trigger, action, condition)
        for item in self.list_for(owner_id):
            if _signature(item.trigger, item.action, item.condition) == signature:
                return item
        return None

    def latest_draft(self, owner_id: int, channel_id: int, since: datetime) -> Objective | None:
        rows = self._database.fetchall(
            """
            SELECT * FROM objectives
            WHERE owner_id = ? AND status = 'draft' AND created_at >= ?
            ORDER BY id DESC
            """,
            (owner_id, since.isoformat()),
        )
        for row in rows:
            found = _objective(row)
            if not found.channel_ids or channel_id in found.channel_ids:
                return found
        return None

    def recent_drafts(self, limit: int = 50) -> tuple[Objective, ...]:
        rows = self._database.fetchall(
            "SELECT * FROM objectives WHERE status = 'draft' ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        return tuple(_objective(row) for row in rows)

    def expire_drafts(self, before: datetime, now: datetime) -> int:
        result = self._database.execute(
            """
            UPDATE objectives SET status = 'cancelled', version = version + 1, updated_at = ?
            WHERE status = 'draft' AND created_at < ?
            """,
            (now.isoformat(), before.isoformat()),
        )
        return result.rowcount

    def claim(self, now: datetime) -> Objective | None:
        """Réserve le plus ancien objectif dû. Personne d'autre ne le prend avant la fin du bail."""
        with self._database.transaction():
            row = self._database.fetchone(
                """
                SELECT id FROM objectives
                WHERE status = 'active' AND next_run_at IS NOT NULL AND next_run_at <= ?
                  AND (lease_until IS NULL OR lease_until < ?)
                ORDER BY next_run_at LIMIT 1
                """,
                (now.isoformat(), now.isoformat()),
            )
            if row is None:
                return None
            until = (now + LEASE).isoformat()
            result = self._database.execute(
                """
                UPDATE objectives
                SET lease_until = ?, version = version + 1, updated_at = ?
                WHERE id = ? AND (lease_until IS NULL OR lease_until < ?)
                """,
                (until, now.isoformat(), row["id"], now.isoformat()),
            )
            if result.rowcount != 1:
                return None
        return self.get(int(row["id"]))

    def event_objectives(self) -> tuple[Objective, ...]:
        rows = self._database.fetchall(
            """
            SELECT * FROM objectives
            WHERE status = 'active' AND next_run_at IS NULL
            ORDER BY id
            """
        )
        return tuple(_objective(row) for row in rows)

    def open_run(self, objective_id: int, key: str, now: datetime) -> str:
        """`start` pour exécuter, `done` si déjà parti, `busy` si un autre tour le tient."""
        try:
            self._database.execute(
                """
                INSERT INTO objective_runs (objective_id, activation_key, started_at, outcome)
                VALUES (?, ?, ?, 'open')
                """,
                (objective_id, key, now.isoformat()),
            )
        except sqlite3.IntegrityError:
            return self._existing_run(objective_id, key, now)
        return "start"

    def complete_run(
        self,
        objective_id: int,
        key: str,
        outcome: str,
        error: str,
        now: datetime,
        summary: str = "",
    ) -> None:
        self._database.execute(
            """
            UPDATE objective_runs
            SET outcome = ?, finished_at = ?, error = ?, summary = ?
            WHERE objective_id = ? AND activation_key = ?
            """,
            (outcome, now.isoformat(), error[:300], summary[:400], objective_id, key),
        )

    def recent_summaries(self, objective_id: int, limit: int = 6) -> tuple[tuple[str, str], ...]:
        """(date, texte envoyé) des derniers passages, du plus ancien au plus récent."""
        rows = self._database.fetchall(
            """
            SELECT started_at, summary FROM objective_runs
            WHERE objective_id = ? AND outcome = 'sent' AND summary != ''
            ORDER BY id DESC LIMIT ?
            """,
            (objective_id, limit),
        )
        return tuple((str(row["started_at"]), str(row["summary"])) for row in reversed(rows))

    def settle(
        self,
        objective: Objective,
        *,
        now: datetime,
        status: str,
        next_run_at: datetime | None,
        fires: int,
        state: Mapping[str, Any],
        error: str = "",
    ) -> Objective:
        result = self._database.execute(
            """
            UPDATE objectives
            SET status = ?, next_run_at = ?, fires = ?, state_json = ?, last_error = ?,
                lease_until = NULL, version = version + 1, updated_at = ?
            WHERE id = ? AND version = ?
            """,
            (
                status,
                _iso(next_run_at),
                fires,
                _dump(state),
                error[:300],
                now.isoformat(),
                objective.id,
                objective.version,
            ),
        )
        if result.rowcount != 1:
            raise StaleObjective(f"Objectif {objective.id} modifié entre-temps.")
        saved = self.get(objective.id)
        if saved is None:
            raise StaleObjective(f"Objectif {objective.id} disparu.")
        return saved

    def revise(
        self,
        objective: Objective,
        *,
        now: datetime,
        title: str,
        trigger: Mapping[str, Any],
        condition: Mapping[str, Any] | None,
        action: Mapping[str, Any],
        next_run_at: datetime | None,
        deliver: str | None = None,
        max_fires: int | None = None,
        state: Mapping[str, Any] | None = None,
    ) -> Objective:
        result = self._database.execute(
            """
            UPDATE objectives
            SET title = ?, trigger_json = ?, condition_json = ?, action_json = ?,
                next_run_at = ?, deliver = ?, max_fires = ?, state_json = ?,
                lease_until = NULL, version = version + 1, updated_at = ?
            WHERE id = ? AND version = ?
            """,
            (
                title.strip(),
                _dump(trigger),
                _dump(condition) if condition else None,
                _dump(action),
                _iso(next_run_at),
                deliver or objective.deliver,
                max_fires,
                _dump(objective.state if state is None else state),
                now.isoformat(),
                objective.id,
                objective.version,
            ),
        )
        if result.rowcount != 1:
            raise StaleObjective(f"Objectif {objective.id} modifié entre-temps.")
        saved = self.get(objective.id)
        if saved is None:
            raise StaleObjective(f"Objectif {objective.id} disparu.")
        return saved

    def release(self, objective_id: int, version: int) -> None:
        self._database.execute(
            "UPDATE objectives SET lease_until = NULL WHERE id = ? AND version = ?",
            (objective_id, version),
        )

    def _existing_run(self, objective_id: int, key: str, now: datetime) -> str:
        row = self._database.fetchone(
            """
            SELECT outcome, started_at FROM objective_runs
            WHERE objective_id = ? AND activation_key = ?
            """,
            (objective_id, key),
        )
        if row is None or row["outcome"] in _DONE:
            return "done" if row is not None else "start"
        started = _parse(row["started_at"])
        if row["outcome"] == "open" and started is not None and now - started < LEASE:
            return "busy"
        self._database.execute(
            """
            UPDATE objective_runs SET started_at = ?, outcome = 'open', error = ''
            WHERE objective_id = ? AND activation_key = ?
            """,
            (now.isoformat(), objective_id, key),
        )
        return "start"


def _objective(row: sqlite3.Row) -> Objective:
    return Objective(
        id=int(row["id"]),
        owner_id=int(row["owner_id"]),
        guild_id=int(row["guild_id"]) if row["guild_id"] is not None else None,
        channel_ids=tuple(json.loads(row["channel_ids"])),
        deliver=str(row["deliver"]),
        title=str(row["title"]),
        trigger=json.loads(row["trigger_json"]),
        condition=json.loads(row["condition_json"]) if row["condition_json"] else None,
        action=json.loads(row["action_json"]),
        status=str(row["status"]),
        next_run_at=_parse(row["next_run_at"]),
        fires=int(row["fires"]),
        max_fires=int(row["max_fires"]) if row["max_fires"] is not None else None,
        cooldown_s=int(row["cooldown_s"]),
        expires_at=_parse(row["expires_at"]),
        state=json.loads(row["state_json"]),
        version=int(row["version"]),
        last_error=str(row["last_error"]),
        origin_message_id=_optional_int(row["origin_message_id"]),
    )


def _optional_int(raw: object) -> int | None:
    return int(raw) if isinstance(raw, int) and not isinstance(raw, bool) else None


def _dump(value: object) -> str:
    return json.dumps(_plain(value), ensure_ascii=False, sort_keys=True)


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(item) for item in value]
    return value


def _iso(moment: datetime | None) -> str | None:
    if moment is None:
        return None
    return moment.astimezone(UTC).isoformat()


def _parse(raw: object) -> datetime | None:
    if not raw:
        return None
    moment = datetime.fromisoformat(str(raw))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment


def _signature(
    trigger: Mapping[str, Any],
    action: Mapping[str, Any],
    condition: Mapping[str, Any] | None,
) -> str:
    return _dump({"action": action, "condition": condition or {}, "trigger": trigger})
