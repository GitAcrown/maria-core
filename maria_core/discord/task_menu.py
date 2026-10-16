"""/programmes : catalogue par type (Rappel, Écoute, Surveillance…), fiche et actions."""

import asyncio

import discord

from maria_core.app import App
from maria_core.discord.hub import (
    Action,
    Hub,
    Picker,
    Run,
    Tab,
    arrows,
    body,
    clip,
    option,
    pages,
    tab_bar,
    thin,
    title,
    wide,
)
from maria_core.discord.task_edit import EditProgram
from maria_core.objectives.labels import condition_text, kind_label, status_label
from maria_core.objectives.model import Objective, ObjectiveQuota, StaleObjective
from maria_core.objectives.schedule import describe
from maria_core.objectives.tools import operate
from maria_core.ui.emojis import KIND_ICONS

PAGE = 5
_RANK = {"draft": 0, "active": 1, "paused": 2, "failed": 3}
_CONFIRM = {
    "cancel": ("Supprimer", "La tâche disparaît pour de bon."),
    "skip": ("Passer une fois", "La prochaine occurrence est sautée."),
}
_GROUPS = (
    ("all", "Tout", frozenset()),
    (
        "reminders",
        "Rappels",
        frozenset({"Rappel", "Rappel récurrent", "Tâche programmée", "Tâche"}),
    ),
    ("listening", "Écoutes", frozenset({"Écoute", "Alerte vocale", "Alerte d'arrivée"})),
    ("watching", "Veilles", frozenset({"Surveillance", "Veille de prix"})),
)
_DONE = {
    "pause": "En pause.",
    "resume": "Reprise.",
    "skip": "Occurrence passée.",
    "confirm": "Activée.",
    "cancel": "Supprimée.",
}


