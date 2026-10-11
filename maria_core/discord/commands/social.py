"""Niveau de spontanéité, explication d'une réaction, gag du serveur."""

from datetime import UTC, datetime

from discord.ext import commands

from maria_core.app import App
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
            await ctx.send("Cette commande est pour un serveur.")
            return
        if not await _can_manage(ctx):
            await ctx.send("Réservé aux modérateurs.")
            return
        try:
            chosen = set_level(_app(self.bot).database, ctx.guild.id, level, _stamp())
        except ValueError as exc:
            await ctx.send(str(exc))
            return
        await ctx.send(f"Spontanéité : {chosen.name}.")

    @commands.command(name="why")
    @commands.is_owner()
    async def why(self, ctx: commands.Context, reference: str) -> None:
        """Pourquoi MARIA a réagi, ou non, à un message."""
        message_id = _message_id(reference)
        if message_id is None:
            await ctx.send("Donne l'identifiant ou le lien du message.")
            return
        await ctx.send(_app(self.bot).social.explain(message_id)[:2000])


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
