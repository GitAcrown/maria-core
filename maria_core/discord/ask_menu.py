"""Clic droit sur un message → « Demander à MARIA » : résumer, traduire ou expliquer.

La réponse est éphémère (elle seule la voit), sans bouton ni suite possible, et n'entre dans
aucune mémoire de conversation. Les modérateurs ont en plus « Retenir pour le serveur ».
"""

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

from maria_core.app import App
from maria_core.conversation.assist import BY_KEY, CHOICES, Assistant, Choice
from maria_core.discord.hub import (
    NO_PINGS,
    Hub,
    Picker,
    body,
    card,
    option,
    refuse,
    title,
    wide,
)
from maria_core.discord.message_text import text_of
from maria_core.memory.policy import Actor
from maria_core.memory.store import MemoryDenied

logger = logging.getLogger(__name__)

NAME = "Demander à MARIA"
_KEEP_CHARS = 500
_KEEP = "keep"


class AskHub(Hub):
    """Le choix de l'action, devant celui qui a fait le clic droit."""

    def __init__(
        self,
        assistant: Assistant,
        message: discord.Message,
        user_id: int,
        *,
        app: App | None = None,
        actor: Actor | None = None,
    ) -> None:
        super().__init__(viewer_id=user_id)
        self.assistant = assistant
        self.target = message  # le message visé : `self.message` est celui du menu lui-même
        self.app = app
        self.actor = actor

    @property
    def can_keep(self) -> bool:
        """Seuls les modérateurs (et le propriétaire) écrivent dans la mémoire du serveur."""
        return (
            self.app is not None
            and self.actor is not None
            and (self.actor.is_moderator or self.actor.is_owner)
        )

    def build(self) -> None:
        author = self.target.author.name
        content = [
            title("Demander à MARIA", f"Message de {author}"),
            wide(),
            body("Que veux-tu faire de ce message ?"),
        ]
        options = [option(choice.key, choice.button) for choice in CHOICES]
        if self.can_keep:
            options.append(option(_KEEP, "Retenir pour le serveur"))
        picker = Picker("Choisir une action…", options, self._pick)
        self.set_layout(content, discord.ui.ActionRow(picker))

    async def _pick(self, interaction: discord.Interaction, value: str) -> None:
        if value == _KEEP:
            await self._keep(interaction)
        elif value in BY_KEY:
            await self._answer(interaction, BY_KEY[value])

    async def _keep(self, interaction: discord.Interaction) -> None:
        text = text_of(self.target)
        if not text:
            await refuse(interaction, "Ce message n'a pas de texte à retenir.")
            return
        await interaction.response.send_modal(_Keep(self, text))

    async def _answer(self, interaction: discord.Interaction, action: Choice) -> None:
        wait = self.assistant.wait_for(interaction.user.id)
        if wait > 0:
            await interaction.response.edit_message(
                view=card(action.title, f"Doucement : réessaie dans {int(wait) + 1} s."),
                allowed_mentions=NO_PINGS,
            )
            return
        await interaction.response.edit_message(
            view=card(action.title, "Je m'en occupe…"), allowed_mentions=NO_PINGS
        )
        text = await self.assistant.run(
            action.key,
            text_of(self.target),
            user_id=interaction.user.id,
            author=self.target.author.name,
        )
        author = self.target.author.name
        await interaction.edit_original_response(
            view=card(action.title, text, meta=f"Message de {author}"), allowed_mentions=NO_PINGS
        )
        self.stop()


class _Keep(discord.ui.Modal, title="Retenir pour le serveur"):
    """Le texte du message, modifiable avant d'entrer dans la mémoire du serveur."""

    def __init__(self, hub: AskHub, text: str) -> None:
        super().__init__()
        self.hub = hub
        self.fact = discord.ui.TextInput(
            label="Ce que MARIA doit retenir",
            style=discord.TextStyle.paragraph,
            default=text[:_KEEP_CHARS],
            max_length=_KEEP_CHARS,
        )
        self.add_item(self.fact)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        hub = self.hub
        app, actor = hub.app, hub.actor
        guild_id = interaction.guild_id or 0
        heading, text, meta = "Retenu pour le serveur", "C'est noté.", "À retrouver dans /global"
        try:
            if app is None or actor is None:
                raise MemoryDenied("La mémoire du serveur est réservée aux modérateurs.")
            await asyncio.to_thread(
                app.memory.store.remember,
                actor,
                scope="guild",
                subject_id=guild_id,
                guild_id=guild_id,
                content=str(self.fact.value),
                source="explicit",
                now=app.memory.now(),
            )
        except (MemoryDenied, ValueError) as exc:
            heading, text, meta = "Rien n'a été retenu", str(exc), ""
        await interaction.response.edit_message(
            view=card(heading, text, meta=meta), allowed_mentions=NO_PINGS
        )
        hub.stop()


class AskCog(commands.Cog):
    def __init__(self, bot: commands.Bot, app: App) -> None:
        self.bot = bot
        self.app = app
        self.assistant = Assistant(app.llm)
        self._menu = app_commands.ContextMenu(name=NAME, callback=self.ask)
        self._menu.guild_only = True

    async def cog_load(self) -> None:
        self.bot.tree.add_command(self._menu)

    async def cog_unload(self) -> None:
        self.bot.tree.remove_command(NAME, type=self._menu.type)

    async def ask(self, interaction: discord.Interaction, message: discord.Message) -> None:
        user = interaction.user
        permissions = getattr(user, "guild_permissions", None)
        actor = Actor(
            user.id,
            await interaction.client.is_owner(user),
            bool(permissions and permissions.manage_messages),
        )
        hub = AskHub(self.assistant, message, user.id, app=self.app, actor=actor)
        await hub.open(interaction)