class TaskHub(Hub):
    def __init__(self, app: App, user_id: int) -> None:
        super().__init__(viewer_id=user_id)
        self.app = app
        self.user_id = user_id
        self.objectives: tuple[Objective, ...] = ()
        self.page = 0
        self.screen = "catalog"
        self.group = "all"
        self.selected: int | None = None
        self.pending = ""
        self.note = ""

    async def load(self) -> None:
        found = await asyncio.to_thread(self.app.objectives.store.list_for, self.user_id)
        self.objectives = tuple(
            sorted(found, key=lambda item: (_RANK.get(item.status, 4), _when(item)))
        )

    def build(self) -> None:
        current = next((item for item in self.objectives if item.id == self.selected), None)
        if self.screen == "wipe":
            self._wipe()
        elif current is None or self.screen == "catalog":
            self._catalog()
        elif self.screen == "confirm":
            self._confirm(current)
        else:
            self._detail(current)

    def _catalog(self) -> None:
        self.screen, self.selected = "catalog", None
        listed = self._listed()
        total = pages(len(listed), PAGE)
        self.page = max(0, min(self.page, total - 1))
        shown = listed[self.page * PAGE : (self.page + 1) * PAGE]
        content: list[discord.ui.Item] = [title("Tâches", self._meta(total)), wide()]
        if not shown:
            content.append(
                body(
                    "*Rien de prévu pour l'instant.*\n-# Dis-moi « rappelle-moi… », "
                    "« préviens-moi si… » ou « surveille cette page »."
                )
            )
        for index, item in enumerate(shown):
            if index:
                content.append(thin())
            content.append(body(_entry(item)))
        if self.note:
            content += [thin(), body(f"-# {self.note}")]
        rows: list[discord.ui.ActionRow] = []
        if shown:
            options = [
                option(item.id, item.title, _plain_meta(item), _icon(item)) for item in shown
            ]
            rows.append(discord.ui.ActionRow(Picker("Ouvrir une tâche…", options, self._open)))
        controls = arrows(self.page, total, self._turn)
        if self.objectives:
            controls.append(Action("Tout supprimer", self._ask_wipe, style=_RED))
        if controls:
            rows.append(discord.ui.ActionRow(*controls))
        self.set_layout(content, *rows, above=tab_bar(self._tabs()))

    def _listed(self) -> tuple[Objective, ...]:
        kinds = next(kinds for key, _label, kinds in _GROUPS if key == self.group)
        if not kinds:
            return self.objectives
        return tuple(item for item in self.objectives if _kind(item) in kinds)

    def _tabs(self) -> list[Tab]:
        """Tout, puis seulement les familles présentes, avec leur nombre."""
        tabs: list[Tab] = []
        for key, label, kinds in _GROUPS:
            count = sum(not kinds or _kind(item) in kinds for item in self.objectives)
            if count or key == "all":
                run, active = self._group(key), key == self.group
                tabs.append(Tab(f"{label} ({count})", run, active=active))
        return tabs

    def _group(self, key: str) -> Run:
        async def run(interaction: discord.Interaction) -> None:
            self.group, self.page, self.note = key, 0, ""
            await self.refresh(interaction)

        return run

    def _meta(self, total: int) -> str:
        counts = [item.status for item in self.objectives]
        bits = [f"{len(counts)} ouverte(s)"]
        if counts.count("draft"):
            bits.append(f"{counts.count('draft')} à confirmer")
        if counts.count("paused"):
            bits.append(f"{counts.count('paused')} en pause")
        if total > 1:
            bits.append(f"page {self.page + 1}/{total}")
        return " · ".join(bits)

    def _fiche(self, item: Objective) -> list[discord.ui.Item]:
        kind = _kind(item)
        content: list[discord.ui.Item] = [
            title(
                clip(f"{_icon(item)} {item.title}", 90),
                f"{kind} · {status_label(item.status, kind)}",
            ),
            wide(),
            body(objective_facts(item)),
        ]
        if item.last_error:
            content.append(body(f"-# Dernière erreur : {clip(item.last_error, 200)}"))
        return content

    def _detail(self, item: Objective) -> None:
        content = self._fiche(item)
        if self.note:
            content += [thin(), body(f"-# {self.note}")]
        self.set_layout(content, discord.ui.ActionRow(*self._buttons(item)))

    def _wipe(self) -> None:
        count = len(self.objectives)
        self.set_layout(
            [
                title("Tout supprimer ?", f"{count} programme(s)"),
                wide(),
                body(
                    f"Supprimer **tous** tes programmes ({count}) ?\n"
                    "-# Rappels, écoutes et surveillances inclus. Irréversible."
                ),
            ],
            discord.ui.ActionRow(
                Action("Oui, tout supprimer", self._confirm_wipe, style=_RED),
                Action("Annuler", self._back),
            ),
        )

    async def _ask_wipe(self, interaction: discord.Interaction) -> None:
        self.screen = "wipe"
        await self.refresh(interaction)

    async def _confirm_wipe(self, interaction: discord.Interaction) -> None:
        ids = [item.id for item in self.objectives]

        def wipe() -> int:
            done = 0
            for objective_id in ids:
                try:
                    operate(self.app.objectives, self.user_id, objective_id, "cancel")
                    done += 1
                except (ValueError, StaleObjective):
                    continue
            return done

        removed = await asyncio.to_thread(wipe)
        await self.load()
        self.screen, self.note = "catalog", f"{removed} programme(s) supprimé(s)."
        await self.refresh(interaction)

    def _buttons(self, item: Objective) -> list[discord.ui.Item]:
        buttons: list[discord.ui.Item] = []
        if item.status == "draft":
            buttons.append(Action("Confirmer", self._run("confirm"), style=_GREEN))
        elif item.status == "paused":
            buttons.append(Action("Reprendre", self._run("resume"), style=_BLUE))
            buttons.append(Action("Modifier", self._edit))
        else:
            buttons.append(Action("Modifier", self._edit, style=_BLUE))
            buttons.append(Action("Pause", self._run("pause")))
            if item.next_run_at is not None and item.trigger.get("type") != "at":
                buttons.append(Action("Passer une fois", self._ask("skip")))
        buttons.append(Action("Supprimer", self._ask("cancel"), style=_RED))
        buttons.append(Action("← Retour", self._back))
        return buttons

    def _confirm(self, item: Objective) -> None:
        """La fiche reste visible ; la question et ses deux boutons remplacent les actions."""
        label, text = _CONFIRM[self.pending]
        content = self._fiche(item)
        content += [thin(), body(f"**{label} ?**" + chr(10) + f"-# {text}")]
        danger = self.pending == "cancel"
        self.set_layout(
            content,
            discord.ui.ActionRow(
                Action(label, self._run(self.pending), style=_RED if danger else _BLUE),
                Action("Annuler", self._detail_again),
            ),
        )

    def _turn(self, delta: int) -> Run:
        async def run(interaction: discord.Interaction) -> None:
            self.page += delta
            self.note = ""
            await self.refresh(interaction)

        return run

    def _ask(self, op: str) -> Run:
        async def run(interaction: discord.Interaction) -> None:
            self.screen, self.pending = "confirm", op
            await self.refresh(interaction)

        return run

    def _run(self, op: str) -> Run:
        async def run(interaction: discord.Interaction) -> None:
            await self.apply(interaction, op)

        return run

    async def apply(self, interaction: discord.Interaction, op: str) -> None:
        objective_id = self.selected or 0
        try:
            await asyncio.to_thread(operate, self.app.objectives, self.user_id, objective_id, op)
        except (ValueError, StaleObjective, ObjectiveQuota) as exc:
            self.screen, self.note = "detail", str(exc)
            await self.refresh(interaction)
            return
        await self.load()
        self.note = _DONE.get(op, "C'est fait.")
        self.screen = "catalog" if op == "cancel" else "detail"
        await self.refresh(interaction)

    async def _edit(self, interaction: discord.Interaction) -> None:
        item = next((entry for entry in self.objectives if entry.id == self.selected), None)
        if item is not None:
            await interaction.response.send_modal(EditProgram(self.app, item, self._edited))

    async def _edited(self, interaction: discord.Interaction, note: str) -> None:
        await self.load()
        self.screen, self.note = "detail", note
        await self.refresh(interaction)

    async def _open(self, interaction: discord.Interaction, value: str) -> None:
        self.selected, self.screen, self.note = int(value), "detail", ""
        await self.refresh(interaction)

    async def _detail_again(self, interaction: discord.Interaction) -> None:
        self.screen, self.pending = "detail", ""
        await self.refresh(interaction)

    async def _back(self, interaction: discord.Interaction) -> None:
        self.screen, self.note = "catalog", ""
        await self.refresh(interaction)


