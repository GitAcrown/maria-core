"""Menus de /moi, /global et /taches. Éphémères : ils vivent le temps du message."""

import asyncio

import discord

from maria_core.app import App
from maria_core.memory.model import Memory, Proposal
from maria_core.memory.policy import Actor
from maria_core.memory.store import MemoryDenied
from maria_core.objectives.model import Objective, ObjectiveQuota, StaleObjective
from maria_core.objectives.schedule import describe
from maria_core.objectives.tools import operate

_PAGE = 25


class MemoryView(discord.ui.View):
    def __init__(
        self,
        *,
        user_id: int,
        guild_id: int | None,
        collective: bool,
        memories: tuple[Memory, ...],
        proposals: tuple[Proposal, ...],
        note: str = "",
    ) -> None:
        super().__init__(timeout=180)
        self.user_id = user_id
        self.guild_id = guild_id
        self.collective = collective
        self.note = note
        self.memory_id: int | None = None
        self.proposal_id: int | None = None
        if memories:
            self.add_item(_MemorySelect(memories[:_PAGE]))
        if proposals and not collective:
            self.add_item(_ProposalSelect(proposals[:_PAGE]))

    def catalog(
        self,
        memories: tuple[Memory, ...],
        proposals: tuple[Proposal, ...],
    ) -> str:
        lines = [_heading(self.collective)]
        if memories:
            lines.extend(f"- #{item.id} {item.content}" for item in memories[:_PAGE])
        else:
            lines.append("Aucun souvenir.")
        if proposals and not self.collective:
            lines.append("Propositions :")
            lines.extend(f"- #{item.id} {item.content}" for item in proposals[:_PAGE])
        if self.note:
            lines.append(self.note)
        return "\n".join(lines)[:2000]

    @discord.ui.button(label="Oublier", style=discord.ButtonStyle.danger)
    async def forget(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if self.memory_id is None:
            await interaction.response.send_message("Choisis un souvenir.", ephemeral=True)
            return
        app = _app(interaction)
        try:
            await asyncio.to_thread(
                app.memory.store.forget,
                await _actor(interaction),
                self.memory_id,
                app.memory.now(),
            )
        except MemoryDenied as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await _refresh_memory(interaction, self, "Souvenir effacé.")

    @discord.ui.button(label="Retenir", style=discord.ButtonStyle.primary)
    async def keep(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await _proposal(interaction, self, accept=True)

    @discord.ui.button(label="Ignorer")
    async def dismiss(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await _proposal(interaction, self, accept=False)

    @discord.ui.button(label="Ajouter")
    async def add(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if self.collective:
            await interaction.response.send_message(
                "Un souvenir du serveur se propose dans la conversation.",
                ephemeral=True,
            )
            return
        await interaction.response.send_modal(_Remember(self))


class TaskView(discord.ui.View):
    def __init__(self, *, user_id: int, objectives: tuple[Objective, ...], note: str = "") -> None:
        super().__init__(timeout=180)
        self.user_id = user_id
        self.note = note
        self.objective_id: int | None = None
        if objectives:
            self.add_item(_TaskSelect(objectives[:_PAGE]))

    def catalog(self, objectives: tuple[Objective, ...]) -> str:
        lines = ["Tes objectifs :"]
        if objectives:
            lines.extend(
                f"- #{item.id} {item.title} — {item.status} — {describe(item.trigger)}"
                for item in objectives[:_PAGE]
            )
        else:
            lines.append("Aucun objectif ouvert.")
        if self.note:
            lines.append(self.note)
        return "\n".join(lines)[:2000]

    @discord.ui.button(label="Pause")
    async def pause(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await _task(interaction, self, "pause", "Objectif en pause.")

    @discord.ui.button(label="Reprendre", style=discord.ButtonStyle.primary)
    async def resume(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await _task(interaction, self, "resume", "Objectif repris.")

    @discord.ui.button(label="Passer")
    async def skip(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await _task(interaction, self, "skip", "Occurrence passée.")

    @discord.ui.button(label="Supprimer", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await _task(interaction, self, "cancel", "Objectif supprimé.")


class _Remember(discord.ui.Modal, title="À retenir sur moi"):
    fact = discord.ui.TextInput(label="Le fait", style=discord.TextStyle.paragraph, max_length=500)

    def __init__(self, view: MemoryView) -> None:
        super().__init__()
        self.view = view

    async def on_submit(self, interaction: discord.Interaction) -> None:
        app = _app(interaction)
        text = str(self.fact.value).strip()
        if not text:
            await interaction.response.send_message("Souvenir vide.", ephemeral=True)
            return
        try:
            await asyncio.to_thread(
                app.memory.store.remember,
                await _actor(interaction),
                scope="user",
                subject_id=interaction.user.id,
                guild_id=self.view.guild_id,
                content=text,
                source="explicit",
                now=app.memory.now(),
            )
        except MemoryDenied as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await _refresh_memory(interaction, self.view, "C'est noté.")


class _MemorySelect(discord.ui.Select):
    def __init__(self, memories: tuple[Memory, ...]) -> None:
        super().__init__(
            placeholder="Choisir un souvenir",
            options=[_option(item.id, item.content) for item in memories],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if isinstance(view, MemoryView):
            view.memory_id = int(self.values[0])
        await interaction.response.defer()


class _ProposalSelect(discord.ui.Select):
    def __init__(self, proposals: tuple[Proposal, ...]) -> None:
        super().__init__(
            placeholder="Choisir une proposition",
            options=[_option(item.id, item.content) for item in proposals],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if isinstance(view, MemoryView):
            view.proposal_id = int(self.values[0])
        await interaction.response.defer()


class _TaskSelect(discord.ui.Select):
    def __init__(self, objectives: tuple[Objective, ...]) -> None:
        super().__init__(
            placeholder="Choisir un objectif",
            options=[_option(item.id, f"{item.title} · {item.status}") for item in objectives],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if isinstance(view, TaskView):
            view.objective_id = int(self.values[0])
        await interaction.response.defer()


def _option(row_id: int, text: str) -> discord.SelectOption:
    label = " ".join(text.split())[:100] or f"#{row_id}"
    return discord.SelectOption(label=label, value=str(row_id))


def _heading(collective: bool) -> str:
    return "Souvenirs du serveur :" if collective else "Tes souvenirs :"


async def send_memory(interaction: discord.Interaction, *, collective: bool) -> None:
    app = _app(interaction)
    guild_id = interaction.guild.id if interaction.guild is not None else None
    view = MemoryView(
        user_id=interaction.user.id,
        guild_id=guild_id,
        collective=collective,
        memories=(),
        proposals=(),
    )
    memories, proposals = await _memory_rows(app, view)
    view = MemoryView(
        user_id=interaction.user.id,
        guild_id=guild_id,
        collective=collective,
        memories=memories,
        proposals=proposals,
    )
    await interaction.response.send_message(
        view.catalog(memories, proposals),
        view=view,
        ephemeral=True,
    )


async def send_tasks(interaction: discord.Interaction) -> None:
    app = _app(interaction)
    found = await asyncio.to_thread(app.objectives.store.list_for, interaction.user.id)
    view = TaskView(user_id=interaction.user.id, objectives=found)
    await interaction.response.send_message(view.catalog(found), view=view, ephemeral=True)


def _app(interaction: discord.Interaction) -> App:
    app = getattr(interaction.client, "app", None)
    if not isinstance(app, App):
        raise RuntimeError("Le bot n'est pas relié à une application.")
    return app


async def _actor(interaction: discord.Interaction) -> Actor:
    user = interaction.user
    permissions = getattr(user, "guild_permissions", None)
    return Actor(
        user.id,
        await interaction.client.is_owner(user),
        bool(permissions and permissions.manage_messages),
    )


async def _proposal(interaction: discord.Interaction, view: MemoryView, *, accept: bool) -> None:
    if view.proposal_id is None:
        await interaction.response.send_message("Choisis une proposition.", ephemeral=True)
        return
    app = _app(interaction)
    actor = await _actor(interaction)
    try:
        if accept:
            await asyncio.to_thread(
                app.memory.store.accept, view.proposal_id, actor, app.memory.now()
            )
            note = "Proposition retenue."
        else:
            await asyncio.to_thread(
                app.memory.store.ignore, view.proposal_id, actor, app.memory.now()
            )
            note = "Proposition ignorée."
    except (MemoryDenied, ValueError) as exc:
        await interaction.response.send_message(str(exc), ephemeral=True)
        return
    await _refresh_memory(interaction, view, note)


async def _task(interaction: discord.Interaction, view: TaskView, op: str, note: str) -> None:
    if view.objective_id is None:
        await interaction.response.send_message("Choisis un objectif.", ephemeral=True)
        return
    app = _app(interaction)
    try:
        await asyncio.to_thread(operate, app.objectives, view.user_id, view.objective_id, op)
    except (ValueError, StaleObjective, ObjectiveQuota) as exc:
        await interaction.response.send_message(str(exc), ephemeral=True)
        return
    await _refresh_tasks(interaction, view, note)


async def _refresh_memory(interaction: discord.Interaction, view: MemoryView, note: str) -> None:
    app = _app(interaction)
    memories, proposals = await _memory_rows(app, view)
    fresh = MemoryView(
        user_id=view.user_id,
        guild_id=view.guild_id,
        collective=view.collective,
        memories=memories,
        proposals=proposals,
        note=note,
    )
    await interaction.response.edit_message(content=fresh.catalog(memories, proposals), view=fresh)


async def _refresh_tasks(interaction: discord.Interaction, view: TaskView, note: str) -> None:
    app = _app(interaction)
    found = await asyncio.to_thread(app.objectives.store.list_for, view.user_id)
    fresh = TaskView(user_id=view.user_id, objectives=found, note=note)
    await interaction.response.edit_message(content=fresh.catalog(found), view=fresh)


async def _memory_rows(
    app: App, view: MemoryView
) -> tuple[tuple[Memory, ...], tuple[Proposal, ...]]:
    if view.collective:
        if view.guild_id is None:
            return (), ()
        memories = await asyncio.to_thread(app.memory.store.list_guild, view.guild_id)
        return memories, ()
    memories = await asyncio.to_thread(app.memory.store.list_for, view.user_id)
    proposals = await asyncio.to_thread(app.memory.store.open_for, view.user_id)
    return memories, proposals
