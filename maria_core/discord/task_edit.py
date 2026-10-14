"""Modifier un programme depuis /programmes : titre, message, et l'heure quand elle a un sens."""

import asyncio
import re
from collections.abc import Awaitable, Callable
from datetime import datetime

import discord

from maria_core.app import App
from maria_core.objectives.model import Objective, ObjectiveQuota, StaleObjective
from maria_core.objectives.schedule import PARIS
from maria_core.objectives.tools import apply

_CLOCK = re.compile(r"^(\d{1,2})\s*[:hH]\s*(\d{2})$")
_DATE = re.compile(r"^(\d{1,2})/(\d{1,2})(?:/(\d{4}))?\s+(\d{1,2})\s*[:hH]\s*(\d{2})$")
TIMED = frozenset({"at", "daily", "weekly"})

type Done = Callable[[discord.Interaction, str], Awaitable[None]]


def when_changes(trigger_type: str, raw: str, now: datetime) -> dict[str, str]:
    """`18:30` pour un rappel récurrent, `25/12 18:30` ou `25/12/2026 18:30` pour une date."""
    text = raw.strip()
    if not text:
        return {}
    if trigger_type in {"daily", "weekly"}:
        found = _CLOCK.match(text)
        if found is None:
            raise ValueError("Heure illisible : écris par exemple 18:30.")
        return {"time": _clock(found.group(1), found.group(2))}
    if trigger_type == "at":
        found = _DATE.match(text)
        if found is None:
            raise ValueError("Date illisible : écris par exemple 25/12 18:30.")
        day, month, year, hour, minute = found.groups()
        local = now.astimezone(PARIS)
        stamp = _stamp(int(year or local.year), int(month), int(day), hour, minute)
        if year is None and stamp < local.replace(tzinfo=None):
            stamp = stamp.replace(year=stamp.year + 1)
        return {"at": stamp.strftime("%Y-%m-%dT%H:%M")}
    raise ValueError("Cette écoute n'a pas d'heure à modifier.")


def _clock(hour: str, minute: str) -> str:
    if not (0 <= int(hour) < 24 and 0 <= int(minute) < 60):
        raise ValueError("Heure impossible.")
    return f"{int(hour):02d}:{minute}"


def _stamp(year: int, month: int, day: int, hour: str, minute: str) -> datetime:
    try:
        return datetime(year, month, day, int(hour), int(minute))
    except ValueError as exc:
        raise ValueError("Date impossible.") from exc


class EditProgram(discord.ui.Modal, title="Modifier le programme"):
    def __init__(self, app: App, objective: Objective, done: Done) -> None:
        super().__init__()
        self.app = app
        self.objective = objective
        self.done = done
        self.name = discord.ui.TextInput(
            label="Titre", default=objective.title[:100], max_length=100
        )
        self.add_item(self.name)
        self.message = discord.ui.TextInput(
            label="Message ou consigne",
            style=discord.TextStyle.paragraph,
            default=str(objective.action.get("text") or "")[:1000],
            max_length=1000,
            required=False,
        )
        self.add_item(self.message)
        self.when = discord.ui.TextInput(
            label="Quand (HH:MM, ou JJ/MM HH:MM)",
            placeholder="Vide pour ne pas changer",
            max_length=20,
            required=False,
        )
        if str(objective.trigger.get("type")) in TIMED:
            self.add_item(self.when)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            changes = self._changes()
            await interaction.response.defer()
            await asyncio.to_thread(
                apply, self.app.objectives, self.objective, {"op": "modify", **changes}
            )
        except (ValueError, StaleObjective, ObjectiveQuota) as exc:
            if not interaction.response.is_done():
                await interaction.response.defer()
            await self.done(interaction, f"Rien de modifié : {exc}")
            return
        await self.done(interaction, "Modifié.")

    def _changes(self) -> dict[str, str]:
        changes: dict[str, str] = {}
        title = str(self.name.value).strip()
        if title and title != self.objective.title:
            changes["title"] = title
        message = str(self.message.value).strip()
        if message and message != str(self.objective.action.get("text") or ""):
            changes["text"] = message
        kind = str(self.objective.trigger.get("type") or "")
        changes.update(when_changes(kind, str(self.when.value or ""), self.app.objectives.now()))
        return changes
