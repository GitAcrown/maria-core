"""Bonbons ou sort : l'outil saisonnier, le tirage et les gages vérifiés par le code."""

import asyncio
import random
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from maria_core.app import App
from maria_core.capabilities import Context
from maria_core.capabilities.runner import available
from maria_core.config import DEFAULT_PLUGINS, Settings
from maria_core.objectives.signals import ObjectiveSignal
from maria_core.plugins import halloween
from maria_core.plugins.halloween import (
    Reward,
    dare_listener,
    halloween_capability,
    in_season,
    render_halloween,
    result_text,
    status_text,
)
from maria_core.plugins.halloween_store import RINGS_PER_DAY, Player, ensure_table
from maria_core.plugins.halloween_sweets import SWEETS, Trick, respects
from maria_core.ui.emojis import FALLBACKS

_PARIS = ZoneInfo("Europe/Paris")


def _at(day: str, hour: int = 12, minute: int = 0) -> datetime:
    return datetime.fromisoformat(f"{day}T{hour:02d}:{minute:02d}:00").replace(tzinfo=_PARIS)


def _context(user: int = 7, name: str = "Léa", message: int = 100) -> Context:
    return Context(
        user_id=user,
        guild_id=5,
        channel_id=3,
        message_id=message,
        is_owner=False,
        is_moderator=False,
        text="bonbons ou sort",
        author_name=name,
    )


class _Dice(random.Random):
    """Un tirage dicté : un bonbon, ou un sort d'un genre précis."""

    def __init__(self, *, trick: bool = False, pick: str = "emoji") -> None:
        super().__init__(1)
        self.trick, self.pick = trick, pick

    def random(self) -> float:
        return 0.0 if self.trick else 0.99

    def choice(self, seq: Any) -> Any:
        if seq and isinstance(seq[0], Trick):
            return next(item for item in seq if item.kind == self.pick)
        return seq[0]


def test_the_tool_exists_from_today_to_november_first_included() -> None:
    assert not in_season(lambda: _at("2026-10-14", 23))
    assert in_season(lambda: _at("2026-10-15", 0))
    assert in_season(lambda: _at("2026-11-01", 23))
    assert not in_season(lambda: _at("2026-11-02", 0))


def test_the_model_only_sees_the_tool_during_the_event(app: App) -> None:
    now = [_at("2026-10-20")]
    app.capabilities.register(halloween_capability(app.database, clock=lambda: now[0]))
    settings = Settings.for_tests(app.settings.data_dir)
    assert "trick_or_treat" in [item.name for item in available(app.capabilities, settings)]
    now[0] = _at("2026-11-02")
    assert "trick_or_treat" not in [item.name for item in available(app.capabilities, settings)]


async def test_one_ring_every_three_hours_and_four_a_day(app: App) -> None:
    ensure_table(app.database)
    now = [_at("2026-10-31", 8)]
    tool = halloween_capability(app.database, clock=lambda: now[0], rng=_Dice())
    first = await tool.run(_context(), {"action": "ring"})
    assert first.ok and first.widget == "trick_or_treat"
    assert first.data["outcome"] == "treat" and first.data["rings_left"] == 3
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
    assert RINGS_PER_DAY == 4
    now[0] = _at("2026-11-01", 9)
    tomorrow = await tool.run(_context(), {"action": "ring"})
    assert tomorrow.data["outcome"] != "closed" and tomorrow.data["rings_left"] == 3


async def test_sweets_are_drawn_at_random_and_collected_by_kind(app: App) -> None:
    ensure_table(app.database)
    tool = halloween_capability(app.database, clock=lambda: _at("2026-10-25"), rng=random.Random(3))
    seen = set()
    for user in range(10, 40):
        result = await tool.run(_context(user=user, name=f"M{user}"), {"action": "ring"})
        if result.data["outcome"] == "treat":
            seen.add(result.data["emoji"])
            assert result.data["emoji"] in [sweet.emoji for sweet in SWEETS]
    assert len(seen) >= 3
    mine = await tool.run(_context(user=10), {"action": "bag"})
    collection = dict(mine.data["sweets"])
    assert set(collection) == {sweet.emoji for sweet in SWEETS}
    assert sum(collection.values()) == mine.data["candies"]


