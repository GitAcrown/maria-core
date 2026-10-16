"""Onglet Profil de /moi : ce que MARIA sait de toi et comment elle te parle."""

import asyncio

import discord

from maria_core.app import App
from maria_core.discord.hub import Action, Hub, Picker, body, option, thin, title, wide
from maria_core.profile.service import Resolved
from maria_core.profile.slots import BY_KEY, FACTS, STYLE, Slot
from maria_core.ui.emojis import SLOT_ICONS

_PROVENANCE = {
    "user": "réglé par toi",
    "auto": "appris par MARIA, modifiable",
    "style": "déduit de tes messages",
}
_AUTO = "auto"
_BLUE = discord.ButtonStyle.primary
_RED = discord.ButtonStyle.danger


class ProfileHub(Hub):
    def __init__(self, app: App, user_id: int, name: str, host: Hub | None = None) -> None:
        super().__init__(viewer_id=user_id, host=host)
        self.app = app
        self.user_id = user_id
        self.name = name
        self.screen = "catalog"
        self.selected = ""
        self.note = ""
        self.found: dict[str, Resolved] = {}

    async def load(self) -> None:
        await asyncio.to_thread(self.app.profiles.absorb, self.user_id, force=True)
        self.found = await asyncio.to_thread(self.app.profiles.resolve, self.user_id)

    def build(self) -> None:
        slot = BY_KEY.get(self.selected)
        if self.screen == "slot" and slot is not None:
            self._slot(slot)
        else:
            self._catalog()

    def _catalog(self) -> None:
        content: list[discord.ui.Item] = [
            title(f"Profil · {self.name}", "MARIA s'en sert toute seule, tu peux tout changer"),
            wide(),
            body("### Ce qu'elle sait\n" + "\n".join(self._line(slot) for slot in FACTS)),
            thin(),
            body(
                "### Comment elle te parle\n"
                + "\n".join(self._line(slot) for slot in STYLE)
                + "\n-# Le style se déduit de la longueur et du ton de tes messages, "
                "jamais de leur contenu."
            ),
        ]
        if self.note:
            content += [thin(), body(f"-# {self.note}")]
        options = [
            option(slot.key, slot.label, self._plain(slot), SLOT_ICONS.get(slot.key, ""))
            for slot in (*FACTS, *STYLE)
        ]
        rows = [
            discord.ui.ActionRow(Picker("Modifier un champ…", options, self._open)),
            discord.ui.ActionRow(Action("Réinitialiser le style", self._reset, style=_RED)),
        ]
        self.set_layout(content, *rows)

    def _slot(self, slot: Slot) -> None:
        current = self.found.get(slot.key)
        icon = SLOT_ICONS.get(slot.key, "")
        content: list[discord.ui.Item] = [
            title(f"{icon} {slot.label}".strip(), slot.hint),
            wide(),
            body(self._value_line(slot, current)),
        ]
        if self.note:
            content += [thin(), body(f"-# {self.note}")]
        rows: list[discord.ui.ActionRow] = []
        if slot.is_choice:
            options = [option(_AUTO, "Automatique", "Selon tes messages")] if slot in STYLE else []
            options += [option(value, label) for value, label in slot.choices]
            rows.append(discord.ui.ActionRow(Picker("Choisir…", options, self._choose)))
            rows.append(discord.ui.ActionRow(Action("Retour", self._back)))
        else:
            buttons: list[discord.ui.Item] = [Action("Modifier", self._edit, style=_BLUE)]
            if current is not None:
                buttons.append(Action("Effacer", self._clear, style=_RED))
            buttons.append(Action("Retour", self._back))
            rows.append(discord.ui.ActionRow(*buttons))
        self.set_layout(content, *rows)

    def _line(self, slot: Slot) -> str:
        icon = SLOT_ICONS.get(slot.key, "")
        value = self._value_line(slot, self.found.get(slot.key))
        return f"{icon} **{slot.label}** · {value}".strip()

    @staticmethod
    def _value_line(slot: Slot, current: Resolved | None) -> str:
        if current is None:
            return "*pas défini*" if not slot.is_choice else "*par défaut*"
        shown = slot.label_of(current.value)
        return f"{shown} · *{_PROVENANCE.get(current.source, '')}*"

    def _plain(self, slot: Slot) -> str:
        current = self.found.get(slot.key)
        if current is None:
            return "pas défini" if not slot.is_choice else "par défaut"
        return slot.label_of(current.value)

    async def _open(self, interaction: discord.Interaction, value: str) -> None:
        self.selected, self.screen, self.note = value, "slot", ""
        await self.refresh(interaction)

    async def _back(self, interaction: discord.Interaction) -> None:
        self.screen, self.selected, self.note = "catalog", "", ""
        await self.refresh(interaction)

    async def _edit(self, interaction: discord.Interaction) -> None:
        slot = BY_KEY[self.selected]
        current = self.found.get(slot.key)
        await interaction.response.send_modal(
            _SetValue(self, slot, current.value if current else "")
        )

    async def save(self, interaction: discord.Interaction, slot: Slot, value: str) -> None:
        store, now = self.app.profiles.store, self.app.profiles.now()
        try:
            kept = await asyncio.to_thread(store.set, self.user_id, slot.key, value, now)
        except ValueError as exc:
            self.note = str(exc)
        else:
            self.note = f"{slot.label} : {slot.label_of(kept)}."
        await self._reload(interaction)

    async def _choose(self, interaction: discord.Interaction, value: str) -> None:
        slot = BY_KEY[self.selected]
        if value == _AUTO:
            await asyncio.to_thread(self.app.profiles.store.clear, self.user_id, slot.key)
            self.note = f"{slot.label} : automatique."
            await self._reload(interaction)
            return
        await self.save(interaction, slot, value)

    async def _clear(self, interaction: discord.Interaction) -> None:
        slot = BY_KEY[self.selected]
        await asyncio.to_thread(self.app.profiles.store.clear, self.user_id, slot.key)
        self.note = f"{slot.label} effacé."
        await self._reload(interaction)

    async def _reset(self, interaction: discord.Interaction) -> None:
        await asyncio.to_thread(self.app.profiles.reset_style, self.user_id)
        self.note = "Style remis à zéro : MARIA le redéduira de tes prochains messages."
        await self._reload(interaction)

    async def _reload(self, interaction: discord.Interaction) -> None:
        await self.load()
        await self.refresh(interaction)


class _SetValue(discord.ui.Modal):
    def __init__(self, hub: ProfileHub, slot: Slot, current: str) -> None:
        super().__init__(title=slot.label[:45])
        self.hub = hub
        self.slot = slot
        self.value = discord.ui.TextInput(
            label=slot.label, default=current[:60], max_length=60, placeholder=slot.hint[:100]
        )
        self.add_item(self.value)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        await self.hub.save(interaction, self.slot, str(self.value.value))
