"""Niveau de spontanéité, explication d'une réaction, gag du serveur."""

from datetime import UTC, datetime

from discord.ext import commands

from maria_core.app import App
from maria_core.discord.hub import say
from maria_core.social.levels import set_level


def _app(bot: commands.Bot) -> App:
    app = getattr(bot, "app", None)
    if not isinstance(app, App):
        raise RuntimeError("Le bot n'est pas relié à une application.")
    return app


class SocialCommands(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.command(name="spontaneite")
    async def spontaneite(self, ctx: commands.Context, level: str) -> None:
        """off, quiet, normal ou chatty. Modérateurs."""
        if ctx.guild is None:
            await say(ctx, "Action impossible", "Cette commande est pour un serveur.")
            return
        if not await _can_manage(ctx):
            await say(ctx, "Action impossible", "Réservé aux modérateurs.")
            return
        try:
            chosen = set_level(_app(self.bot).database, ctx.guild.id, level, _stamp())
        except ValueError as exc:
            await say(ctx, "Action impossible", str(exc))
            return
        await say(ctx, "Spontanéité", f"**{chosen.name}**")

    @commands.command(name="why")
    @commands.is_owner()
    async def why(self, ctx: commands.Context, reference: str) -> None:
        """Pourquoi MARIA a réagi, ou non, à un message."""
        message_id = _message_id(reference)
        if message_id is None:
            await say(ctx, "Action impossible", "Donne l'identifiant ou le lien du message.")
            return
        explained = _app(self.bot).social.explain(message_id)[:3500]
        await say(ctx, "Pourquoi cette réaction ?", explained, meta=f"message {message_id}")


def _message_id(reference: str) -> int | None:
    token = reference.strip().rstrip("/").split("/")[-1]
    if token.isdigit():
        return int(token)
    return None


def _stamp() -> str:
    return datetime.now(UTC).isoformat()


async def _can_manage(ctx: commands.Context) -> bool:
    if await ctx.bot.is_owner(ctx.author):
        return True
    permissions = getattr(ctx.author, "guild_permissions", None)
    return bool(permissions and permissions.manage_messages)