async def test_a_theft_never_goes_below_zero_and_takes_from_the_collection(app: App) -> None:
    ensure_table(app.database)
    app.database.execute("INSERT INTO halloween_bag (guild_id, user_id, candies) VALUES (5, 7, 1)")
    app.database.execute("INSERT INTO halloween_sweets VALUES (5, 7, 'caramel', 1)")
    tool = halloween_capability(
        app.database, clock=lambda: _at("2026-10-25"), rng=_Dice(trick=True, pick="")
    )
    result = await tool.run(_context(), {"action": "ring"})
    assert result.data["outcome"] == "trick" and result.data["stolen"] == 1
    assert result.data["candies"] == 0 and all(count == 0 for _e, count in result.data["sweets"])


async def test_an_old_bag_counts_as_plain_candies(app: App) -> None:
    ensure_table(app.database)
    app.database.execute("INSERT INTO halloween_bag (guild_id, user_id, candies) VALUES (5, 7, 5)")
    tool = halloween_capability(app.database, clock=lambda: _at("2026-10-25"))
    bag = await tool.run(_context(), {"action": "bag"})
    assert dict(bag.data["sweets"])[SWEETS[0].emoji] == 5


def test_each_dare_is_checked_by_the_code() -> None:
    assert respects("word", "fantôme", "ce FANTOME me fait peur")
    assert not respects("word", "fantôme", "les fantômes arrivent")
    assert respects("caps", "", "OK TOUT EST BON")
    assert not respects("caps", "", "Ok tout est bon")
    assert not respects("caps", "", "OUI")
    assert respects("emoji", "", "bonne nuit 👻")
    assert not respects("emoji", "", "bonne nuit")
    assert respects("long", "", " ".join(["mot"] * 20))
    assert not respects("long", "", " ".join(["mot"] * 19))
    assert respects("question", "", "tu viens ?")
    assert not respects("question", "", "tu viens")
    assert not respects("inconnu", "", "tu viens ?")


async def test_a_respected_dare_rewards_one_candy_and_a_reaction(app: App) -> None:
    ensure_table(app.database)
    now = [_at("2026-10-25", 10)]
    watch: set[tuple[int, int]] = set()
    dice = _Dice(trick=True, pick="emoji")
    tool = halloween_capability(app.database, clock=lambda: now[0], rng=dice, watch=watch)
    result = await tool.run(_context(message=100), {"action": "ring"})
    assert result.data["dare"]["text"].startswith("Glisse un 🎃")
    assert watch == {(5, 7)} and "Réussis-le" in result_text(result.data)
    bag = await tool.run(_context(), {"action": "bag"})
    assert "**Gage en cours**" in result_text(bag.data)

    rewards: list[Reward] = []

    async def collect(reward: Reward) -> None:
        rewards.append(reward)

    app.events.subscribe(Reward, collect)
    listener = dare_listener(
        app.database, app.events, watch, clock=lambda: now[0], rng=random.Random(2)
    )

    def message(identifier: int, text: str) -> ObjectiveSignal:
        return ObjectiveSignal(
            kind="message",
            key=f"m{identifier}",
            channel_id=3,
            guild_id=5,
            user_id=7,
            text=text,
            url=f"https://discord.com/channels/5/77/{identifier}",
            message_id=identifier,
        )

    await listener(message(99, "avant la sonnerie 👻"))  # antérieur : ne compte pas
    await listener(message(101, "salut"))
    await listener(message(102, "toujours rien"))
    assert (5, 7) in watch and not rewards
    await listener(message(103, "voilà 🎃"))
    await asyncio.sleep(0.05)  # laisse partir la publication en tâche de fond
    assert watch == set()
    sent = [reward for reward in rewards if reward.message_id == 103]
    assert len(sent) == 1 and sent[0].channel_id == 77
    assert sent[0].emoji in [sweet.emoji for sweet in SWEETS]
    after = await tool.run(_context(), {"action": "bag"})
    assert after.data["candies"] == 1 and after.data["dare"] is None
    await listener(message(104, "encore 🎃"))  # plus de gage : rien
    await asyncio.sleep(0.05)
    assert len([reward for reward in rewards if reward.message_id == 104]) == 0


