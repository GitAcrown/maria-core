"""/moi : tout ce que MARIA sait de toi, en onglets comme le /carnet de CRIT.

Profil, souvenirs, ce qu'elle a appris récemment, propositions à valider. Chaque onglet est un
panneau (le menu de mémoire, le menu de profil) que ce menu dessine sous une seule rangée d'onglets.
"""

import asyncio

import discord

from maria_core.app import App
from maria_core.discord.hub import Hub, Run, Tab, tab_bar
from maria_core.discord.memory_menu import MemoryHub, memory_state
from maria_core.discord.profile_menu import ProfileHub

_PROFILE = "profile"


class MeHub(Hub):
    def __init__(self, memory: MemoryHub, profile: ProfileHub) -> None:
        super().__init__(viewer_id=memory.state.user_id)
        self.memory = memory
        self.profile = profile
        memory.host = profile.host = self
        self.tab = _PROFILE

    async def load(self) -> None:
        await asyncio.gather(self.memory.load(), self.profile.load())

    def build(self) -> None:
        if self.tab not in {key for key, _label in self._specs()}:
            self.tab = "memories"
        if self.tab == _PROFILE:
            self.profile.build()
        else:
            self.memory.tab = self.tab
            self.memory.build()

    def place(self, items: "list[discord.ui.Item]") -> None:
        tabs = [Tab(label, self._go(key), active=key == self.tab) for key, label in self._specs()]
        super().place([*tab_bar(tabs), *items])

    def _specs(self) -> list[tuple[str, str]]:
        return [(_PROFILE, "Profil"), *self.memory.tab_specs()]

    def _go(self, key: str) -> Run:
        async def run(interaction: discord.Interaction) -> None:
            self.tab = key
            if key == _PROFILE:
                self.profile.screen, self.profile.selected, self.profile.note = "catalog", "", ""
            else:
                memory = self.memory
                memory.tab, memory.page, memory.note = key, 0, ""
                memory.screen, memory.selected = "catalog", None
            await self.refresh(interaction)

        return run


async def open_me(interaction: discord.Interaction, app: App) -> None:
    state, actor = await memory_state(interaction, collective=False)
    user = interaction.user
    hub = MeHub(MemoryHub(app, state, actor), ProfileHub(app, user.id, user.name))
    await interaction.response.defer(ephemeral=True, thinking=True)
    await hub.load()
    await hub.open(interaction)
