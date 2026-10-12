"""Score reproductible, budget tenu, niveau off silencieux."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from maria_core.conversation.model import Inbound
from maria_core.db import Database
from maria_core.decisions.types import Verdict
from maria_core.social.baseline import adjust
from maria_core.social.emojis import learn
from maria_core.social.score import parts_from
from maria_core.social.service import Social

_NOW = datetime(2026, 10, 11, 18, 0, tzinfo=UTC)


class _Engine:
    def __init__(self, answers: dict[str, object]) -> None:
        self.answers = answers
        self.calls: list[str] = []

    async def resolve(self, name: str, state: dict[str, object]) -> Verdict:
        self.calls.append(name)
        return Verdict(name=name, value=self.answers.get(name, False), path="rules", confidence=1)


def _social(tmp_path: Path, engine: _Engine, clock: list[datetime]) -> tuple[Social, Database]:
    database = Database(tmp_path / "maria.db")
    database.migrate()
    social = Social(database, engine, clock=lambda: clock[0])
    social.reactor = _react
    return social, database


async def _react(_channel_id: int, _message_id: int, _emoji: str) -> bool:
    return True


def _message(**overrides: object) -> Inbound:
    values: dict[str, object] = {
        "channel_id": 3,
        "message_id": 10,
        "guild_id": 5,
        "author_id": 7,
        "author_name": "Léa",
        "text": "INCROYABLE !!!",
        "is_dm": False,
        "author_is_bot": False,
        "mentioned": False,
        "reply_to_bot": False,
        "mention_everyone": False,
        "edited": False,
        "author_is_owner": False,
        "author_is_moderator": False,
    }
    values.update(overrides)
    return Inbound(**values)  # type: ignore[arg-type]


def test_score_depends_only_on_its_inputs() -> None:
    lively = parts_from(
        humans=4,
        human_reactions=0,
        expressive=True,
        attention=2,
        fatigue=0,
        maria_reacted=False,
    )
    quiet = parts_from(
        humans=1,
        human_reactions=0,
        expressive=False,
        attention=0,
        fatigue=0,
        maria_reacted=False,
    )
    assert lively.total() == lively.total()
    assert round(lively.total(), 3) == 0.75
    assert quiet.total() < 0.35


async def test_off_stays_silent_without_calling_the_model(tmp_path: Path) -> None:
    engine = _Engine({"ambient_react": True})
    social, database = _social(tmp_path, engine, [_NOW])
    database.execute(
        "INSERT INTO guild_settings (guild_id, spontaneity, updated_at) VALUES (5, 'off', ?)",
        (_NOW.isoformat(),),
    )
    social.room.note(3, 7)
    social.room.note(3, 8)
    social.room.note(3, 9)
    social.room.bump_attention(5, 7)
    assert await social.consider(_message()) == ""
    assert engine.calls == []
    assert "off" in social.explain(10)
    database.close()


async def test_budget_and_same_author_block_the_next_reaction(tmp_path: Path) -> None:
    engine = _Engine({"ambient_react": True, "pick_reaction": "0"})
    clock = [_NOW]
    social, database = _social(tmp_path, engine, clock)
    database.execute(
        "INSERT INTO guild_settings (guild_id, spontaneity, updated_at) VALUES (5, 'normal', ?)",
        (_NOW.isoformat(),),
    )
    learn(database, 5, "😂", "trop drôle", _NOW)
    for author in (7, 8, 9, 11):
        social.room.note(3, author)

    async def consider(author: int, message_id: int) -> str:
        clock[0] += timedelta(seconds=60)
        social.room.bump_attention(5, author)
        social.room.bump_attention(5, author)
        return await social.consider(_message(author_id=author, message_id=message_id))

    assert await consider(7, 10) == "😂"
    assert await consider(7, 14) == ""
    assert social.explain(14).endswith("same_author.")
    assert await consider(8, 11) == "😂"
    assert await consider(9, 12) == "😂"
    assert await consider(11, 13) == "😂"
    database.close()


async def test_followup_respects_the_level(tmp_path: Path) -> None:
    engine = _Engine({"followup": "respond"})
    clock = [_NOW]
    social, database = _social(tmp_path, engine, clock)
    social.note_reply(_message(), "voilà")
    clock[0] = _NOW + timedelta(seconds=5)
    assert await social.wants_followup(_message(message_id=12, text="et donc")) == "respond"
    database.execute(
        "INSERT INTO guild_settings (guild_id, spontaneity, updated_at) VALUES (5, 'off', ?)",
        (_NOW.isoformat(),),
    )
    assert await social.wants_followup(_message(message_id=13, text="et donc")) == "ignore"
    database.close()


def test_a_busy_hour_raises_the_threshold_and_a_quiet_one_lowers_it() -> None:
    assert adjust(0.55, None, 10, 30) == 0.55
    assert adjust(0.55, 4, 40, 0) > 0.55
    assert adjust(0.55, 40, 1, 0) < 0.55


async def test_a_busy_habit_makes_the_same_liveliness_stay_quiet(tmp_path: Path) -> None:
    engine = _Engine({"ambient_react": True})
    social, database = _social(tmp_path, engine, [_NOW])
    learn(database, 5, "😂", "", _NOW)
    for author in (7, 8, 9, 11):
        social.room.note(3, author)
    social.room.bump_attention(5, 7)
    _habit(database, messages=4, today=40)
    assert await social.consider(_message(text="ah ok")) == ""
    assert engine.calls == []
    assert "below" in social.explain(10)
    database.close()


async def test_a_quiet_habit_lets_a_small_reaction_through(tmp_path: Path) -> None:
    engine = _Engine({"ambient_react": True})
    social, database = _social(tmp_path, engine, [_NOW])
    learn(database, 5, "😂", "", _NOW)
    social.room.note(3, 7)
    social.room.bump_attention(5, 7)
    _habit(database, messages=40, today=1)
    assert await social.consider(_message(message_id=20, text="oh !")) == "😂"
    assert engine.calls == ["ambient_react", "pick_reaction"]


async def test_a_cold_author_gets_no_ambient_reaction(tmp_path: Path) -> None:
    engine = _Engine({"ambient_react": True})
    social, database = _social(tmp_path, engine, [_NOW])
    social.room.note(3, 7)
    assert await social.consider(_message()) == ""
    assert engine.calls == []
    assert "cold" in social.explain(10)
    database.close()


async def test_a_chain_of_replies_resets_after_a_pause(tmp_path: Path) -> None:
    engine = _Engine({"followup": "respond"})
    clock = [_NOW]
    social, database = _social(tmp_path, engine, clock)
    for _ in range(5):
        social.note_reply(_message(), "oui")
        clock[0] += timedelta(seconds=10)
    assert await social.wants_followup(_message(text="et donc")) == "ignore"
    clock[0] += timedelta(hours=1)
    social.note_reply(_message(), "oui")
    clock[0] += timedelta(seconds=5)
    assert await social.wants_followup(_message(text="et donc")) == "respond"
    database.close()


def _habit(database: Database, *, messages: int, today: int) -> None:
    for day in ("2026-10-08", "2026-10-09", "2026-10-10"):
        database.execute(
            """
            INSERT INTO guild_hour_activity (guild_id, day, hour, messages)
            VALUES (5, ?, 20, ?)
            """,
            (day, messages),
        )
    database.execute(
        """
        INSERT INTO guild_hour_activity (guild_id, day, hour, messages)
        VALUES (5, '2026-10-11', 20, ?)
        """,
        (today,),
    )
