"""Sondage natif Discord. Le modèle ne vote pas et ne voit pas les votes."""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from maria_core.capabilities.base import Capability, Context, Result, Risk
from maria_core.capabilities.ports import PollPoster
from maria_core.db import Database

_MIN_OPTIONS = 2
_MAX_OPTIONS = 10
_MAX_HOURS = 168
_DEFAULT_HOURS = 24


@dataclass(frozen=True, slots=True)
class StoredPoll:
    message_id: int
    question: str
    options: tuple[str, ...]
    expires_at: str


class PollStore:
    def __init__(self, database: Database) -> None:
        self._database = database

    def save(
        self,
        *,
        message_id: int,
        channel_id: int,
        guild_id: int,
        author_id: int,
        question: str,
        options: tuple[str, ...],
        hours: int,
    ) -> None:
        now = datetime.now(UTC)
        self._database.execute(
            """
            INSERT INTO polls (
                message_id, channel_id, guild_id, author_id, question,
                options_json, expires_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message_id,
                channel_id,
                guild_id,
                author_id,
                question,
                json.dumps(list(options), ensure_ascii=False),
                (now + timedelta(hours=hours)).isoformat(),
                now.isoformat(),
            ),
        )


def poll_capability(poster: PollPoster) -> Capability:
    async def run(context: Context, args: Mapping[str, Any]) -> Result:
        if context.guild_id is None:
            return Result(ok=False, data={}, error="Disponible uniquement sur un serveur.")
        question, options, hours, multiple, error = _spec(args)
        if error:
            return Result(ok=False, data={}, error=error)
        message_id = await poster.post(
            channel_id=context.channel_id,
            guild_id=context.guild_id,
            author_id=context.user_id,
            question=question,
            options=tuple(options),
            hours=hours,
            multiple=multiple,
        )
        return Result(
            ok=True,
            data={
                "message_id": message_id,
                "question": question,
                "options": options,
                "duration_hours": hours,
                "note": "Tu ne votes pas, et tu ne vois pas les votes en cours.",
            },
        )

    return Capability(
        name="create_poll",
        description=(
            "Poste un sondage Discord (2 à 10 options). "
            "INTERDIT de voter toi-même ou d'annoncer un score : Discord ne le donne pas."
        ),
        parameters={
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "options": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 2,
                    "maxItems": 10,
                },
                "multiple": {"type": "boolean"},
                "duration_hours": {"type": "integer", "minimum": 1, "maximum": 168},
            },
            "required": ["question", "options"],
        },
        risk=Risk.WRITE,
        run=run,
    )


def _spec(args: Mapping[str, Any]) -> tuple[str, list[str], int, bool, str]:
    question = str(args.get("question") or "").strip()[:300]
    options = [str(item).strip()[:55] for item in args.get("options") or [] if str(item).strip()]
    if not question:
        return "", [], 0, False, "Question vide."
    if len(options) < _MIN_OPTIONS:
        return "", [], 0, False, "Il faut au moins 2 options."
    hours = args.get("duration_hours")
    if not isinstance(hours, int) or isinstance(hours, bool):
        hours = _DEFAULT_HOURS
    hours = max(1, min(_MAX_HOURS, hours))
    return question, options[:_MAX_OPTIONS], hours, args.get("multiple") is True, ""
