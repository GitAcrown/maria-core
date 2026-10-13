"""/moi et /global : résumé, catalogue paginé, fiche d'un souvenir. Comme dans MARIA_R."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass

import discord

from maria_core.app import App
from maria_core.discord.hub import (
    Action,
    Hub,
    Picker,
    Run,
    body,
    clip,
    option,
    pages,
    thin,
    title,
    wide,
)
from maria_core.memory.model import Memory, Proposal
from maria_core.memory.policy import Actor
from maria_core.memory.store import MemoryDenied

PAGE = 15
_SOURCES = {"explicit": "dit explicitement", "proposal": "proposition acceptée"}


@dataclass(slots=True)
class MemoryState:
    user_id: int
    guild_id: int | None
    collective: bool
    can_manage: bool
    name: str
    summary: str = ""
    memories: tuple[Memory, ...] = ()
    proposals: tuple[Proposal, ...] = ()


class MemoryHub(Hub):
    def __init__(self, app: App, state: MemoryState, actor: Actor) -> None:
        super().__init__(viewer_id=state.user_id)
        self.app = app
        self.state = state
        self.actor = actor
        self.tab = "memories"
        self.page = 0
        self.screen = "catalog"
        self.selected: int | None = None
        self.note = ""

    async def load(self) -> None:
        state = self.state
        if state.collective:
            guild = state.guild_id or 0
            state.memories = await asyncio.to_thread(self.app.memory.store.list_guild, guild)
            state.proposals = (
                await asyncio.to_thread(self.app.memory.store.open_guild, guild)
                if state.can_manage
                else ()
            )
        else:
            state.memories = await asyncio.to_thread(self.app.memory.store.list_for, state.user_id)
            state.proposals = await asyncio.to_thread(self.app.memory.store.open_for, state.user_id)
        state.summary = await self.app.memory_summaries.summarize(
            state.memories, collective=state.collective, name=state.name
        )

    def build(self) -> None:
        if self.screen == "memory":
            self._memory()
        elif self.screen == "proposal":
            self._proposal()
        else:
            self._catalog()

    def _catalog(self) -> None:
        state = self.state
        waiting = len(state.proposals)
        meta = f"{len(state.memories)} souvenir(s)" + (f" · {waiting} à valider" if waiting else "")
        items = state.memories if self.tab == "memories" else state.proposals
        total = pages(len(items), PAGE)
        self.page = max(0, min(self.page, total - 1))
        shown = items[self.page * PAGE : (self.page + 1) * PAGE]
        content: list[discord.ui.Item] = [title(self._heading(), meta), wide()]
        if self.tab == "memories":
            content += [body(state.summary), thin()]
        lines = [f"\u203a {clip(item.content, 150)}" for item in shown]
        empty = "-# Aucun souvenir." if self.tab == "memories" else "-# Rien à valider."
        content.append(body("\n".join(lines) if lines else empty))
        if total > 1:
            content.append(body(f"-# Page {self.page + 1}/{total}"))
        if self.note:
            content.append(body(f"-# {self.note}"))
        self.set_layout(content, *self._catalog_rows(shown, total))

    def _catalog_rows(
        self, shown: tuple[Memory, ...] | tuple[Proposal, ...], total: int
    ) -> list[discord.ui.ActionRow]:
        rows: list[discord.ui.ActionRow] = []
        if self.state.proposals:
            rows.append(
                discord.ui.ActionRow(
                    self._tab("memories", "Souvenirs"),
                    self._tab("proposals", f"À valider ({len(self.state.proposals)})"),
                )
            )
        if shown:
            options = [option(item.id, item.content) for item in shown]
            rows.append(discord.ui.ActionRow(Picker("Ouvrir…", options, self._open)))
        controls: list[discord.ui.Item] = []
        if not self.state.collective:
            controls.append(Action("Ajouter", self._add, style=discord.ButtonStyle.primary))
        if total > 1:
            controls += [
                Action("←", self._turn(-1), disabled=self.page == 0),
                Action("→", self._turn(1), disabled=self.page >= total - 1),
            ]
        if controls:
            rows.append(discord.ui.ActionRow(*controls))
        return rows

    def _memory(self) -> None:
        memory = next((item for item in self.state.memories if item.id == self.selected), None)
        if memory is None:
            self._back_to_catalog()
            return
        meta = " · ".join(
            part
            for part in (
                "serveur" if memory.scope == "guild" else "perso",
                f"retenu le {memory.created_at:%d/%m/%Y}",
                _SOURCES.get(memory.source, ""),
            )
            if part
        )
        content: list[discord.ui.Item] = [title("Souvenir", meta), wide(), body(memory.content)]
        if self.note:
            content += [thin(), body(f"-# {self.note}")]
        buttons: list[discord.ui.Item] = []
        if self._may_edit():
            buttons += [
                Action("Modifier", self._edit, style=discord.ButtonStyle.primary),
                Action("Oublier", self._forget, style=discord.ButtonStyle.danger),
                Action("Annuler la modif", self._undo),
            ]
        buttons.append(Action("Retour", self._back))
        self.set_layout(content, discord.ui.ActionRow(*buttons))

    def _proposal(self) -> None:
        proposal = next((item for item in self.state.proposals if item.id == self.selected), None)
        if proposal is None:
            self._back_to_catalog()
            return
        meta = "à revoir" if proposal.review_of else f"proposé le {proposal.created_at:%d/%m/%Y}"
        content: list[discord.ui.Item] = [
            title("Proposition", meta),
            wide(),
            body(proposal.content),
        ]
        if self.note:
            content += [thin(), body(f"-# {self.note}")]
        self.set_layout(
            content,
            discord.ui.ActionRow(
                Action("Retenir", self._accept, style=discord.ButtonStyle.success),
                Action("Ignorer", self._ignore, style=discord.ButtonStyle.danger),
                Action("Retour", self._back),
            ),
        )

    def _heading(self) -> str:
        return f"Mémoire · {self.state.name}"

    def _may_edit(self) -> bool:
        return not self.state.collective or self.state.can_manage

    def _tab(self, tab: str, label: str) -> Action:
        style = discord.ButtonStyle.primary if self.tab == tab else discord.ButtonStyle.secondary

        async def run(interaction: discord.Interaction) -> None:
            self.tab, self.page, self.note = tab, 0, ""
            await self.refresh(interaction)

        return Action(label, run, style=style)

    def _turn(self, delta: int) -> Run:
        async def run(interaction: discord.Interaction) -> None:
            self.page += delta
            await self.refresh(interaction)

        return run

    def _back_to_catalog(self) -> None:
        self.screen, self.selected = "catalog", None
        self._catalog()

    async def _open(self, interaction: discord.Interaction, value: str) -> None:
        self.selected = int(value)
        self.screen = "memory" if self.tab == "memories" else "proposal"
        self.note = ""
        await self.refresh(interaction)

    async def _back(self, interaction: discord.Interaction) -> None:
        self.screen, self.selected, self.note = "catalog", None, ""
        await self.refresh(interaction)

    async def _add(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(_Remember(self))

    async def _edit(self, interaction: discord.Interaction) -> None:
        memory = next((item for item in self.state.memories if item.id == self.selected), None)
        if memory is not None:
            await interaction.response.send_modal(_Correct(self, memory))

    async def _forget(self, interaction: discord.Interaction) -> None:
        store, now = self.app.memory.store, self.app.memory.now()
        await self.act(interaction, lambda: store.forget(self.actor, self.selected, now), "Oublié.")

    async def _undo(self, interaction: discord.Interaction) -> None:
        store, now = self.app.memory.store, self.app.memory.now()
        await self.act(
            interaction, lambda: store.undo(self.actor, self.selected, now), "Modification annulée."
        )

    async def _accept(self, interaction: discord.Interaction) -> None:
        store, now = self.app.memory.store, self.app.memory.now()
        await self.act(interaction, lambda: store.accept(self.selected, self.actor, now), "Retenu.")

    async def _ignore(self, interaction: discord.Interaction) -> None:
        store, now = self.app.memory.store, self.app.memory.now()
        await self.act(interaction, lambda: store.ignore(self.selected, self.actor, now), "Ignoré.")

    async def act(
        self, interaction: discord.Interaction, change: Callable[[], object], note: str
    ) -> None:
        """Applique un changement, recharge (le résumé peut prendre un instant)."""
        await interaction.response.defer()
        try:
            await asyncio.to_thread(change)
        except (MemoryDenied, ValueError) as exc:
            self.note = str(exc)
            await self.refresh(interaction)
            return
        await self.load()
        self.screen, self.selected, self.note = "catalog", None, note
        await self.refresh(interaction)


class _Remember(discord.ui.Modal, title="À retenir sur moi"):
    fact = discord.ui.TextInput(label="Le fait", style=discord.TextStyle.paragraph, max_length=500)

    def __init__(self, hub: MemoryHub) -> None:
        super().__init__()
        self.hub = hub

    async def on_submit(self, interaction: discord.Interaction) -> None:
        hub = self.hub
        text = str(self.fact.value).strip()
        store, now = hub.app.memory.store, hub.app.memory.now()
        state = hub.state

        def change() -> None:
            store.remember(
                hub.actor,
                scope="user",
                subject_id=state.user_id,
                guild_id=state.guild_id,
                content=text,
                source="explicit",
                now=now,
            )

        await hub.act(interaction, change, "C'est noté.")


class _Correct(discord.ui.Modal, title="Modifier le souvenir"):
    def __init__(self, hub: MemoryHub, memory: Memory) -> None:
        super().__init__()
        self.hub = hub
        self.memory_id = memory.id
        self.fact = discord.ui.TextInput(
            label="Souvenir",
            style=discord.TextStyle.paragraph,
            default=memory.content[:500],
            max_length=500,
        )
        self.add_item(self.fact)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        hub = self.hub
        text = str(self.fact.value).strip()
        store, now = hub.app.memory.store, hub.app.memory.now()
        await hub.act(
            interaction, lambda: store.correct(hub.actor, self.memory_id, text, now), "Modifié."
        )


async def open_memory(interaction: discord.Interaction, app: App, *, collective: bool) -> None:
    user = interaction.user
    permissions = getattr(user, "guild_permissions", None)
    actor = Actor(
        user.id,
        await interaction.client.is_owner(user),
        bool(permissions and permissions.manage_messages),
    )
    guild = interaction.guild
    name = guild.name if collective and guild is not None else user.display_name
    state = MemoryState(
        user_id=user.id,
        guild_id=guild.id if guild is not None else None,
        collective=collective,
        can_manage=actor.is_owner or actor.is_moderator,
        name=name,
    )
    hub = MemoryHub(app, state, actor)
    await interaction.response.defer(ephemeral=True, thinking=True)
    await hub.load()
    await hub.open(interaction)