async def test_a_dare_ends_after_three_messages_or_an_hour(app: App) -> None:
    ensure_table(app.database)
    now = [_at("2026-10-25", 10)]
    watch: set[tuple[int, int]] = set()
    tool = halloween_capability(
        app.database, clock=lambda: now[0], rng=_Dice(trick=True, pick="question"), watch=watch
    )
    await tool.run(_context(message=10), {"action": "ring"})
    listener = dare_listener(app.database, app.events, watch, clock=lambda: now[0])

    def message(identifier: int) -> ObjectiveSignal:
        return ObjectiveSignal(
            kind="message",
            key="k",
            channel_id=3,
            guild_id=5,
            user_id=7,
            text="rien",
            message_id=identifier,
        )

    for identifier in (11, 12, 13):
        await listener(message(identifier))
    assert watch == set()
    now[0] = _at("2026-10-25", 14)
    await tool.run(_context(message=20), {"action": "ring"})
    assert watch == {(5, 7)}
    now[0] = _at("2026-10-25", 16)  # plus d'une heure après
    await listener(message(21))
    assert watch == set()
    assert (await tool.run(_context(), {"action": "bag"})).data["dare"] is None


def test_the_cards_say_what_happened(app: App) -> None:
    treat = render_halloween(
        {
            "action": "ring",
            "outcome": "treat",
            "gift": "une sucette",
            "gained": 1,
            "emoji": SWEETS[3].emoji,
            "candies": 6,
        }
    )
    text = treat.cards[0].as_text()
    assert "Des bonbons" in text and SWEETS[3].emoji in text and "Halloween" not in text
    trick = render_halloween(
        {"action": "ring", "outcome": "trick", "gift": "Une sorcière…", "stolen": 2, "candies": 1}
    )
    assert "Un sort" in trick.cards[0].as_text() and "-2" in trick.cards[0].as_text()
    dare = render_halloween(
        {"action": "ring", "outcome": "trick", "gift": "Pose une question", "dare": {"text": "x"}}
    )
    assert "Réussis-le" in dare.cards[0].as_text()
    shut = render_halloween({"action": "ring", "outcome": "closed", "candies": 3})
    assert "Reviens demain" in shut.cards[0].as_text()
    empty = render_halloween({"action": "ranking", "board": []})
    assert "Personne" in empty.cards[0].as_text()
    assert "prochaine" in status_text({"action": "bag", "rings_left": 2, "next_at": 1})


def test_a_table_from_before_the_pause_gets_its_new_column(app: App) -> None:
    ensure_table(app.database)
    app.database.execute("DROP TABLE halloween_bag")
    app.database.execute(
        "CREATE TABLE halloween_bag (guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL, "
        "name TEXT NOT NULL DEFAULT '', candies INTEGER NOT NULL DEFAULT 0, "
        "tricks INTEGER NOT NULL DEFAULT 0, day TEXT NOT NULL DEFAULT '', "
        "rings INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (guild_id, user_id))"
    )
    ensure_table(app.database)
    columns = [row["name"] for row in app.database.fetchall("PRAGMA table_info(halloween_bag)")]
    assert "last_at" in columns


def test_custom_emojis_have_a_unicode_fallback_only_while_loaded(app: App) -> None:
    app.plugins.load("maria_core.plugins.halloween")
    tags = [halloween.PUMPKIN, halloween.GOBLET, *[sweet.emoji for sweet in SWEETS]]
    assert all(tag in FALLBACKS for tag in tags)
    app.plugins.unload("halloween")
    assert not any(tag in FALLBACKS for tag in tags)


def test_the_event_is_a_plugin_loaded_by_default_and_removable(app: App) -> None:
    assert "maria_core.plugins.halloween" in DEFAULT_PLUGINS
    assert app.plugins.load("maria_core.plugins.halloween") == "halloween"
    assert "trick_or_treat" in app.capabilities
    app.plugins.unload("halloween")
    assert "trick_or_treat" not in app.capabilities
    assert app.events.publish_soon  # le bus reste utilisable, sans l'abonné du gage
    assert Player(5, 7, "Léa").guild == 5
