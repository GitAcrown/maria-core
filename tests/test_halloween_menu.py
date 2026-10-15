"""/halloween : onglets Sac et Classement, sans sonnerie ; la ligne de l'événement en bas."""

import discord

from maria_core.app import App
from maria_core.discord.halloween_menu import HalloweenHub
from maria_core.plugins.halloween import Player


def _buttons(view: discord.ui.LayoutView) -> list[discord.ui.Button]:
    return [item for item in view.walk_children() if isinstance(item, discord.ui.Button)]


def _texts(view: discord.ui.LayoutView) -> list[str]:
    return [
        item.content for item in view.walk_children() if isinstance(item, discord.ui.TextDisplay)
    ]


async def test_the_menu_has_only_bag_and_ranking_and_no_way_to_ring(app: App) -> None:
    app.plugins.load("maria_core.plugins.halloween")
    hub = HalloweenHub(app, Player(5, 7, "Léa"))
    await hub.load()
    hub.build()
    first = hub.children[0]
    assert isinstance(first, discord.ui.ActionRow)
    tabs = [item for item in first.children if isinstance(item, discord.ui.Button)]
    assert [tab.label for tab in tabs] == ["Sac", "Classement"]
    assert tabs[0].style == discord.ButtonStyle.primary
    assert [button.label for button in _buttons(hub)] == ["Sac", "Classement"]


async def test_the_event_line_closes_the_card_after_a_separator(app: App) -> None:
    app.plugins.load("maria_core.plugins.halloween")
    hub = HalloweenHub(app, Player(5, 7, "Léa"))
    await hub.load()
    hub.build()
    container = hub.children[1]
    assert isinstance(container, discord.ui.Container)
    last, before = container.children[-1], container.children[-2]
    assert isinstance(last, discord.ui.TextDisplay)
    assert last.content == "-# Halloween · jusqu'au 1er novembre"
    assert isinstance(before, discord.ui.Separator)
    assert "Halloween" not in "".join(_texts(hub)[:-1])
    hub.screen = "ranking"
    await hub.load()
    hub.build()
    assert hub.page["action"] == "ranking"
