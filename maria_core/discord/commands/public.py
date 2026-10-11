"""Commandes slash visibles après `sync`."""

import asyncio
from datetime import UTC, datetime

import discord
from discord import app_commands
from discord.ext import commands

from maria_core.app import App
from maria_core.conversation.policy import save_everyone, save_mode, save_transcribe
from maria_core.discord.menus import send_memory, send_tasks

_MODES = [
    app_commands.Choice(name="Off — ne répond plus", value="off"),
    app_commands.Choice(name="Strict — mention, réponse, ou son prénom", value="strict"),
    app_commands.Choice(name="Greedy — répond aussi quand on parle d'elle", value="greedy"),
]


def _app(bot: commands.Bot) -> App:
    app = getattr(bot, "app", None)
    if not isinstance(app, App):
        raise RuntimeError("Le bot n'est pas relié à une application.")
    return app


class PublicCommands(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="moi", description="Tes souvenirs et tes propositions")
    async def moi(self, interaction: discord.Interaction) -> None:
        await send_memory(interaction, collective=False)

    @app_commands.command(name="global", description="Souvenirs du serveur")
    @app_commands.guild_only()
    async def guild_memory(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Disponible sur un serveur.", ephemeral=True)
            return
        await send_memory(interaction, collective=True)

    @app_commands.command(name="taches", description="Tes objectifs ouverts")
    async def tasks(self, interaction: discord.Interaction) -> None:
        await send_tasks(interaction)

    @app_commands.command(name="info", description="Réglages de MARIA dans ce salon")
    @app_commands.guild_only()
    async def info(self, interaction: discord.Interaction) -> None:
        place = _place(interaction)
        if place is None:
            await interaction.response.send_message("Disponible sur un serveur.", ephemeral=True)
            return
        guild, channel = place
        text = await asyncio.to_thread(_snapshot, _app(self.bot), guild.id, channel.id)
        await interaction.response.send_message(text[:2000], ephemeral=True)

    chatbot = app_commands.Group(
        name="chatbot",
        description="Réglages de MARIA",
        guild_only=True,
        default_permissions=discord.Permissions(manage_messages=True),
    )

    @chatbot.command(name="mode", description="Quand MARIA répond")
    @app_commands.choices(mode=_MODES)
    async def mode(self, interaction: discord.Interaction, mode: app_commands.Choice[str]) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("Disponible sur un serveur.", ephemeral=True)
            return
        await asyncio.to_thread(save_mode, _app(self.bot).database, guild.id, mode.value, _stamp())
        await interaction.response.send_message(f"Mode : **{mode.name}**.", ephemeral=True)

    @chatbot.command(name="forget", description="Oublie la conversation de ce salon")
    async def forget(self, interaction: discord.Interaction) -> None:
        channel = interaction.channel
        if channel is None:
            await interaction.response.send_message("Salon introuvable.", ephemeral=True)
            return
        _app(self.bot).conversation.forget_channel(channel.id)
        await interaction.response.send_message("Conversation oubliée.", ephemeral=True)

    @chatbot.command(name="everyone", description="Répondre aux @everyone et @here")
    async def everyone(self, interaction: discord.Interaction, actif: bool) -> None:
        await _toggle(self.bot, interaction, everyone=actif)

    @chatbot.command(name="autotranscribe", description="Transcrire les vocaux de ce salon")
    async def autotranscribe(self, interaction: discord.Interaction, actif: bool) -> None:
        await _toggle(self.bot, interaction, transcribe=actif)


def _place(
    interaction: discord.Interaction,
) -> tuple[discord.Guild, discord.abc.GuildChannel] | None:
    guild = interaction.guild
    channel = interaction.channel
    if guild is None or channel is None:
        return None
    if isinstance(channel, discord.Thread) and channel.parent is not None:
        channel = channel.parent
    if isinstance(channel, discord.abc.GuildChannel):
        return guild, channel
    return None


async def _toggle(
    bot: commands.Bot,
    interaction: discord.Interaction,
    *,
    everyone: bool | None = None,
    transcribe: bool | None = None,
) -> None:
    place = _place(interaction)
    if place is None:
        await interaction.response.send_message("Salon de serveur requis.", ephemeral=True)
        return
    guild, channel = place
    database = _app(bot).database
    if everyone is not None:
        await asyncio.to_thread(save_everyone, database, channel.id, guild.id, everyone)
        state = "activée" if everyone else "désactivée"
        await interaction.response.send_message(
            f"Réponse aux @everyone / @here **{state}**.",
            ephemeral=True,
        )
        return
    enabled = bool(transcribe)
    await asyncio.to_thread(save_transcribe, database, channel.id, guild.id, enabled)
    state = "activée" if enabled else "désactivée"
    await interaction.response.send_message(
        f"Transcription des vocaux **{state}**.",
        ephemeral=True,
    )


def _snapshot(app: App, guild_id: int, channel_id: int) -> str:
    guild = app.database.fetchone(
        "SELECT mode, spontaneity FROM guild_settings WHERE guild_id = ?",
        (guild_id,),
    )
    channel = app.database.fetchone(
        """
        SELECT respond_everyone, auto_transcribe
        FROM channel_settings WHERE channel_id = ?
        """,
        (channel_id,),
    )
    mode = "strict" if guild is None else str(guild["mode"] or "strict")
    spontaneity = "normal" if guild is None else str(guild["spontaneity"] or "normal")
    everyone = "oui" if channel is not None and channel["respond_everyone"] else "non"
    transcribe = "oui" if channel is not None and channel["auto_transcribe"] else "non"
    history = app.conversation.transcript(channel_id)
    return (
        f"Mode : {mode}\n"
        f"Spontanéité : {spontaneity}\n"
        f"@everyone : {everyone}\n"
        f"Vocaux transcrits : {transcribe}\n"
        f"Messages en mémoire dans ce salon : {len(history)}"
    )


def _stamp() -> str:
    return datetime.now(UTC).isoformat()
