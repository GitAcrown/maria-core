"""Bouton Annuler sous « 🧠 Retenu : … ». MARIA retient seule, la personne défait en un clic."""

import asyncio
import re

import discord
from discord.ext import commands

from maria_core.app import App
from maria_core.discord.hub import refuse
from maria_core.memory.policy import Actor
from maria_core.memory.store import MemoryDenied

_TRACE = re.compile(r"-# 🧠 Retenu[^\n]*")


class LearnedView(discord.ui.View):
    def __init__(self, memory_id: int) -> None:
        super().__init__(timeout=None)
        self.memory_id = memory_id
        undo = discord.ui.Button(
            label="Annuler",
            custom_id=f"maria:learn:{memory_id}",
            style=discord.ButtonStyle.secondary,
        )
        undo.callback = self._undo
        self.add_item(undo)

    async def _undo(self, interaction: discord.Interaction) -> None:
        await undo_learned(interaction, self.memory_id)


def restore_learned(bot: commands.Bot, app: App) -> None:
    """Les boutons Annuler des derniers jours restent utilisables après un redémarrage."""
    for memory_id, message_id in app.memory.learned.restorable(app.memory.now()):
        bot.add_view(LearnedView(memory_id), message_id=message_id)


async def undo_learned(interaction: discord.Interaction, memory_id: int) -> None:
    app = getattr(interaction.client, "app", None)
    if not isinstance(app, App):
        return
    permissions = getattr(interaction.user, "guild_permissions", None)
    actor = Actor(
        interaction.user.id,
        await interaction.client.is_owner(interaction.user),
        bool(permissions and permissions.manage_messages),
    )
    try:
        await asyncio.to_thread(app.memory.store.undo, actor, memory_id, app.memory.now())
    except MemoryDenied:
        await refuse(interaction, "Ce souvenir ne te concerne pas.")
        return
    await asyncio.to_thread(app.memory.learned.clear, memory_id)
    message = interaction.message
    content = message.content if message is not None else ""
    done = _TRACE.sub("-# 🧠 Annulé.", content) if _TRACE.search(content) else "-# 🧠 Annulé."
    await interaction.response.edit_message(content=done, view=None)
