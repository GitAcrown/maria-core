"""Clic droit sur un message → « Demander à MARIA » : résumer, traduire ou expliquer.

La réponse est éphémère (elle seule la voit), sans bouton ni suite possible, et n'entre dans
aucune mémoire de conversation.
"""

import logging

import discord
from discord import app_commands
from discord.ext import commands

from maria_core.app import App
from maria_core.conversation.assist import CHOICES, Assistant, Choice
from maria_core.discord.hub import NO_PINGS, Action, Hub, Run, body, card, title, wide

logger = logging.getLogger(__name__)

NAME = "Demander à MARIA"


class AskHub(Hub):
    """Le choix de l'action, devant celui qui a fait le clic droit."""

    def __init__(self, assistant: Assistant, message: discord.Message, user_id: int) -> None:
        super().__init__(viewer_id=user_id)
        self.assistant = assistant
        self.message = message

    def build(self) -> None:
        author = self.message.author.display_name
        content = [
            title("Demander à MARIA", f"Message de {author}"),
            wide(),
            body("Que veux-tu faire de ce message ?"),
        ]
        buttons = [Action(choice.button, self._run(choice)) for choice in CHOICES]
        self.set_layout(content, discord.ui.ActionRow(*buttons))

    def _run(self, choice: Choice) -> Run:
        async def run(interaction: discord.Interaction) -> None:
            await self._answer(interaction, choice)

        return run

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
            _text_of(self.message),
            user_id=interaction.user.id,
            author=self.message.author.display_name,
        )
        author = self.message.author.display_name
        await interaction.edit_original_response(
            view=card(action.title, text, meta=f"Message de {author}"), allowed_mentions=NO_PINGS
        )
        self.stop()


def _text_of(message: discord.Message) -> str:
    """Le texte du message, plus le texte de ses aperçus (liens, citations)."""
    parts = [message.content or ""]
    parts += [embed.description for embed in message.embeds if embed.description]
    return "\n\n".join(part.strip() for part in parts if part and part.strip())


class AskCog(commands.Cog):
    def __init__(self, bot: commands.Bot, app: App) -> None:
        self.bot = bot
        self.assistant = Assistant(app.llm)
        self._menu = app_commands.ContextMenu(name=NAME, callback=self.ask)
        self._menu.guild_only = True

    async def cog_load(self) -> None:
        self.bot.tree.add_command(self._menu)

    async def cog_unload(self) -> None:
        self.bot.tree.remove_command(NAME, type=self._menu.type)

    async def ask(self, interaction: discord.Interaction, message: discord.Message) -> None:
        hub = AskHub(self.assistant, message, interaction.user.id)
        await hub.open(interaction)
