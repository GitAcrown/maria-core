"""/halloween : onglets Porte, Sac, Classement, et bouton Sonner grisé quand la porte est fermée."""

import discord

from maria_core.app import App
from maria_core.discord.halloween_menu import HalloweenHub
from maria_core.plugins.halloween import RINGS_PER_DAY, Player, in_season, play


def _buttons(view: discord.ui.LayoutView) -> list[discord.ui.Button]:
    return [item for item in view.walk_children() if isinstance(item, discord.ui.Button)]


async def test_the_menu_has_three_tabs_and_a_ring_button(app: App) -> None:
    app.plugins.load("maria_core.plugins.halloween")
    hub = HalloweenHub(app, Player(5, 7, "Léa"))
    await hub.load()
    hub.build()
    first = hub.children[0]
    assert isinstance(first, discord.ui.ActionRow)
    tabs = [item for item in first.children if isinstance(item, discord.ui.Button)]
    assert [tab.label for tab in tabs] == ["Porte", "Sac", "Classement"]
    assert tabs[0].style == discord.ButtonStyle.primary
    ring = next(button for button in _buttons(hub) if button.label == "Sonner")
    assert not ring.disabled
    hub.screen = "bag"
    hub.page = await play(app.database, hub.who, "bag")
    hub.build()
    assert all(button.label != "Sonner" for button in _buttons(hub))


async def test_the_ring_button_is_disabled_once_the_door_is_closed(app: App) -> None:
    app.plugins.load("maria_core.plugins.halloween")
    who = Player(5, 7, "Léa")
    if not in_season():
        return  # le tirage sans horloge injectée n'a de sens que pendant l'événement
    for _ in range(RINGS_PER_DAY):
        await play(app.database, who, "ring")
    hub = HalloweenHub(app, who)
    await hub.load()
    hub.build()
    ring = next(button for button in _buttons(hub) if button.label == "Sonner")
    assert ring.disabled
