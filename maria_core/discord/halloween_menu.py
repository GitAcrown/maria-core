"""/halloween : menu à onglets (porte, sac, classement), comme le /carnet de CRIT.

Fichier de l'événement Halloween 2026 : à supprimer avec le plugin (voir RETRAIT_HALLOWEEN.md),
ainsi que son enregistrement dans `bot.py`.
"""

from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from maria_core.app import App
from maria_core.discord.hub import Hub, body, refuse, thin, title, wide
from maria_core.discord.layout import emojis
from maria_core.plugins.halloween import (
    CANDY,
    NAME,
    PUMPKIN,
    Player,
    in_season,
    play,
    result_text,
    status_text,
)

_TABS = (
    ("door", "Porte", PUMPKIN),
    ("bag", "Sac", CANDY),
    ("ranking", "Classement", "🏆"),
)
_INTRO = (
    "Tu te tiens devant la porte d'un vieux manoir, une citrouille grimaçante te regarde.\n"
    "Sonne pour tenter ta chance : des bonbons, ou un sort."
)


class _Tab(discord.ui.Button):
    def __init__(self, hub: "HalloweenHub", screen: str, label: str, emoji: str) -> None:
        super().__init__(
            label=label,
            emoji=discord.PartialEmoji.from_str(emojis(emoji)),
            style=discord.ButtonStyle.primary
            if hub.screen == screen
            else discord.ButtonStyle.secondary,
        )
        self.hub = hub
        self.screen = screen

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.hub.go(interaction, self.screen)


class _Ring(discord.ui.Button):
    def __init__(self, hub: "HalloweenHub", *, disabled: bool) -> None:
        super().__init__(label="Sonner", style=discord.ButtonStyle.success, disabled=disabled)
        self.hub = hub

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.hub.ring(interaction)


class HalloweenHub(Hub):
    def __init__(self, app: App, who: Player) -> None:
        super().__init__(viewer_id=who.user)
        self.app = app
        self.who = who
        self.screen = "door"
        self.status: dict[str, Any] = {}  # dernier état connu du sac : sonneries restantes
        self.rung: dict[str, Any] = {}  # dernière sonnerie, affichée sur la porte
        self.page: dict[str, Any] = {}  # contenu de l'onglet Sac ou Classement

    async def load(self) -> None:
        self.status = await play(self.app.database, self.who, "bag")

    def build(self) -> None:
        self.clear_items()
        tabs = (_Tab(self, name, label, emoji) for name, label, emoji in _TABS)
        self.add_item(discord.ui.ActionRow(*tabs))
        door = self.screen == "door"
        shown = self.rung if door else self.page
        text = result_text(shown) if shown else _INTRO
        foot = status_text(shown if shown else self.status)
        content: list[discord.ui.Item] = [
            title(f"{PUMPKIN} Bonbons ou sort", "Halloween · jusqu'au 1er novembre"),
            wide(),
            body(text),
            discord.ui.TextDisplay(f"-# {emojis(foot)}"),
        ]
        if door:
            left = int(self.status.get("rings_left") or 0)
            content += [thin(), discord.ui.ActionRow(_Ring(self, disabled=left <= 0))]
        self.add_item(discord.ui.Container(*content))

    async def go(self, interaction: discord.Interaction, screen: str) -> None:
        self.screen = screen
        if screen != "door":
            self.page = await play(self.app.database, self.who, screen)
            if screen == "bag":
                self.status = self.page
        await self.refresh(interaction)

    async def ring(self, interaction: discord.Interaction) -> None:
        self.rung = self.status = await play(self.app.database, self.who, "ring")
        self.screen = "door"
        await self.refresh(interaction)


class HalloweenCog(commands.Cog):
    def __init__(self, bot: commands.Bot, app: App) -> None:
        self.bot = bot
        self.app = app

    @app_commands.command(
        name="halloween", description="Bonbons ou sort : sonne, ton sac, le classement"
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
