"""Bonbons ou sort : l'outil n'existe que pendant l'événement, et le tirage est celui du code."""

import random
from datetime import datetime
from zoneinfo import ZoneInfo

from maria_core.app import App
from maria_core.capabilities import Context
from maria_core.capabilities.runner import available
from maria_core.config import DEFAULT_PLUGINS, Settings
from maria_core.plugins import halloween
from maria_core.plugins.halloween import (
    RINGS_PER_DAY,
    halloween_capability,
    in_season,
    render_halloween,
)
from maria_core.ui.emojis import FALLBACKS

_PARIS = ZoneInfo("Europe/Paris")


def _at(day: str, hour: int = 12) -> datetime:
    return datetime.fromisoformat(f"{day}T{hour:02d}:00:00").replace(tzinfo=_PARIS)


def _context(user: int = 7, name: str = "Léa") -> Context:
    return Context(
        user_id=user,
        guild_id=5,
        channel_id=3,
        message_id=1,
        is_owner=False,
        is_moderator=False,
        text="bonbons ou sort",
        author_name=name,
    )


def test_the_tool_exists_from_today_to_november_first_included() -> None:
    assert not in_season(lambda: _at("2026-10-14", 23))
    assert in_season(lambda: _at("2026-10-15", 0))
    assert in_season(lambda: _at("2026-11-01", 23))
    assert not in_season(lambda: _at("2026-11-02", 0))


def test_the_model_only_sees_the_tool_during_the_event(app: App) -> None:
    now = [_at("2026-10-20")]
    capability = halloween_capability(app.database, clock=lambda: now[0])
    app.capabilities.register(capability)
    settings = Settings.for_tests(app.settings.data_dir)
    assert "trick_or_treat" in [item.name for item in available(app.capabilities, settings)]
    now[0] = _at("2026-11-02")
    assert "trick_or_treat" not in [item.name for item in available(app.capabilities, settings)]


async def test_a_ring_gives_candies_or_a_trick_and_is_limited_per_day(app: App) -> None:
    app.database.execute(halloween._TABLE)
    now = [_at("2026-10-31")]
    tool = halloween_capability(app.database, clock=lambda: now[0], rng=random.Random(4))
    outcomes = []
    for _ in range(RINGS_PER_DAY):
        result = await tool.run(_context(), {"action": "ring"})
        assert result.ok and result.widget == "trick_or_treat"
        outcomes.append(result.data["outcome"])
    assert set(outcomes) <= {"treat", "trick"}
    closed = await tool.run(_context(), {"action": "ring"})
    assert closed.data["outcome"] == "closed" and closed.data["rings_left"] == 0
    other = await tool.run(_context(user=8, name="Paul"), {"action": "ring"})
    assert other.data["outcome"] != "closed"
    now[0] = _at("2026-11-01")
    again = await tool.run(_context(), {"action": "ring"})
    assert again.data["outcome"] != "closed" and again.data["rings_left"] == RINGS_PER_DAY - 1


async def test_the_bag_adds_up_theft_never_goes_below_zero_and_the_ranking_orders(app: App) -> None:
    app.database.execute(halloween._TABLE)
    tool = halloween_capability(app.database, clock=lambda: _at("2026-10-25"))
    always_trick = random.Random()
    always_trick.random = lambda: 0.0  # type: ignore[method-assign]
    always_trick.choice = lambda _items: ("Une sorcière te chipe deux bonbons !", 2)  # type: ignore[method-assign]
    broke = halloween_capability(app.database, clock=lambda: _at("2026-10-25"), rng=always_trick)
    result = await broke.run(_context(), {"action": "ring"})
    assert result.data["outcome"] == "trick" and result.data["stolen"] == 0
    assert result.data["candies"] == 0

    app.database.execute(
        "INSERT INTO halloween_bag (guild_id, user_id, name, candies) VALUES (5, 9, 'Zoé', 12)"
    )
    app.database.execute("UPDATE halloween_bag SET candies = 4 WHERE user_id = 7")
    bag = await tool.run(_context(), {"action": "bag"})
    assert bag.data["candies"] == 4 and bag.data["rings_left"] == RINGS_PER_DAY - 1
    ranking = await tool.run(_context(), {"action": "ranking"})
    assert [entry["name"] for entry in ranking.data["board"]] == ["Zoé", "Léa"]
    assert [entry["me"] for entry in ranking.data["board"]] == [False, True]


def test_the_cards_say_what_happened(app: App) -> None:
    treat = render_halloween(
        {"action": "ring", "outcome": "treat", "gift": "un bonbon", "gained": 1, "candies": 6}
    )
    assert "Des bonbons" in treat.cards[0].as_text() and "6" in treat.cards[0].as_text()
    trick = render_halloween(
        {"action": "ring", "outcome": "trick", "gift": "Une sorcière…", "stolen": 2, "candies": 1}
    )
    assert "Un sort" in trick.cards[0].as_text() and "-2" in trick.cards[0].as_text()
    shut = render_halloween({"action": "ring", "outcome": "closed", "candies": 3})
    assert "Reviens demain" in shut.cards[0].as_text()
    empty = render_halloween({"action": "ranking", "board": []})
    assert "Personne" in empty.cards[0].as_text()


def test_custom_emojis_have_a_unicode_fallback_only_while_loaded(app: App) -> None:
    app.plugins.load("maria_core.plugins.halloween")
    assert FALLBACKS[halloween.PUMPKIN] == "🎃" and FALLBACKS[halloween.CANDY] == "🍬"
    app.plugins.unload("halloween")
    assert halloween.PUMPKIN not in FALLBACKS


def test_the_event_is_a_plugin_loaded_by_default_and_removable(app: App) -> None:
    assert "maria_core.plugins.halloween" in DEFAULT_PLUGINS
    assert app.plugins.load("maria_core.plugins.halloween") == "halloween"
    assert "trick_or_treat" in app.capabilities
    app.plugins.unload("halloween")
    assert "trick_or_treat" not in app.capabilities
