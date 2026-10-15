"""Commandes slash visibles après `sync`."""

import asyncio
from datetime import UTC, datetime

import discord
from discord import app_commands
from discord.ext import commands

from maria_core.app import App
from maria_core.capabilities.builtin.python_tool import set_python
from maria_core.conversation.policy import (
    save_everyone,
    save_limit,
    save_mode,
    save_transcribe,
)
from maria_core.discord.hub import answer, card, refuse
from maria_core.discord.me_menu import open_me
from maria_core.discord.memory_menu import open_memory
from maria_core.discord.task_menu import open_tasks
from maria_core.memory.service import LEARNING
from maria_core.social.levels import LEVELS, set_level, set_member_level

_MODES = [
    app_commands.Choice(name="Off — ne répond plus", value="off"),
    app_commands.Choice(name="Strict — mention, réponse, ou son prénom", value="strict"),
    app_commands.Choice(name="Greedy — répond aussi quand on parle d'elle", value="greedy"),
]
_LEARNING = [
    app_commands.Choice(name="Automatique — elle retient seule, j'annule si besoin", value="auto"),
    app_commands.Choice(name="Elle me demande avant de retenir", value="ask"),
    app_commands.Choice(name="Elle ne retient rien sur moi", value="off"),
]
_LIMITS = [
    app_commands.Choice(name="Aucune — MARIA répond toujours (défaut)", value="none"),
    app_commands.Choice(name="Modérée — pas plus de réponses que de messages", value="normal"),
    app_commands.Choice(name="Stricte — deux fois moins de réponses", value="strict"),
]
_LIMIT_NAMES = {"none": "aucune", "normal": "modérée", "strict": "stricte"}
_LEVELS = [
    app_commands.Choice(name="Off — aucune réaction spontanée", value="off"),
    app_commands.Choice(name="Discret", value="quiet"),
    app_commands.Choice(name="Normal", value="normal"),
    app_commands.Choice(name="Bavard", value="chatty"),
]


def _app(bot: commands.Bot) -> App:
    app = getattr(bot, "app", None)
    if not isinstance(app, App):
        raise RuntimeError("Le bot n'est pas relié à une application.")
    return app


