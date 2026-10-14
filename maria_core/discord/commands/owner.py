"""Commandes réservées au propriétaire : processus, extensions, synchronisation."""

import asyncio
import logging
import os
import subprocess
import sys
from datetime import UTC, datetime
from typing import Literal

import discord
from discord.ext import commands

from maria_core import __version__
from maria_core.app import App
from maria_core.discord.hub import say
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


def _keys(settings: object) -> list[tuple[str, str]]:
    names = (
        "token",
        "openai_api_key",
        "typesafe_api_key",
        "brave_api_key",
        "tmdb_api_key",
        "openweathermap_api_key",
        "spotify_client_id",
        "spotify_client_secret",
        "prim_api_key",
        "sncf_api_key",
        "api_football_key",
    )
    return [(name.upper(), str(getattr(settings, name, "") or "")) for name in names]


def _mask(value: str) -> str:
    if not value:
        return "manquante"
    if len(value) <= 6:
        return f"présente ({len(value)} car.)"
    return f"présente (…{value[-4:]})"


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
        lines = [
            f"**Disponibilité** · {_uptime(self.bot)}",
            f"**Latence** · {round(self.bot.latency * 1000)} ms",
            f"**Base** · v{app.database.version}",
            f"**Serveurs** · {len(self.bot.guilds)}",
            f"**Extensions** · {names}",
        ]
        await say(ctx, "MARIA", "\n".join(lines), meta=f"maria-core {__version__}")

    @commands.command(name="restart")
    @commands.is_owner()
    async def restart(self, ctx: commands.Context) -> None:
        """Relance le processus."""
        await ctx.send("Redémarrage…")
        logger.info("Redémarrage demandé par %s", ctx.author)
        await self.bot.close()
        os.execv(sys.executable, [sys.executable, *sys.argv])

    @commands.command(name="shutdown")
    @commands.is_owner()
    async def shutdown(self, ctx: commands.Context) -> None:
        """Arrête proprement le processus."""
        await ctx.send("Arrêt…")
        logger.info("Arrêt demandé par %s", ctx.author)
        await self.bot.close()

    @commands.command(name="update")
    @commands.is_owner()
    async def update(self, ctx: commands.Context) -> None:
        """git pull, puis redémarrage si tout s'est bien passé."""
        await ctx.send("Mise à jour…")
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                ["git", "pull", "--ff-only"],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            await ctx.send(f"git pull impossible : {exc}")
            return
        output = (result.stdout or result.stderr or "(aucune sortie)").strip()[:1800]
        if result.returncode != 0:
            await ctx.send(f"Échec de git pull :\n```\n{output}\n```")
            return
        await ctx.send(f"Mise à jour faite :\n```\n{output}\n```\nRedémarrage…")
        await self.bot.close()
        os.execv(sys.executable, [sys.executable, *sys.argv])

    @commands.command(name="keys")
    @commands.is_owner()
    async def keys(self, ctx: commands.Context) -> None:
        """Clés de configuration présentes ou manquantes, masquées."""
        settings = _app(self.bot).settings
        rows = [f"`{name}` · {_mask(value)}" for name, value in _keys(settings)]
        await say(ctx, "Clés", "\n".join(rows), meta="valeurs masquées")

    @commands.group(name="plugin", invoke_without_command=True)
    @commands.is_owner()
    async def plugin(self, ctx: commands.Context) -> None:
        """Liste les extensions chargées."""
        names = _app(self.bot).plugins.names
        listed = "\n".join(f"`{name}`" for name in names) or "*Aucune extension chargée.*"
        await say(ctx, "Extensions", listed, meta=f"{len(names)} chargée(s)")

    @plugin.command(name="load")
    @commands.is_owner()
    async def plugin_load(self, ctx: commands.Context, module_name: str) -> None:
        """Charge une extension par son nom de module."""
        try:
            name = _app(self.bot).plugins.load(module_name)
        except PluginError as exc:
            await ctx.send(f"Chargement impossible : {exc}")
            return
        await say(ctx, "Extension chargée", f"`{name}`")

    @plugin.command(name="unload")
    @commands.is_owner()
    async def plugin_unload(self, ctx: commands.Context, name: str) -> None:
        """Décharge une extension par son NAME."""
        try:
            _app(self.bot).plugins.unload(name)
        except PluginError as exc:
            await ctx.send(f"Déchargement impossible : {exc}")
            return
        await say(ctx, "Extension déchargée", f"`{name}`")

    @plugin.command(name="reload")
    @commands.is_owner()
    async def plugin_reload(self, ctx: commands.Context, name: str) -> None:
        """Recharge une extension par son NAME."""
        try:
            loaded = _app(self.bot).plugins.reload(name)
        except PluginError as exc:
            await ctx.send(f"Rechargement impossible : {exc}")
            return
        await say(ctx, "Extension rechargée", f"`{loaded}`")

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
        await say(ctx, "Commandes synchronisées", f"{done}/{len(guilds)} serveur(s).")

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
        rendered = "\n".join(f"`/{command.name}`" for command in synced) or "*Aucune.*"
        await say(ctx, "Commandes synchronisées", rendered, meta=f"{len(synced)} · {scope}")


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
