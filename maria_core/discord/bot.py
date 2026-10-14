"""Adaptateur Discord. Aucune règle métier : il publie et affiche."""

import asyncio
import logging
from datetime import UTC, datetime

import discord
from discord.ext import commands

from maria_core.app import App
from maria_core.discord.chat import ChatCog
from maria_core.discord.commands.owner import OwnerCommands
from maria_core.discord.commands.public import PublicCommands
from maria_core.discord.commands.social import SocialCommands
from maria_core.discord.commands.usage import UsageCommands
from maria_core.discord.directory import DiscordDirectory
from maria_core.discord.layout import use_emojis
from maria_core.discord.learned_view import restore_learned
from maria_core.discord.memory_view import restore_proposals
from maria_core.discord.objectives import DiscordCourier
from maria_core.discord.polls import DiscordPolls
from maria_core.discord.presence import PresenceCog
from maria_core.discord.reactions import ReactionCog
from maria_core.discord.reading import DiscordHistory
from maria_core.discord.signals import SignalCog
from maria_core.discord.voice import VoiceCog
from maria_core.ui.emojis import FALLBACKS, emoji_id

logger = logging.getLogger(__name__)

_HOUSEKEEPING_SECONDS = 6 * 3600


async def on_app_command_error(
    interaction: discord.Interaction, error: discord.app_commands.AppCommandError
) -> None:
    """Une commande slash ne reste jamais sans réponse : message clair, jamais d'exception brute."""
    if isinstance(error, discord.app_commands.CommandOnCooldown):
        text = f"**Cooldown ·** Réessaie dans {_delay(error.retry_after)}."
    elif isinstance(error, discord.app_commands.MissingPermissions):
        missing = ", ".join(f"`{item}`" for item in error.missing_permissions)
        text = f"**Action impossible ·** Permission manquante : {missing}."
    elif isinstance(error, discord.app_commands.CheckFailure):
        text = "**Action impossible ·** Tu ne peux pas utiliser cette commande ici."
    else:
        logger.error("Commande slash en échec", exc_info=error)
        text = "**Erreur ·** Une erreur est survenue, réessaie dans un instant."
    try:
        if interaction.response.is_done():
            await interaction.followup.send(text, ephemeral=True)
        else:
            await interaction.response.send_message(text, ephemeral=True, delete_after=20)
    except discord.HTTPException:
        logger.debug("Erreur de commande non signalée", exc_info=True)


def _delay(seconds: float) -> str:
    minutes, secs = divmod(round(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    parts = [
        f"{hours} h" if hours else "",
        f"{minutes} min" if minutes else "",
        f"{secs} s" if secs else "",
    ]
    return " ".join(part for part in parts if part) or "quelques instants"


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
        self.tree.on_error = on_app_command_error

    async def setup_hook(self) -> None:
        app = self.app
        app.bind_discord(
            directory=DiscordDirectory(self),
            poster=DiscordPolls(self, app.polls),
            reader=DiscordHistory(self),
        )
        restore_proposals(self, app.memory.store.restorable())
        restore_learned(self, app)
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
            SignalCog(self, app),
            reactions,
            SocialCommands(self),
            UsageCommands(self, app),
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
        await self._check_emojis()

    async def _check_emojis(self) -> None:
        """Emojis du serveur et de l'application : les emojis custom absents passent en Unicode."""
        usable = {emoji.id for emoji in self.emojis}
        try:
            usable |= {emoji.id for emoji in await self.fetch_application_emojis()}
        except discord.HTTPException:
            logger.debug("Emojis d'application illisibles", exc_info=True)
        use_emojis(usable)
        missing = [tag for tag in FALLBACKS if emoji_id(tag) not in usable]
        if missing:
            logger.warning("Emojis custom inaccessibles, repli Unicode : %s", ", ".join(missing))

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
