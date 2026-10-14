"""Objectifs : ce que la revue de parité avec MARIA_R a corrigé."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from maria_core.capabilities import CapabilityRegistry, Context
from maria_core.capabilities.runner import invoke
from maria_core.config import Settings
from maria_core.conversation.model import Inbound
from maria_core.db import Database
from maria_core.decisions.types import Verdict
from maria_core.llm.types import ToolCall
from maria_core.objectives.catalog import register_builtin_kinds
from maria_core.objectives.compile import check_plan, compile_trigger
from maria_core.objectives.drafts import Drafts
from maria_core.objectives.matcher import matches, word_in
from maria_core.objectives.model import Objective
from maria_core.objectives.pipeline import Delivery
from maria_core.objectives.runtime import Objectives
from maria_core.objectives.schedule import PARIS
from maria_core.objectives.signals import ObjectiveSignal
from maria_core.objectives.tools import objective_capabilities
from maria_core.objectives.types import ObjectiveTypes

_NOW = datetime(2026, 10, 12, 8, 0, tzinfo=UTC)


class _Courier:
    def __init__(self) -> None:
        self.sent: list[Delivery] = []
        self.notices: list[str] = []

    async def send(self, _objective: object, delivery: Delivery) -> None:
        self.sent.append(delivery)

    async def notify(self, _objective: object, text: str) -> None:
        self.notices.append(text)


class _Engine:
    def __init__(self, value: object) -> None:
        self.value = value
        self.names: list[str] = []

    async def resolve(self, name: str, state: dict[str, object]) -> Verdict:
        self.names.append(name)
        return Verdict(name=name, value=self.value, path="model", confidence=0.9)


def _open(
    tmp_path: Path, clock: list[datetime], *, fetcher=None, judge=None
) -> tuple[Objectives, Database, _Courier]:
    database = Database(tmp_path / "maria.db")
    database.migrate()
    service = Objectives(database, clock=lambda: clock[0], fetcher=fetcher, judge=judge)
    courier = _Courier()
    service.runner.courier = courier
    return service, database, courier


def _context() -> Context:
    return Context(
        user_id=7,
        guild_id=5,
        channel_id=3,
        message_id=99,
        is_owner=False,
        is_moderator=False,
        text="",
    )


async def _create(service: Objectives, tmp_path: Path, **arguments: object) -> dict[str, object]:
    registry = CapabilityRegistry()
    for capability in objective_capabilities(service):
        registry.register(capability)
    result = await invoke(
        registry,
        Settings.for_tests(tmp_path),
        _context(),
        ToolCall(id="1", name="objective_create", arguments=dict(arguments)),
    )
    assert result.ok, result.error
    return dict(result.data)


def test_a_date_without_timezone_is_read_in_paris() -> None:
    trigger = compile_trigger({"trigger_type": "at", "at": "2026-10-12T20:00"}, _types(), now=_NOW)
    moment = datetime.fromisoformat(str(trigger["at"]))
    assert moment.astimezone(PARIS).hour == 20


def test_in_minutes_and_past_dates() -> None:
    trigger = compile_trigger({"trigger_type": "at", "in_minutes": 10}, _types(), now=_NOW)
    assert datetime.fromisoformat(str(trigger["at"])) == _NOW + timedelta(minutes=10)
    with pytest.raises(ValueError, match="passée"):
        compile_trigger({"trigger_type": "at", "at": "2026-10-11T08:00"}, _types(), now=_NOW)


def test_plans_that_would_spam_are_refused() -> None:
    with pytest.raises(ValueError, match="judge"):
        check_plan({"type": "on_message"}, None, {"type": "remind"})
    with pytest.raises(ValueError, match="fetch_then"):
        check_plan({"type": "daily"}, {"type": "price_below"}, {"type": "remind"})
    with pytest.raises(ValueError, match="6 h"):
        check_plan({"type": "interval", "every_s": 600}, None, {"type": "fetch_then"})


async def test_a_one_shot_listening_objective_is_active_at_once_and_fires_once(
    tmp_path: Path,
) -> None:
    clock = [_NOW]
    service, database, courier = _open(tmp_path, clock)
    data = await _create(
        service,
        tmp_path,
        title="Ranked",
        trigger_type="on_topic",
        pattern="ranked, classé",
        action_type="alert",
        text="ça parle de ranked",
    )
    assert data["status"] == "active"
    assert data["max_fires"] == 1
    signal = ObjectiveSignal(
        kind="message", key="message:1", channel_id=3, guild_id=5, user_id=8, text="une classé ?"
    )
    assert await service.matcher.handle(signal, now=clock[0]) == 1
    second = ObjectiveSignal(
        kind="message", key="message:2", channel_id=3, guild_id=5, user_id=8, text="classé"
    )
    assert await service.matcher.handle(second, now=clock[0]) == 0
    assert len(courier.sent) == 1
    assert "> une classé ?" in courier.sent[0].text
    database.close()


async def test_a_judged_condition_also_gates_a_plain_reminder(tmp_path: Path) -> None:
    clock = [_NOW]
    verdicts = [False]

    async def judge(_text: str, _evidence: str) -> bool:
        return verdicts[0]

    service, database, courier = _open(tmp_path, clock, judge=judge)
    service.store.create(
        owner_id=7,
        guild_id=5,
        channel_ids=(3,),
        deliver="channel",
        title="Vente",
        trigger={"type": "on_topic", "pattern": "vente", "repeat": True},
        condition={"type": "judge", "text": "le message annonce une vente", "when": "before"},
        action={"type": "alert", "text": "vente repérée"},
        now=clock[0],
    )
    signal = ObjectiveSignal(
        kind="message", key="message:5", channel_id=3, guild_id=5, user_id=8, text="la vente"
    )
    assert await service.matcher.handle(signal, now=clock[0]) == 0
    verdicts[0] = True
    other = ObjectiveSignal(
        kind="message", key="message:6", channel_id=3, guild_id=5, user_id=8, text="vente !"
    )
    assert await service.matcher.handle(other, now=clock[0]) == 1
    assert courier.sent[0].text.startswith("vente repérée")
    database.close()


async def test_every_web_read_counts_and_a_price_alert_is_not_repeated(tmp_path: Path) -> None:
    clock = [_NOW]
    reads = {"n": 0}

    async def fetch(_url: str) -> str:
        reads["n"] += 1
        return "Prix : 9,90 €"

    service, database, courier = _open(tmp_path, clock, fetcher=fetch)
    service.store.create(
        owner_id=7,
        guild_id=5,
        channel_ids=(3,),
        deliver="channel",
        title="Prix",
        trigger={"type": "interval", "every_s": 6 * 3600},
        condition={"type": "price_below", "threshold": 10},
        action={"type": "fetch_then", "url": "https://shop.test/p", "text": ""},
        now=clock[0] - timedelta(hours=7),
    )
    for _ in range(2):
        claimed = service.store.claim(clock[0])
        assert claimed is not None
        await service.runner.execute(claimed)
        clock[0] += timedelta(hours=6, minutes=1)
    assert reads["n"] == 2
    assert len(courier.sent) == 1
    count = database.fetchone("SELECT COUNT(*) AS n FROM objective_fetches")
    assert count is not None
    assert count["n"] == 2
    database.close()


async def test_a_reminder_replies_to_the_request_and_names_its_kind(tmp_path: Path) -> None:
    clock = [_NOW]
    service, database, courier = _open(tmp_path, clock)
    data = await _create(
        service,
        tmp_path,
        title="Eau",
        trigger_type="at",
        in_minutes=1,
        action_type="remind",
        text="bois de l'eau",
    )
    assert data["status"] == "active"
    clock[0] += timedelta(minutes=2)
    claimed = service.store.claim(clock[0])
    assert claimed is not None
    assert await service.runner.execute(claimed) == "sent"
    delivery = courier.sent[0]
    assert delivery.reply_to == 99
    assert delivery.mention is True
    assert delivery.footer == "**Rappel**"
    database.close()


def test_listening_matches_whole_words_authors_and_voice_targets() -> None:
    assert word_in("Grosse vente ce soir", "vente")
    assert not word_in("Quelle aventure", "vente")
    assert word_in("le métro", "metro")
    objective = _objective({"type": "on_topic", "pattern": "jeu", "author": "self"})
    mine = ObjectiveSignal(kind="message", key="k", channel_id=3, guild_id=5, user_id=7, text="jeu")
    theirs = ObjectiveSignal(
        kind="message", key="k", channel_id=3, guild_id=5, user_id=8, text="jeu"
    )
    assert matches(objective, mine)
    assert not matches(objective, theirs)
    voice = _objective({"type": "on_voice", "signal": "stream", "user_id": 8})
    stream = ObjectiveSignal(kind="voice_stream", key="v", channel_id=40, guild_id=5, user_id=8)
    join = ObjectiveSignal(kind="voice_join", key="v", channel_id=40, guild_id=5, user_id=8)
    other = ObjectiveSignal(kind="voice_stream", key="v", channel_id=40, guild_id=5, user_id=9)
    assert matches(voice, stream)
    assert not matches(voice, join)
    assert not matches(voice, other)


def _objective(trigger: dict[str, object]) -> Objective:
    return Objective(
        id=1,
        owner_id=7,
        guild_id=5,
        channel_ids=(3,),
        deliver="channel",
        title="t",
        trigger=trigger,
        condition=None,
        action={"type": "alert", "text": "x"},
        status="active",
        next_run_at=None,
        fires=0,
        max_fires=None,
        cooldown_s=0,
        expires_at=None,
        state={},
        version=1,
        last_error="",
    )


def _types() -> ObjectiveTypes:
    types = ObjectiveTypes()
    register_builtin_kinds(types)
    return types


def _inbound(text: str) -> Inbound:
    return Inbound(
        channel_id=3,
        message_id=50,
        guild_id=5,
        author_id=7,
        author_name="Léa",
        text=text,
        is_dm=False,
        author_is_bot=False,
        mentioned=False,
        reply_to_bot=False,
        mention_everyone=False,
        edited=False,
        author_is_owner=False,
        author_is_moderator=False,
    )


def test_a_listening_trigger_keeps_only_the_distinctive_name() -> None:
    trigger = compile_trigger(
        {
            "trigger_type": "on_topic",
            "pattern": "le film « Le corset », Corset",
            "topic": "le film « Le Corset »",
        },
        _types(),
        now=_NOW,
    )
    assert trigger["pattern"] == "corset"
    assert trigger["aliases"] == ["Corset"]
    assert trigger["topic"] == "le film Le Corset"
    assert word_in("Le Corset est un film sur la scoliose", "corset")
    misérables = compile_trigger(
        {"trigger_type": "on_topic", "pattern": "Les Misérables"}, _types()
    )
    assert misérables["pattern"] == "Misérables"


async def test_a_draft_is_still_confirmed_by_a_plain_message_hours_later(tmp_path: Path) -> None:
    clock = [_NOW]
    service, database, _courier = _open(tmp_path, clock)
    data = await _create(
        service,
        tmp_path,
        title="Le Corset",
        trigger_type="on_topic",
        pattern="le film « Le corset »",
        action_type="alert",
        text="Quelqu'un parle du film Le Corset",
        repeat=True,
    )
    assert data["status"] == "draft"
    clock[0] = _NOW + timedelta(hours=2)
    drafts = Drafts(service, _Engine("accept"))
    assert await drafts.answer(_inbound("oui")) is True
    assert service.store.get(int(str(data["id"]))).status == "active"
    database.close()


async def test_a_forgotten_draft_stops_listening_after_a_while(tmp_path: Path) -> None:
    clock = [_NOW]
    service, database, _courier = _open(tmp_path, clock)
    await _create(
        service,
        tmp_path,
        title="Ranked",
        trigger_type="on_topic",
        pattern="ranked",
        action_type="alert",
        text="ça parle de ranked",
        repeat=True,
    )
    clock[0] = _NOW + timedelta(hours=5)
    assert await Drafts(service, _Engine("accept")).answer(_inbound("oui")) is False
    database.close()


async def test_the_alert_names_who_spoke_not_who_asked(tmp_path: Path) -> None:
    clock = [_NOW]
    service, database, courier = _open(tmp_path, clock)
    service.store.create(
        owner_id=7,
        guild_id=5,
        channel_ids=(3,),
        deliver="channel",
        title="Corset",
        trigger={"type": "on_topic", "pattern": "corset"},
        condition=None,
        action={"type": "alert", "text": "Quelqu'un parle du film Le Corset"},
        now=clock[0],
    )
    signal = ObjectiveSignal(
        kind="message",
        key="message:9",
        channel_id=3,
        guild_id=5,
        user_id=8,
        text="Le corset est un film sur la scoliose",
        author_name="Léa",
    )
    assert await service.matcher.handle(signal, now=clock[0]) == 1
    assert courier.sent[0].text == (
        "Quelqu'un parle du film Le Corset\n> **Léa** : Le corset est un film sur la scoliose"
    )
    database.close()


async def test_only_what_can_become_a_chore_asks_for_a_yes(tmp_path: Path) -> None:
    clock = [_NOW]
    service, database, _courier = _open(tmp_path, clock)
    once = {
        "trigger_type": "at",
        "in_minutes": 10,
        "action_type": "remind",
        "text": "Sors le chien",
    }
    assert (await _create(service, tmp_path, title="Chien", **once))["status"] == "active"
    listen = {"trigger_type": "on_topic", "pattern": "ranked", "action_type": "alert"}
    assert (await _create(service, tmp_path, title="Ranked", text="x", **listen))[
        "status"
    ] == "active"
    daily = {"trigger_type": "daily", "time": "08:00", "action_type": "remind"}
    assert (await _create(service, tmp_path, title="Eau", text="Bois", **daily))[
        "status"
    ] == "draft"
    again = {**listen, "pattern": "tournoi", "repeat": True}
    assert (await _create(service, tmp_path, title="Tournoi", text="x", **again))[
        "status"
    ] == "draft"
    watch = {
        "trigger_type": "interval",
        "every_minutes": 720,
        "action_type": "fetch_then",
        "url": "https://shop.test/p",
        "condition_type": "price_below",
        "threshold": 50,
    }
    assert (await _create(service, tmp_path, title="Prix", text="x", **watch))["status"] == "draft"
    database.close()
