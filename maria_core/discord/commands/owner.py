"""Commandes réservées au propriétaire : processus, extensions, synchronisation."""

import logging
import os
import sys
from datetime import UTC, datetime
from typing import Literal

import discord
from discord.ext import commands

from maria_core import __version__
from maria_core.app import App
from maria_core.errors import PluginError

logger = logging.getLogger(__name__)


def _app(bot: commands.Bot) -> App:
    app = getattr(bot, "app", None)
    if not isinstance(app, App):
        raise RuntimeError("Le bot n'est pas relié à une application.")
    return app


def _uptime(bot: commands.Bot) -> str:
    started = getattr(bot, "started_at", None)
    if not isinstance(started, datetime):
        return "inconnue"
    total = max(0, int((datetime.now(UTC) - started).total_seconds()))
    hours, rest = divmod(total, 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{hours} h {minutes} min {seconds} s"


class OwnerCommands(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.command(name="ping")
    @commands.is_owner()
    async def ping(self, ctx: commands.Context) -> None:
        """Latence de la connexion Discord."""
        await ctx.send(f"Pong. `{round(self.bot.latency * 1000)} ms`")

    @commands.command(name="status")
    @commands.is_owner()
    async def status(self, ctx: commands.Context) -> None:
        """Version, base et extensions chargées."""
        app = _app(self.bot)
        names = ", ".join(app.plugins.names) or "aucune"
        await ctx.send(
            f"maria-core `{__version__}`\n"
            f"Disponibilité : {_uptime(self.bot)}\n"
            f"Base : v{app.database.version}\n"
            f"Extensions : {names}\n"
            f"Serveurs : {len(self.bot.guilds)}"
        )

    @commands.command(name="restart")
    @commands.is_owner()
    async def restart(self, ctx: commands.Context) -> None:
        """Relance le processus."""
        await ctx.send("Redémarrage…")
        logger.info("Redémarrage demandé par %s", ctx.author)
        await self.bot.close()
        os.execv(sys.executable, [sys.executable, *sys.argv])

    @commands.group(name="plugin", invoke_without_command=True)
    @commands.is_owner()
    async def plugin(self, ctx: commands.Context) -> None:
        """Liste les extensions chargées."""
        names = ", ".join(_app(self.bot).plugins.names) or "aucune"
        await ctx.send(f"Extensions : {names}")

    @plugin.command(name="load")
    @commands.is_owner()
    async def plugin_load(self, ctx: commands.Context, module_name: str) -> None:
        """Charge une extension par son nom de module."""
        try:
            name = _app(self.bot).plugins.load(module_name)
        except PluginError as exc:
            await ctx.send(f"Chargement impossible : {exc}")
            return
        await ctx.send(f"Extension `{name}` chargée.")

    @plugin.command(name="unload")
    @commands.is_owner()
    async def plugin_unload(self, ctx: commands.Context, name: str) -> None:
        """Décharge une extension par son NAME."""
        try:
            _app(self.bot).plugins.unload(name)
        except PluginError as exc:
            await ctx.send(f"Déchargement impossible : {exc}")
            return
        await ctx.send(f"Extension `{name}` déchargée.")

    @plugin.command(name="reload")
    @commands.is_owner()
    async def plugin_reload(self, ctx: commands.Context, name: str) -> None:
        """Recharge une extension par son NAME."""
        try:
            loaded = _app(self.bot).plugins.reload(name)
        except PluginError as exc:
            await ctx.send(f"Rechargement impossible : {exc}")
            return
        await ctx.send(f"Extension `{loaded}` rechargée.")

    @commands.command(name="sync")
    @commands.guild_only()
    @commands.is_owner()
    async def sync(
        self,
        ctx: commands.Context,
        guilds: commands.Greedy[discord.Object],
        spec: Literal["~", "*", "^"] | None = None,
    ) -> None:
        """Synchronise les commandes slash.

        Sans argument : globales. ~ serveur courant. * copie les globales ici.
        ^ efface celles du serveur. Des identifiants peuvent suivre.
        """
        if guilds:
            await self._sync_many(ctx, guilds)
            return
        await self._sync_one(ctx, spec)

    async def _sync_many(
        self,
        ctx: commands.Context,
        guilds: list[discord.Object],
    ) -> None:
        done = 0
        for guild in guilds:
            try:
                await ctx.bot.tree.sync(guild=guild)
            except discord.HTTPException:
                logger.warning("Synchronisation impossible pour le serveur %s", guild.id)
            else:
                done += 1
        await ctx.send(f"Arbre synchronisé dans {done}/{len(guilds)} serveur(s).")

    async def _sync_one(self, ctx: commands.Context, spec: Literal["~", "*", "^"] | None) -> None:
        guild = ctx.guild
        if spec is None:
            synced = await ctx.bot.tree.sync()
            scope = "globales"
        elif guild is None:
            await ctx.send("Cette synchronisation doit être lancée sur un serveur.")
            return
        else:
            synced = await _sync_guild(ctx, guild, spec)
            scope = f"sur {guild.name}"
        rendered = ", ".join(f"`{command.name}`" for command in synced) if synced else "—"
        await ctx.send(f"{len(synced)} commande(s) synchronisée(s) ({scope}) : {rendered}")


async def _sync_guild(
    ctx: commands.Context,
    guild: discord.Guild,
    spec: Literal["~", "*", "^"],
) -> list[discord.app_commands.AppCommand]:
    if spec == "*":
        ctx.bot.tree.copy_global_to(guild=guild)
    elif spec == "^":
        ctx.bot.tree.clear_commands(guild=guild)
        await ctx.bot.tree.sync(guild=guild)
        return []
    return await ctx.bot.tree.sync(guild=guild)
