"""`moi` et `global` : souvenirs acceptés et propositions encore ouvertes."""

import asyncio

import discord
from discord.ext import commands

from maria_core.app import App
from maria_core.memory.policy import Actor
from maria_core.memory.service import render_moi
from maria_core.memory.store import MemoryDenied


def _app(bot: commands.Bot) -> App:
    app = getattr(bot, "app", None)
    if not isinstance(app, App):
        raise RuntimeError("Le bot n'est pas relié à une application.")
    return app


class MemoryCommands(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.group(name="moi", invoke_without_command=True)
    async def moi(self, ctx: commands.Context) -> None:
        """Souvenirs et propositions de la personne."""
        app = _app(self.bot)
        text = render_moi(
            await asyncio.to_thread(app.memory.store.list_for, ctx.author.id),
            await asyncio.to_thread(app.memory.store.open_for, ctx.author.id),
        )
        await ctx.send(text[:2000])

    @moi.command(name="retenir")
    async def retenir(self, ctx: commands.Context, proposal_id: int) -> None:
        """Accepte une proposition."""
        await self._resolve(ctx, proposal_id, accept=True)

    @moi.command(name="ignorer")
    async def ignorer(self, ctx: commands.Context, proposal_id: int) -> None:
        """Ignore une proposition."""
        await self._resolve(ctx, proposal_id, accept=False)

    @commands.command(name="global")
    async def guild_memory(self, ctx: commands.Context) -> None:
        """Souvenirs du serveur. Modérateurs."""
        if ctx.guild is None:
            await ctx.send("Cette commande est pour un serveur.")
            return
        if not await self._can_manage(ctx):
            await ctx.send("Réservé aux modérateurs.")
            return
        memories = await asyncio.to_thread(_app(self.bot).memory.store.list_guild, ctx.guild.id)
        lines = [f"- #{item.id} {item.content}" for item in memories]
        await ctx.send("\n".join(lines)[:2000] or "Aucun souvenir de serveur.")

    async def _resolve(self, ctx: commands.Context, proposal_id: int, *, accept: bool) -> None:
        app = _app(self.bot)
        actor = await _actor(ctx)
        try:
            if accept:
                await asyncio.to_thread(
                    app.memory.store.accept, proposal_id, actor, app.memory.now()
                )
                await ctx.send("C'est noté.")
            else:
                await asyncio.to_thread(
                    app.memory.store.ignore, proposal_id, actor, app.memory.now()
                )
                await ctx.send("Proposition ignorée.")
        except (MemoryDenied, ValueError) as exc:
            await ctx.send(str(exc))

    async def _can_manage(self, ctx: commands.Context) -> bool:
        if await self.bot.is_owner(ctx.author):
            return True
        permissions = getattr(ctx.author, "guild_permissions", None)
        return bool(permissions and permissions.manage_messages)


async def _actor(ctx: commands.Context) -> Actor:
    return Actor(
        ctx.author.id,
        await ctx.bot.is_owner(ctx.author),
        bool(
            isinstance(ctx.author, discord.Member) and ctx.author.guild_permissions.manage_messages
        ),
    )
