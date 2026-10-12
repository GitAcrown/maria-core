"""Boutons Retenir / Ignorer sous une proposition. La réponse de MARIA n'est jamais effacée."""

import asyncio

import discord
from discord.ext import commands

from maria_core.app import App
from maria_core.memory.model import Proposal
from maria_core.memory.policy import Actor
from maria_core.memory.store import MemoryDenied


class ProposalView(discord.ui.View):
    def __init__(self, proposal_id: int) -> None:
        super().__init__(timeout=None)
        retain = discord.ui.Button(
            label="Retenir",
            style=discord.ButtonStyle.primary,
            custom_id=f"maria:mem:{proposal_id}:yes",
        )
        ignore = discord.ui.Button(
            label="Ignorer",
            custom_id=f"maria:mem:{proposal_id}:no",
        )
        retain.callback = self._retain
        ignore.callback = self._ignore
        self.add_item(retain)
        self.add_item(ignore)
        self.proposal_id = proposal_id

    async def _retain(self, interaction: discord.Interaction) -> None:
        await _answer(interaction, self.proposal_id, accept=True)

    async def _ignore(self, interaction: discord.Interaction) -> None:
        await _answer(interaction, self.proposal_id, accept=False)


def restore_proposals(bot: commands.Bot, proposals: tuple[Proposal, ...]) -> None:
    for proposal in proposals:
        if proposal.reply_message_id is None:
            continue
        bot.add_view(ProposalView(proposal.id), message_id=proposal.reply_message_id)


async def _answer(interaction: discord.Interaction, proposal_id: int, *, accept: bool) -> None:
    app = getattr(interaction.client, "app", None)
    if not isinstance(app, App) or interaction.user is None:
        return
    actor = Actor(
        interaction.user.id,
        await interaction.client.is_owner(interaction.user),
        _moderator(interaction),
    )
    try:
        if accept:
            await asyncio.to_thread(app.memory.store.accept, proposal_id, actor, app.memory.now())
            text = "C'est noté."
        else:
            await asyncio.to_thread(app.memory.store.ignore, proposal_id, actor, app.memory.now())
            text = "D'accord, je ne le retiens pas."
    except (MemoryDenied, ValueError):
        await interaction.response.send_message(
            "Cette proposition ne t'est pas adressée, ou elle est déjà traitée.", ephemeral=True
        )
        return
    await interaction.response.edit_message(view=None)
    await interaction.followup.send(text, ephemeral=True)


def _moderator(interaction: discord.Interaction) -> bool:
    permissions = getattr(interaction.user, "guild_permissions", None)
    return bool(permissions and permissions.manage_messages)
