"""Échéances, bail, créneau unique, relances, outils."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from maria_core.capabilities import CapabilityRegistry, Context
from maria_core.capabilities.runner import invoke
from maria_core.config import Settings
from maria_core.db import Database
from maria_core.llm.types import ToolCall
from maria_core.objectives.model import StaleObjective
from maria_core.objectives.pipeline import Delivery, Written
from maria_core.objectives.price import extract_price
from maria_core.objectives.quota import MAX_OPEN
from maria_core.objectives.runtime import Objectives
from maria_core.objectives.schedule import PARIS, next_due, time_key
from maria_core.objectives.signals import ObjectiveSignal
from maria_core.objectives.tools import objective_capabilities

_PARIS = ZoneInfo("Europe/Paris")


class _Courier:
    def __init__(self, *, fail: bool = False) -> None:
        self.sent: list[str] = []
        self.deliveries: list[Delivery] = []
        self.notices: list[str] = []
        self.fail = fail

    async def send(self, _objective: object, delivery: Delivery) -> None:
        if self.fail:
            raise RuntimeError("canal coupé")
        self.sent.append(delivery.text)
        self.deliveries.append(delivery)

    async def notify(self, _objective: object, text: str) -> None:
        self.notices.append(text)


def _open(
    tmp_path: Path, clock: list[datetime], fetcher=None
) -> tuple[Objectives, Database, _Courier]:
    database = Database(tmp_path / "maria.db")
    database.migrate()
    courier = _Courier()
    service = Objectives(database, clock=lambda: clock[0], fetcher=fetcher, writer=_Writer())
    service.runner.courier = courier
    return service, database, courier


class _Writer:
    async def write(
        self,
        _objective: object,
        instruction: str,
        _evidence: str,
        _runs: tuple[tuple[str, str], ...],
    ) -> Written:
        return Written(f"rédigé : {instruction}")


def _due(service: Objectives, *, title: str = "Boire", text: str = "bois de l'eau") -> int:
    moment = service.now()
    objective, created = service.store.create(
        owner_id=7,
        guild_id=5,
        channel_ids=(3,),
        deliver="channel",
        title=title,
        trigger={"type": "at", "at": moment.isoformat()},
        condition=None,
        action={"type": "remind", "text": text},
        now=moment,
    )
    assert created
    return objective.id


def _daily(
    service: Objectives, *, title: str = "Boire", text: str = "bois de l'eau", when: str = "09:00"
) -> int:
    objective, created = service.store.create(
        owner_id=7,
        guild_id=5,
        channel_ids=(3,),
        deliver="channel",
        title=title,
        trigger={"type": "daily", "time": when},
        condition=None,
        action={"type": "remind", "text": text},
        now=service.now(),
    )
    assert created
    return objective.id


def test_daily_stays_at_nine_across_the_paris_clock_change() -> None:
    after = datetime(2026, 3, 28, 9, 0, tzinfo=UTC)
    nxt = next_due({"type": "daily", "time": "09:00"}, after=after)
    assert nxt is not None
    local = nxt.astimezone(PARIS)
    assert local.date().isoformat() == "2026-03-29"
    assert (local.hour, local.minute) == (9, 0)
    assert nxt.astimezone(UTC).hour == 7


def test_weekly_skips_to_the_next_asked_day() -> None:
    tuesday = datetime(2026, 10, 13, 12, 0, tzinfo=PARIS)
    nxt = next_due(
        {"type": "weekly", "time": "08:30", "weekdays": ["thu"]},
        after=tuesday.astimezone(UTC),
    )
    assert nxt is not None
    assert nxt.astimezone(PARIS).weekday() == 3
    assert nxt.astimezone(PARIS).strftime("%H:%M") == "08:30"


def test_price_with_a_comma_is_read() -> None:
    assert extract_price("soldé 12,50 € aujourd'hui") == 12.5


async def test_claim_is_exclusive_until_the_lease_ends(tmp_path: Path) -> None:
    clock = [datetime(2026, 10, 11, 8, 0, tzinfo=UTC)]
    service, database, _courier = _open(tmp_path, clock)
    _due(service)
    assert service.store.claim(clock[0]) is not None
    assert service.store.claim(clock[0]) is None
    database.close()


async def test_a_recorded_run_is_not_sent_again_after_restart(tmp_path: Path) -> None:
    clock = [datetime(2026, 10, 11, 8, 0, tzinfo=UTC)]
    service, database, courier = _open(tmp_path, clock)
    _due(service)
    claimed = service.store.claim(clock[0])
    assert claimed is not None
    assert claimed.next_run_at is not None
    database.execute(
        """
        INSERT INTO objective_runs (objective_id, activation_key, started_at, outcome, finished_at)
        VALUES (?, ?, ?, 'sent', ?)
        """,
        (claimed.id, time_key(claimed.next_run_at), clock[0].isoformat(), clock[0].isoformat()),
    )
    assert await service.runner.execute(claimed) == "duplicate"
    assert courier.sent == []
    saved = service.store.get(claimed.id)
    assert saved is not None
    assert saved.next_run_at != claimed.next_run_at
    database.close()


async def test_the_same_message_fires_an_event_objective_once(tmp_path: Path) -> None:
    clock = [datetime(2026, 10, 11, 8, 0, tzinfo=UTC)]
    service, database, courier = _open(tmp_path, clock)
    service.store.create(
        owner_id=7,
        guild_id=5,
        channel_ids=(3,),
        deliver="channel",
        title="Écoute",
        trigger={"type": "on_topic", "pattern": "métro"},
        condition=None,
        action={"type": "remind", "text": "j'ai vu le métro"},
        now=clock[0],
    )
    signal = ObjectiveSignal(
        kind="message",
        key="message:42",
        channel_id=3,
        guild_id=5,
        user_id=8,
        text="le métro est bloqué",
    )
    assert await service.matcher.handle(signal, now=clock[0]) == 1
    assert await service.matcher.handle(signal, now=clock[0]) == 0
    assert courier.sent[0].startswith("j'ai vu le métro")
    assert len(courier.sent) == 1
    assert "le métro est bloqué" in courier.sent[0]
    database.close()


async def test_a_late_reminder_is_sent_and_an_old_one_is_marked_missed(tmp_path: Path) -> None:
    clock = [datetime(2026, 10, 11, 12, 0, tzinfo=UTC)]
    service, database, courier = _open(tmp_path, clock)
    recent, _created = service.store.create(
        owner_id=7,
        guild_id=5,
        channel_ids=(3,),
        deliver="channel",
        title="Récent",
        trigger={"type": "at", "at": (clock[0] - timedelta(hours=1)).isoformat()},
        condition=None,
        action={"type": "remind", "text": "encore temps"},
        now=clock[0] - timedelta(hours=2),
        max_fires=1,
    )
    claimed = service.store.claim(clock[0])
    assert claimed is not None
    assert claimed.id == recent.id
    assert await service.runner.execute(claimed) == "sent"
    assert courier.sent == ["encore temps"]
    assert courier.deliveries[0].footer == "**Rappel**"

    old, _created = service.store.create(
        owner_id=7,
        guild_id=5,
        channel_ids=(3,),
        deliver="channel",
        title="Ancien",
        trigger={"type": "at", "at": (clock[0] - timedelta(hours=7)).isoformat()},
        condition=None,
        action={"type": "remind", "text": "trop tard"},
        now=clock[0] - timedelta(hours=8),
        max_fires=1,
    )
    claimed = service.store.claim(clock[0])
    assert claimed is not None
    assert claimed.id == old.id
    assert await service.runner.execute(claimed) == "missed"
    assert "trop tard" not in courier.sent
    assert courier.notices
    database.close()


async def test_three_retries_then_the_objective_fails(tmp_path: Path) -> None:
    clock = [datetime(2026, 10, 11, 8, 0, tzinfo=UTC)]
    service, database, courier = _open(tmp_path, clock)
    courier.fail = True
    _due(service)
    for _ in range(4):
        claimed = service.store.claim(clock[0])
        assert claimed is not None
        assert await service.runner.execute(claimed) == "failed"
        saved = service.store.get(claimed.id)
        assert saved is not None
        clock[0] = saved.next_run_at or clock[0]
    saved = service.store.get(1)
    assert saved is not None
    assert saved.status == "failed"
    assert courier.notices
    database.close()


async def test_a_stale_update_is_refused_and_a_change_reschedules(tmp_path: Path) -> None:
    clock = [datetime(2026, 10, 11, 8, 0, tzinfo=UTC)]
    service, database, _courier = _open(tmp_path, clock)
    _daily(service)
    current = service.store.get(1)
    assert current is not None
    paused = service.store.settle(
        current,
        now=clock[0],
        status="paused",
        next_run_at=current.next_run_at,
        fires=0,
        state=current.state,
    )
    try:
        service.store.revise(
            current,
            now=clock[0],
            title=current.title,
            trigger={"type": "daily", "time": "18:00"},
            condition=None,
            action=dict(current.action),
            next_run_at=clock[0],
        )
        raise AssertionError("version périmée")
    except StaleObjective:
        pass
    revised = service.store.revise(
        paused,
        now=clock[0],
        title="Boire",
        trigger={"type": "daily", "time": "18:00"},
        condition=None,
        action=dict(paused.action),
        next_run_at=next_due({"type": "daily", "time": "18:00"}, after=clock[0]),
    )
    assert revised.version == paused.version + 1
    assert revised.next_run_at is not None
    assert revised.next_run_at.astimezone(PARIS).hour == 18
    database.close()


async def test_creating_the_same_objective_returns_the_existing_one(tmp_path: Path) -> None:
    clock = [datetime(2026, 10, 11, 8, 0, tzinfo=UTC)]
    service, database, _courier = _open(tmp_path, clock)
    _daily(service, title="Boire")
    again, created = service.store.create(
        owner_id=7,
        guild_id=5,
        channel_ids=(3,),
        deliver="channel",
        title="Autre titre",
        trigger={"type": "daily", "time": "09:00"},
        condition=None,
        action={"type": "remind", "text": "bois de l'eau"},
        now=clock[0],
    )
    assert created is False
    assert again.id == 1
    other, created = service.store.create(
        owner_id=7,
        guild_id=5,
        channel_ids=(3,),
        deliver="channel",
        title="Boire",
        trigger={"type": "daily", "time": "20:00"},
        condition=None,
        action={"type": "remind", "text": "bois de l'eau"},
        now=clock[0],
    )
    assert created is True
    assert other.id == 2
    database.close()


async def test_skip_moves_an_overdue_daily_to_the_next_future_slot(tmp_path: Path) -> None:
    clock = [datetime(2026, 10, 11, 16, 0, tzinfo=UTC)]
    service, database, _courier = _open(tmp_path, clock)
    yesterday = clock[0] - timedelta(days=1)
    service.store.create(
        owner_id=7,
        guild_id=5,
        channel_ids=(3,),
        deliver="channel",
        title="Matin",
        trigger={"type": "daily", "time": "09:00"},
        condition=None,
        action={"type": "remind", "text": "debout"},
        now=yesterday,
    )
    current = service.store.get(1)
    assert current is not None
    assert current.next_run_at is not None
    assert current.next_run_at < clock[0]
    registry = CapabilityRegistry()
    for capability in objective_capabilities(service):
        registry.register(capability)
    result = await invoke(
        registry,
        Settings.for_tests(tmp_path),
        Context(
            user_id=7,
            guild_id=5,
            channel_id=3,
            message_id=1,
            is_owner=False,
            is_moderator=False,
            text="",
        ),
        ToolCall(id="1", name="objective_update", arguments={"id": 1, "op": "skip"}),
    )
    assert result.ok is True
    skipped = service.store.get(1)
    assert skipped is not None
    assert skipped.next_run_at is not None
    assert skipped.next_run_at > clock[0]
    database.close()


async def test_open_objective_quota(tmp_path: Path) -> None:
    assert MAX_OPEN == 10
    clock = [datetime(2026, 10, 11, 8, 0, tzinfo=UTC)]
    service, database, _courier = _open(tmp_path, clock)
    for index in range(MAX_OPEN):
        _daily(service, title=f"Tâche {index}", text=f"texte {index}", when=f"{index % 24:02d}:00")
    try:
        _daily(service, title="De trop", text="non")
        raise AssertionError("quota")
    except Exception as exc:
        assert "Plafond" in str(exc)
    database.close()


async def test_fetch_sends_only_when_the_price_is_under_the_threshold(tmp_path: Path) -> None:
    clock = [datetime(2026, 10, 11, 8, 0, tzinfo=UTC)]
    pages = ["Promo 9,90 €"]

    async def fetch(_url: str) -> str:
        return pages[0]

    service, database, courier = _open(tmp_path, clock, fetcher=fetch)
    service.store.create(
        owner_id=7,
        guild_id=5,
        channel_ids=(3,),
        deliver="channel",
        title="Prix",
        trigger={"type": "at", "at": clock[0].isoformat()},
        condition={"type": "price_below", "threshold": 10},
        action={"type": "fetch_then", "url": "https://shop.test/p", "text": "tombé à {price}"},
        now=clock[0] - timedelta(minutes=1),
        max_fires=1,
    )
    claimed = service.store.claim(clock[0])
    assert claimed is not None
    assert await service.runner.execute(claimed) == "sent"
    assert courier.sent[0].startswith("tombé à 9.90")
    assert "<https://shop.test/p>" in courier.sent[0]
    database.close()


async def test_web_budget_postpones_a_fetch(tmp_path: Path) -> None:
    clock = [datetime(2026, 10, 11, 8, 0, tzinfo=UTC)]
    calls = {"n": 0}

    async def fetch(_url: str) -> str:
        calls["n"] += 1
        return "1 €"

    service, database, _courier = _open(tmp_path, clock, fetcher=fetch)
    service.store.create(
        owner_id=7,
        guild_id=None,
        channel_ids=(),
        deliver="dm",
        title="Veille",
        trigger={"type": "interval", "every_s": 3600},
        condition=None,
        action={"type": "fetch_then", "url": "https://shop.test", "text": "vu"},
        now=clock[0] - timedelta(hours=2),
    )
    for _ in range(40):
        database.execute(
            """
            INSERT INTO objective_fetches (at, objective_id, budget_key)
            VALUES (?, 1, 'user:7')
            """,
            (clock[0].isoformat(),),
        )
    claimed = service.store.claim(clock[0])
    assert claimed is not None
    assert await service.runner.execute(claimed) == "budget"
    assert calls["n"] == 0
    database.close()


async def test_tools_create_pause_and_list(tmp_path: Path) -> None:
    clock = [datetime(2026, 10, 11, 8, 0, tzinfo=UTC)]
    service, database, _courier = _open(tmp_path, clock)
    registry_caps = objective_capabilities(service)
    registry = CapabilityRegistry()
    for capability in registry_caps:
        registry.register(capability)
    settings = Settings.for_tests(tmp_path)
    context = Context(
        user_id=7,
        guild_id=5,
        channel_id=3,
        message_id=9,
        is_owner=False,
        is_moderator=False,
        text="",
    )
    created = await invoke(
        registry,
        settings,
        context,
        ToolCall(
            id="1",
            name="objective_create",
            arguments={
                "title": "Sport",
                "trigger_type": "weekly",
                "weekdays": "lundi,jeudi",
                "time": "18h30",
                "action_type": "remind",
                "text": "séance",
            },
        ),
    )
    assert created.ok is True
    paused = await invoke(
        registry,
        settings,
        context,
        ToolCall(
            id="2", name="objective_update", arguments={"id": created.data["id"], "op": "pause"}
        ),
    )
    assert paused.data["status"] == "paused"
    listed = await invoke(
        registry, settings, context, ToolCall(id="3", name="objective_list", arguments={})
    )
    assert listed.data["objectives"][0]["when"].startswith("chaque")
    database.close()
