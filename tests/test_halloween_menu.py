"""/halloween : onglets Sac et Classement, sans sonnerie ; la ligne de l'événement en bas."""

import discord

from maria_core.app import App
from maria_core.discord.halloween_menu import HalloweenCog, HalloweenHub
from maria_core.plugins.halloween import Player, Reward
from maria_core.plugins.halloween_sweets import SWEETS


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


async def test_a_respected_dare_puts_a_candy_reaction_with_a_unicode_fallback(app: App) -> None:
    calls: list[tuple[int, int, str]] = []

    async def reactor(channel_id: int, message_id: int, emoji: str) -> bool:
        calls.append((channel_id, message_id, emoji))
        return not emoji.startswith("<:")  # l'emoji custom est refusé, le Unicode passe

    app.social.reactor = reactor
    cog = HalloweenCog(None, app)  # type: ignore[arg-type]
    emoji = SWEETS[1].emoji
    await cog._reward(Reward(5, 77, 103, 7, emoji))
    assert calls == [(77, 103, emoji), (77, 103, SWEETS[1].fallback)]
