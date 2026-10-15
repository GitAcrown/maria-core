"""/halloween : menu à onglets (sac, classement), comme le /carnet de CRIT.

Fichier de l'événement Halloween 2026 : à supprimer avec le plugin (voir RETRAIT_HALLOWEEN.md),
ainsi que son enregistrement dans `bot.py`.
"""

from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from maria_core.app import App
from maria_core.discord.hub import Hub, Run, Tab, body, refuse, tab_bar, thin, title, wide
from maria_core.discord.layout import emojis
from maria_core.plugins.halloween import (
    CANDY,
    GOBLET,
    NAME,
    PUMPKIN,
    Player,
    in_season,
    play,
    result_text,
    status_text,
)

_TABS = (
    ("bag", "Sac", CANDY),
    ("ranking", "Classement", GOBLET),
)
_EVENT = "Halloween · jusqu'au 1er novembre"


class HalloweenHub(Hub):
    def __init__(self, app: App, who: Player) -> None:
        super().__init__(viewer_id=who.user)
        self.app = app
        self.who = who
        self.screen = "bag"
        self.page: dict[str, Any] = {}

    async def load(self) -> None:
        self.page = await play(self.app.database, self.who, self.screen)

    def build(self) -> None:
        content: list[discord.ui.Item] = [
            title(f"{PUMPKIN} Bonbons ou sort"),
            wide(),
            body(result_text(self.page)),
            discord.ui.TextDisplay(f"-# {emojis(status_text(self.page))}"),
            thin(),
            discord.ui.TextDisplay(f"-# {_EVENT}"),
        ]
        tabs = [
            Tab(label, self._show(name), active=self.screen == name, emoji=emoji)
            for name, label, emoji in _TABS
        ]
        self.set_layout(content, above=tab_bar(tabs))

    def _show(self, screen: str) -> Run:
        async def run(interaction: discord.Interaction) -> None:
            self.screen = screen
            await self.load()
            await self.refresh(interaction)

        return run


class HalloweenCog(commands.Cog):
    def __init__(self, bot: commands.Bot, app: App) -> None:
        self.bot = bot
        self.app = app

    @app_commands.command(
        name="halloween", description="Bonbons ou sort : ton sac et le classement"
    )
    @app_commands.guild_only()
    async def halloween(self, interaction: discord.Interaction) -> None:
        if not in_season() or NAME not in self.app.plugins.names:
            await refuse(interaction, "L'événement Halloween est terminé.")
            return
        who = Player(interaction.guild_id or 0, interaction.user.id, interaction.user.display_name)
        hub = HalloweenHub(self.app, who)
        await hub.load()
        await hub.open(interaction)
