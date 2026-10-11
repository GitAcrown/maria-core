"""Menu d'onglets persistant, restauré au démarrage."""

import asyncio

import discord
from discord.ext import commands

from maria_core.ui.tabs import SavedTabs, TabStore


class TabView(discord.ui.View):
    def __init__(self, store: TabStore, saved: SavedTabs) -> None:
        super().__init__(timeout=None)
        self.store = store
        self.tab_id = saved.id
        select = discord.ui.Select(
            custom_id=f"maria:tab:{saved.id}",
            placeholder="Choisir un onglet",
            options=_options(saved),
        )
        select.callback = self._chosen
        self.add_item(select)

    async def _chosen(self, interaction: discord.Interaction) -> None:
        saved = await asyncio.to_thread(self.store.get, self.tab_id)
        choice = _selected(self)
        if saved is None or choice is None or choice >= len(saved.tabs):
            await interaction.response.send_message("Onglet introuvable.", ephemeral=True)
            return
        await interaction.response.edit_message(content=saved.tabs[choice][1][:2000], view=self)


def restore_tabs(bot: commands.Bot, store: TabStore) -> None:
    for saved in store.recent():
        if saved.message_id is None or not saved.tabs:
            continue
        bot.add_view(TabView(store, saved), message_id=saved.message_id)


def _options(saved: SavedTabs) -> list[discord.SelectOption]:
    options = [
        discord.SelectOption(label=(label.strip()[:100] or f"Onglet {index + 1}"), value=str(index))
        for index, (label, _body) in enumerate(saved.tabs[:25])
    ]
    return options or [discord.SelectOption(label="Vide", value="0")]


def _selected(view: discord.ui.View) -> int | None:
    for child in view.children:
        if isinstance(child, discord.ui.Select) and child.values:
            try:
                return int(child.values[0])
            except ValueError:
                return None
    return None
