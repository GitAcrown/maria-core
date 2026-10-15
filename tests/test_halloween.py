"""Bonbons ou sort : l'outil n'existe que pendant l'événement, et le tirage est celui du code."""

import random
from datetime import datetime, timedelta
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
    result_text,
    status_text,
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


async def test_one_ring_every_three_hours_and_four_a_day(app: App) -> None:
    halloween.ensure_table(app.database)
    now = [_at("2026-10-31", 8)]
    tool = halloween_capability(app.database, clock=lambda: now[0], rng=random.Random(4))
    first = await tool.run(_context(), {"action": "ring"})
    assert first.ok and first.widget == "trick_or_treat"
    assert first.data["outcome"] in {"treat", "trick"} and first.data["rings_left"] == 3
    reopen = int((now[0] + timedelta(hours=3)).timestamp())
    assert first.data["next_at"] == reopen
    again = await tool.run(_context(), {"action": "ring"})
    assert again.data["outcome"] == "closed" and again.data["reason"] == "wait"
    assert again.data["next_at"] == reopen and again.data["rings_left"] == 3
    assert f"<t:{reopen}:R>" in result_text(again.data)
    other = await tool.run(_context(user=8, name="Paul"), {"action": "ring"})
    assert other.data["outcome"] != "closed"
    for hour in (11, 14, 17):
        now[0] = _at("2026-10-31", hour)
        result = await tool.run(_context(), {"action": "ring"})
        assert result.data["outcome"] != "closed"
    assert result.data["rings_left"] == 0 and result.data["next_at"] == 0
    now[0] = _at("2026-10-31", 23)
    full = await tool.run(_context(), {"action": "ring"})
    assert full.data["outcome"] == "closed" and full.data["reason"] == "day"
    assert "demain" in result_text(full.data)
    now[0] = _at("2026-11-01", 9)
    tomorrow = await tool.run(_context(), {"action": "ring"})
    assert tomorrow.data["outcome"] != "closed" and tomorrow.data["rings_left"] == 3


async def test_the_bag_tells_when_the_door_reopens(app: App) -> None:
    halloween.ensure_table(app.database)
    now = [_at("2026-10-31", 8)]
    tool = halloween_capability(app.database, clock=lambda: now[0], rng=random.Random(4))
    await tool.run(_context(), {"action": "ring"})
    now[0] = _at("2026-10-31", 9)
    bag = await tool.run(_context(), {"action": "bag"})
    assert bag.data["rings_left"] == 3 and bag.data["next_at"] > 0
    assert "prochaine" in status_text(bag.data)
    now[0] = _at("2026-10-31", 12)
    assert (await tool.run(_context(), {"action": "bag"})).data["next_at"] == 0


def test_a_table_from_before_the_pause_gets_its_new_column(app: App) -> None:
    halloween.ensure_table(app.database)
    app.database.execute("DROP TABLE halloween_bag")
    app.database.execute(
        "CREATE TABLE halloween_bag (guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL, "
        "name TEXT NOT NULL DEFAULT '', candies INTEGER NOT NULL DEFAULT 0, "
        "tricks INTEGER NOT NULL DEFAULT 0, day TEXT NOT NULL DEFAULT '', "
        "rings INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (guild_id, user_id))"
    )
    halloween.ensure_table(app.database)
    columns = [row["name"] for row in app.database.fetchall("PRAGMA table_info(halloween_bag)")]
    assert "last_at" in columns


async def test_the_bag_adds_up_theft_never_goes_below_zero_and_the_ranking_orders(app: App) -> None:
    halloween.ensure_table(app.database)
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
    assert "Halloween" not in treat.cards[0].as_text()  # plus de ligne d'événement dans la carte
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
