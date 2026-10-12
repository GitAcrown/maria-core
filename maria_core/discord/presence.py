"""Statut Discord tournant, lu dans DATA_DIR/statuses.txt. Rotation dans l'ordre du fichier.

Format : une entrée par ligne, `playing:`, `watching:`, `listening:` ou un texte libre.
Les lignes vides et celles qui commencent par # sont ignorées.
"""

import asyncio
import logging
from pathlib import Path

import discord
from discord.ext import commands

logger = logging.getLogger(__name__)

INTERVAL_SECONDS = 20 * 60
_KINDS = {
    "playing": discord.ActivityType.playing,
    "watching": discord.ActivityType.watching,
    "listening": discord.ActivityType.listening,
}


def load_statuses(path: Path) -> list[tuple[str, str]]:
    if not path.is_file():
        return []
    entries: list[tuple[str, str]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        kind, _, rest = line.partition(":")
        if kind in _KINDS and rest.strip():
            entries.append((kind, rest.strip()))
        else:
            entries.append(("custom", line))
    return entries


def activity_of(kind: str, text: str) -> discord.BaseActivity:
    if kind == "playing":
        return discord.Game(name=text)
    if kind in _KINDS:
        return discord.Activity(type=_KINDS[kind], name=text)
    return discord.CustomActivity(name=text)


class PresenceCog(commands.Cog):
    def __init__(self, bot: commands.Bot, path: Path) -> None:
        self.bot = bot
        self.path = path
        self._index = 0
        self._task: asyncio.Task[None] | None = None

    async def cog_load(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def cog_unload(self) -> None:
        if self._task is not None:
            self._task.cancel()

    async def next_status(self) -> str:
        statuses = await asyncio.to_thread(load_statuses, self.path)
        if not statuses:
            return ""
        kind, text = statuses[self._index % len(statuses)]
        self._index += 1
        await self.bot.change_presence(activity=activity_of(kind, text))
        return text

    @commands.command(name="presence")
    @commands.is_owner()
    async def presence(self, ctx: commands.Context) -> None:
        """Passe au statut suivant."""
        shown = await self.next_status()
        await ctx.send(f"Statut : {shown}" if shown else f"Aucun statut dans {self.path.name}.")

    async def _loop(self) -> None:
        await self.bot.wait_until_ready()
        while True:
            try:
                await self.next_status()
            except discord.HTTPException:
                logger.warning("Statut refusé par Discord", exc_info=True)
            await asyncio.sleep(INTERVAL_SECONDS)