_GREEN = discord.ButtonStyle.success
_BLUE = discord.ButtonStyle.primary
_RED = discord.ButtonStyle.danger


def _kind(item: Objective) -> str:
    return kind_label(item.trigger, item.action, item.condition)


def _name(item: Objective) -> str:
    return clip(f"{_kind(item)} · {item.title}", 100)


def _icon(item: Objective) -> str:
    return KIND_ICONS.get(_kind(item), "🗓️")


def _when(item: Objective) -> float:
    return item.next_run_at.timestamp() if item.next_run_at else float("inf")


def _entry(item: Objective) -> str:
    """Titre `###`, une ligne de contenu si elle apporte quelque chose, puis la méta."""
    lines = [f"### {_icon(item)} {clip(item.title, 90)}"]
    detail = condition_text(item.condition) or str(item.action.get("text") or "")
    if detail and detail.casefold() != item.title.casefold():
        lines.append(clip(detail, 160))
    lines.append(f"-# {_meta(item)}")
    return "\n".join(lines)


def _meta(item: Objective) -> str:
    bits = [_kind(item), status_label(item.status, _kind(item)), describe(item.trigger)]
    if item.next_run_at is not None and item.status == "active":
        bits.append(f"<t:{int(item.next_run_at.timestamp())}:R>")
    if item.max_fires and item.max_fires > 1:
        bits.append(f"{item.fires}/{item.max_fires}")
    if item.deliver == "dm":
        bits.append("MP")
    return " · ".join(bits)


def _plain_meta(item: Objective) -> str:
    return f"{_kind(item)} · {status_label(item.status, _kind(item))} · {describe(item.trigger)}"


def objective_facts(item: Objective) -> str:
    lines = [f"**Quand** · {describe(item.trigger)}"]
    condition = condition_text(item.condition)
    if condition:
        lines.append(f"**Si** · {condition}")
    text = str(item.action.get("text") or "")
    if text:
        lines.append(f"**Message** · {clip(text, 600)}")
    source = str(item.action.get("url") or item.action.get("query") or "")
    if source:
        lines.append(f"**Source** · {clip(source, 120)}")
    if item.next_run_at is not None and item.status == "active":
        stamp = int(item.next_run_at.timestamp())
        lines.append(f"**Prochaine fois** · <t:{stamp}:F> · <t:{stamp}:R>")
    foot = [f"#{item.id}", "en MP" if item.deliver == "dm" else "dans le salon"]
    if item.max_fires:
        foot.append(f"{item.fires}/{item.max_fires} alerte(s)")
    if item.expires_at is not None:
        foot.append(f"expire <t:{int(item.expires_at.timestamp())}:R>")
    lines.append("-# " + " · ".join(foot))
    return "\n".join(lines)


async def open_tasks(interaction: discord.Interaction, app: App) -> None:
    hub = TaskHub(app, interaction.user.id)
    await hub.load()
    await hub.open(interaction)
