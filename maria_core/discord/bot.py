"""Adaptateur Discord. Aucune règle métier : il publie et affiche."""

import asyncio
import logging
from datetime import UTC, datetime

import discord
from discord.ext import commands

from maria_core.app import App
from maria_core.discord.chat import ChatCog
from maria_core.discord.commands.memory import MemoryCommands
from maria_core.discord.commands.owner import OwnerCommands
from maria_core.discord.commands.public import PublicCommands
from maria_core.discord.commands.social import SocialCommands
from maria_core.discord.directory import DiscordDirectory
from maria_core.discord.memory_view import restore_proposals
from maria_core.discord.objectives import DiscordCourier, restore_drafts
from maria_core.discord.polls import DiscordPolls
from maria_core.discord.presence import PresenceCog
from maria_core.discord.reactions import ReactionCog
from maria_core.discord.reading import DiscordHistory
from maria_core.discord.signals import SignalCog
from maria_core.discord.voice import VoiceCog

logger = logging.getLogger(__name__)

_HOUSEKEEPING_SECONDS = 6 * 3600


def build_intents() -> discord.Intents:
    """Intents privilégiés nécessaires à la conversation, à la voix et aux membres."""
    intents = discord.Intents.default()
    intents.message_content = True
    intents.members = True
    intents.voice_states = True
    return intents


class MariaBot(commands.Bot):
    def __init__(self, app: App) -> None:
        super().__init__(
            command_prefix=app.settings.command_prefix,
            intents=build_intents(),
            help_command=None,
            application_id=app.settings.app_id,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        self.app = app
        self.started_at = datetime.now(UTC)
        self._objectives_task: asyncio.Task[None] | None = None
        self._housekeeping_task: asyncio.Task[None] | None = None

    async def setup_hook(self) -> None:
        app = self.app
        app.bind_discord(
            directory=DiscordDirectory(self),
            poster=DiscordPolls(self, app.polls),
            reader=DiscordHistory(self),
        )
        restore_proposals(self, app.memory.store.restorable())
        restore_drafts(self, app)
        app.objectives.runner.courier = DiscordCourier(self)
        reactions = ReactionCog(self, app)
        app.social.reactor = reactions.add
        app.social.usable = reactions.usable
        app.drafts.reactor = reactions.add
        self._objectives_task = asyncio.create_task(app.objectives.scheduler.run())
        self._housekeeping_task = asyncio.create_task(self._housekeep())
        for cog in (
            OwnerCommands(self),
            ChatCog(self, app),
            VoiceCog(self, app),
            MemoryCommands(self),
            SignalCog(self, app),
            reactions,
            SocialCommands(self),
            PublicCommands(self),
            PresenceCog(self, app.settings.data_dir / "statuses.txt"),
        ):
            await self.add_cog(cog)

    async def close(self) -> None:
        self.app.objectives.scheduler.stop()
        for task in (self._objectives_task, self._housekeeping_task):
            if task is not None:
                task.cancel()
        await super().close()

    async def _housekeep(self) -> None:
        while True:
            try:
                removed = await asyncio.to_thread(self.app.housekeeping)
            except Exception:
                logger.exception("Entretien périodique en échec")
            else:
                if any(removed.values()):
                    logger.info("Entretien : %s", removed)
            await asyncio.sleep(_HOUSEKEEPING_SECONDS)

    async def on_ready(self) -> None:
        user = self.user
        if user is None:
            return
        logger.info(
            "Connecté en tant que %s (%s), discord.py %s, %s serveur(s)",
            user,
            user.id,
            discord.__version__,
            len(self.guilds),
        )

    async def on_command_error(
        self,
        context: commands.Context,
        exception: commands.CommandError,
    ) -> None:
        error: Exception = exception
        if isinstance(exception, commands.CommandInvokeError) and exception.original is not None:
            error = exception.original
        if isinstance(error, commands.CommandNotFound):
            return
        if isinstance(error, commands.NotOwner):
            await context.send("Cette commande est réservée au propriétaire.")
            return
        if isinstance(error, commands.MissingRequiredArgument):
            await context.send(f"Argument manquant : `{error.param.name}`.")
            return
        logger.error("Commande %s échouée", context.command, exc_info=error)
        await context.send("Une erreur est survenue.")