class PublicCommands(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="moi", description="Ce que MARIA sait de toi : profil, souvenirs, propositions"
    )
    async def moi(self, interaction: discord.Interaction) -> None:
        await open_me(interaction, _app(self.bot))

    @app_commands.command(name="global", description="Souvenirs du serveur")
    @app_commands.guild_only()
    async def guild_memory(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await refuse(interaction, "Disponible sur un serveur.")
            return
        await open_memory(interaction, _app(self.bot), collective=True)

    @app_commands.command(name="programmes", description="Tes rappels, écoutes et surveillances")
    async def tasks(self, interaction: discord.Interaction) -> None:
        await open_tasks(interaction, _app(self.bot))

    @app_commands.command(name="info", description="Réglages de MARIA dans ce salon")
    @app_commands.guild_only()
    async def info(self, interaction: discord.Interaction) -> None:
        place = _place(interaction)
        if place is None:
            await refuse(interaction, "Disponible sur un serveur.")
            return
        guild, channel = place
        app = _app(self.bot)
        text, mode = await asyncio.to_thread(_snapshot, app, guild.id, channel.id)
        view = card(f"#{channel.name}", text, meta=f"Mode · {mode}")
        await interaction.response.send_message(view=view, ephemeral=True)

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
            await refuse(interaction, "Disponible sur un serveur.")
            return
        await asyncio.to_thread(save_mode, _app(self.bot).database, guild.id, mode.value, _stamp())
        await answer(interaction, "Mode de réponse", mode.name)

    @chatbot.command(name="forget", description="Oublie la conversation de ce salon")
    async def forget(self, interaction: discord.Interaction) -> None:
        channel = interaction.channel
        if channel is None:
            await refuse(interaction, "Salon introuvable.")
            return
        _app(self.bot).conversation.forget_channel(channel.id)
        await answer(interaction, "Conversation oubliée", "-# MARIA repart de zéro dans ce salon.")

    @chatbot.command(name="everyone", description="Répondre aux @everyone et @here")
    async def everyone(self, interaction: discord.Interaction, actif: bool) -> None:
        await _toggle(self.bot, interaction, everyone=actif)

    @chatbot.command(name="autotranscribe", description="Transcrire les vocaux de ce salon")
    async def autotranscribe(self, interaction: discord.Interaction, actif: bool) -> None:
        await _toggle(self.bot, interaction, transcribe=actif)

    @chatbot.command(name="python", description="Autoriser run_python sur ce serveur")
    async def python(self, interaction: discord.Interaction, actif: bool) -> None:
        guild = interaction.guild
        if guild is None:
            await refuse(interaction, "Disponible sur un serveur.")
            return
        await asyncio.to_thread(set_python, _app(self.bot).database, guild.id, actif, _stamp())
        state = "activé" if actif else "désactivé"
        await answer(interaction, "run_python", f"**{state.capitalize()}** sur ce serveur.")

    @chatbot.command(name="limite", description="Limiter les réponses de MARIA sur ce serveur")
    @app_commands.choices(niveau=_LIMITS)
    async def limit(
        self, interaction: discord.Interaction, niveau: app_commands.Choice[str]
    ) -> None:
        guild = interaction.guild
        if guild is None:
            await refuse(interaction, "Disponible sur un serveur.")
            return
        await asyncio.to_thread(
            save_limit, _app(self.bot).database, guild.id, niveau.value, _stamp()
        )
        await answer(
            interaction,
            "Limite de réponses",
            f"**{niveau.name}**",
            meta="Les suivis sans appel restent toujours un peu plus discrets",
        )

    @chatbot.command(name="spontaneite", description="Réactions spontanées de MARIA")
    @app_commands.choices(niveau=_LEVELS)
    async def spontaneity(
        self, interaction: discord.Interaction, niveau: app_commands.Choice[str]
    ) -> None:
        guild = interaction.guild
        if guild is None:
            await refuse(interaction, "Disponible sur un serveur.")
            return
        await asyncio.to_thread(
            set_level, _app(self.bot).database, guild.id, niveau.value, _stamp()
        )
        await answer(interaction, "Spontanéité", f"**{niveau.name}**")

    preferences = app_commands.Group(
        name="preferences", description="Tes réglages avec MARIA", guild_only=True
    )

    @preferences.command(name="apprentissage", description="Ce que MARIA retient sur toi")
    @app_commands.choices(mode=_LEARNING)
    async def learning(
        self, interaction: discord.Interaction, mode: app_commands.Choice[str]
    ) -> None:
        guild = interaction.guild
        if guild is None:
            await refuse(interaction, "Disponible sur un serveur.")
            return
        app = _app(self.bot)
        await asyncio.to_thread(app.memory.set_learning, interaction.user.id, guild.id, mode.value)
        await answer(
            interaction,
            "Apprentissage",
            f"**{LEARNING[mode.value]}**.",
            meta="Retrouve et annule ce qu'elle a retenu dans /moi",
        )

    @preferences.command(name="reactions", description="Réactions spontanées sur tes messages")
    @app_commands.choices(niveau=[*_LEVELS, app_commands.Choice(name="Comme le serveur", value="")])
    async def reactions(
        self, interaction: discord.Interaction, niveau: app_commands.Choice[str]
    ) -> None:
        guild = interaction.guild
        if guild is None:
            await refuse(interaction, "Disponible sur un serveur.")
            return
        chosen = niveau.value if niveau.value in LEVELS else None
        await asyncio.to_thread(
            set_member_level, _app(self.bot).database, guild.id, interaction.user.id, chosen
        )
        await answer(interaction, "Réactions sur tes messages", f"**{niveau.name}**")


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
        await refuse(interaction, "Salon de serveur requis.")
        return
    guild, channel = place
    database = _app(bot).database
    if everyone is not None:
        await asyncio.to_thread(save_everyone, database, channel.id, guild.id, everyone)
        state = "activée" if everyone else "désactivée"
        await answer(interaction, "@everyone et @here", f"Réponse **{state}** dans ce salon.")
        return
    enabled = bool(transcribe)
    await asyncio.to_thread(save_transcribe, database, channel.id, guild.id, enabled)
    state = "activée" if enabled else "désactivée"
    await answer(interaction, "Vocaux", f"Transcription automatique **{state}** dans ce salon.")


_MODES_TEXT = {
    "off": "désactivée",
    "strict": "mention, réponse ou prénom",
    "greedy": "aussi quand on parle d'elle",
}


def _snapshot(app: App, guild_id: int, channel_id: int) -> tuple[str, str]:
    guild = app.database.fetchone(
        """
        SELECT mode, spontaneity, python_blocked, reply_limit
        FROM guild_settings WHERE guild_id = ?
        """,
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
    limit = "aucune" if guild is None else _LIMIT_NAMES.get(str(guild["reply_limit"]), "aucune")
    flags = [
        ("@everyone", channel is not None and bool(channel["respond_everyone"])),
        ("Vocaux transcrits", channel is not None and bool(channel["auto_transcribe"])),
        ("run_python", guild is None or not guild["python_blocked"]),
    ]
    messages, tokens, ceiling = app.conversation.usage(channel_id)
    share = min(100, round(100 * tokens / ceiling)) if ceiling else 0
    filled = share // 5
    lines = [
        f"**Messages** · {messages}",
        f"**Tokens** · {tokens:,} / {ceiling:,}".replace(",", " "),
        f"`{'█' * filled}{'░' * (20 - filled)}` {share} %",
        "",
        f"**Spontanéité** · {spontaneity}",
        f"**Limite de réponses** · {limit}",
        " · ".join(f"{label} {'✅' if on else '❌'}" for label, on in flags),
        f"-# {len(app.capabilities.names())} outils disponibles",
    ]
    return "\n".join(lines), _MODES_TEXT.get(mode, mode)


def _stamp() -> str:
    return datetime.now(UTC).isoformat()
