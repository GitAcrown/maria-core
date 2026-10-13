"""Carte de brouillon sous la réponse de MARIA : ce qui va être créé, Confirmer / Annuler.

Persistante : les boutons survivent au redémarrage. Après un clic, la carte montre l'issue.
"""

import asyncio

import discord

from maria_core.app import App
from maria_core.discord.hub import NO_PINGS, body, clip, thin, title, wide
from maria_core.discord.task_menu import objective_facts
from maria_core.objectives.labels import kind_label
from maria_core.objectives.model import Objective, StaleObjective
from maria_core.objectives.tools import apply

_HINT = "-# Confirme ici, ou réponds « oui » / « non » dans le salon."


class DraftView(discord.ui.LayoutView):
    def __init__(self, objective_id: int, objective: Objective | None = None) -> None:
        super().__init__(timeout=None)
        self.objective_id = objective_id
        confirm = discord.ui.Button(
            label="Confirmer",
            style=discord.ButtonStyle.success,
            custom_id=f"maria:obj:{objective_id}:yes",
        )
        cancel = discord.ui.Button(
            label="Annuler",
            style=discord.ButtonStyle.secondary,
            custom_id=f"maria:obj:{objective_id}:no",
        )
        confirm.callback = self._confirm
        cancel.callback = self._cancel
        items: list[discord.ui.Item] = []
        if objective is not None:
            items += [*draft_card(objective, "brouillon · à confirmer"), body(_HINT), thin()]
        items.append(discord.ui.ActionRow(confirm, cancel))
        self.add_item(discord.ui.Container(*items))

    async def _confirm(self, interaction: discord.Interaction) -> None:
        await settle(interaction, self.objective_id, "confirm")

    async def _cancel(self, interaction: discord.Interaction) -> None:
        await settle(interaction, self.objective_id, "cancel")


def draft_card(objective: Objective, meta: str) -> list[discord.ui.Item]:
    kind = kind_label(objective.trigger, objective.action, objective.condition)
    return [
        title(clip(f"{kind} · {objective.title}", 90), meta),
        wide(),
        body(objective_facts(objective)),
    ]


def outcome(objective: Objective, confirmed: bool) -> discord.ui.LayoutView:
    """La carte une fois tranchée, sans boutons."""
    view = discord.ui.LayoutView(timeout=None)
    if confirmed:
        view.add_item(discord.ui.Container(*draft_card(objective, "activée")))
    else:
        kind = kind_label(objective.trigger, objective.action, objective.condition)
        view.add_item(
            discord.ui.Container(title(clip(f"{kind} · {objective.title}", 90), "annulée"))
        )
    return view


def restore_drafts(bot: discord.Client, app: App) -> None:
    for objective in app.objectives.store.recent_drafts():
        if objective.origin_message_id is not None:
            bot.add_view(DraftView(objective.id))


async def settle(interaction: discord.Interaction, objective_id: int, op: str) -> None:
    app = getattr(interaction.client, "app", None)
    if not isinstance(app, App):
        return
    objective = await asyncio.to_thread(app.objectives.store.get, objective_id)
    if objective is None or objective.owner_id != interaction.user.id:
        await interaction.response.send_message("Ce brouillon n'est pas le tien.", ephemeral=True)
        return
    try:
        saved = await asyncio.to_thread(apply, app.objectives, objective, {"op": op})
    except (StaleObjective, ValueError):
        await interaction.response.send_message("Ce brouillon est déjà traité.", ephemeral=True)
        return
    await interaction.response.edit_message(
        view=outcome(saved, op == "confirm"), allowed_mentions=NO_PINGS
    )


async def send_draft(channel: discord.abc.Messageable, app: App, objective_id: int) -> int | None:
    objective = await asyncio.to_thread(app.objectives.store.get, objective_id)
    if objective is None:
        return None
    try:
        sent = await channel.send(
            view=DraftView(objective_id, objective), allowed_mentions=NO_PINGS
        )
    except discord.HTTPException:
        return None
    return sent.id
