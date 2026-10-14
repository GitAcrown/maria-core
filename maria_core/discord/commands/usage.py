"""`usage` : ce que MARIA a consommé et ce qui échoue, lu dans les journaux d'appels."""

import asyncio
from datetime import UTC, datetime, timedelta

from discord.ext import commands

from maria_core.app import App
from maria_core.db import Database
from maria_core.discord.hub import say

_DAYS = 7
_TOOLS_SHOWN = 12


def usage_report(database: Database, now: datetime, days: int = _DAYS) -> tuple[str, str]:
    """(texte, méta) du bilan des `days` derniers jours."""
    since = (now - timedelta(days=days)).isoformat()
    models = database.fetchall(
        """
        SELECT purpose, model, COUNT(*) AS calls, SUM(input_tokens) AS tokens_in,
               SUM(output_tokens) AS tokens_out, SUM(1 - ok) AS failed,
               CAST(AVG(duration_ms) AS INTEGER) AS average
        FROM llm_calls WHERE at >= ? GROUP BY purpose, model ORDER BY tokens_in DESC
        """,
        (since,),
    )
    tools = database.fetchall(
        """
        SELECT name, COUNT(*) AS calls, SUM(1 - ok) AS failed,
               CAST(AVG(duration_ms) AS INTEGER) AS average
        FROM capability_calls WHERE at >= ? GROUP BY name ORDER BY calls DESC LIMIT ?
        """,
        (since, _TOOLS_SHOWN),
    )
    lines = ["### Modèle"]
    for row in models:
        lines.append(
            f"**{row['purpose']}** · {row['model'] or '?'} · {row['calls']} appel(s) · "
            f"{_tokens(row['tokens_in'])} → {_tokens(row['tokens_out'])} · {row['average']} ms"
            + (f" · **{row['failed']} échec(s)**" if row["failed"] else "")
        )
    if not models:
        lines.append("*Aucun appel.*")
    lines.append("### Outils")
    for row in tools:
        lines.append(
            f"`{row['name']}` · {row['calls']} appel(s) · {row['average']} ms"
            + (f" · **{row['failed']} échec(s)**" if row["failed"] else "")
        )
    if not tools:
        lines.append("*Aucun appel.*")
    return "\n".join(lines), f"{days} derniers jours"


def _tokens(value: int | None) -> str:
    count = int(value or 0)
    return f"{count / 1000:.1f}k" if count >= 1000 else str(count)


class UsageCommands(commands.Cog):
    def __init__(self, bot: commands.Bot, app: App) -> None:
        self.bot = bot
        self.app = app

    @commands.command(name="usage")
    @commands.is_owner()
    async def usage(self, ctx: commands.Context, days: int = _DAYS) -> None:
        """Appels au modèle et aux outils sur les derniers jours (1 à 90)."""
        span = max(1, min(90, days))
        text, meta = await asyncio.to_thread(
            usage_report, self.app.database, datetime.now(UTC), span
        )
        await say(ctx, "Usage", text, meta=meta)
