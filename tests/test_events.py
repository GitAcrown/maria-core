"""Le bus isole les erreurs et respecte l'ordre de spécificité."""

import pytest

from maria_core.errors import RegistryError
from maria_core.events import EventBus


class Parent:
    pass


class Child(Parent):
    pass


async def test_handlers_run_specific_first_and_one_failure_does_not_stop_the_rest() -> None:
    bus = EventBus()
    seen: list[str] = []

    async def on_child(_event: Child) -> None:
        seen.append("child")

    async def on_parent(_event: Parent) -> None:
        seen.append("parent")
        raise RuntimeError("panne")

    async def on_parent_after(_event: Parent) -> None:
        seen.append("after")

    bus.subscribe(Child, on_child)
    bus.subscribe(Parent, on_parent)
    bus.subscribe(Parent, on_parent_after)

    failures = await bus.publish(Child())
    assert failures == 1
    assert seen == ["child", "parent", "after"]


async def test_unsubscribe_and_duplicate_subscription() -> None:
    bus = EventBus()
    seen: list[int] = []

    async def on_parent(_event: Parent) -> None:
        seen.append(1)

    bus.subscribe(Parent, on_parent)
    with pytest.raises(RegistryError, match="déjà abonné"):
        bus.subscribe(Parent, on_parent)
    bus.unsubscribe(Parent, on_parent)
    assert await bus.publish(Parent()) == 0
    assert seen == []


def test_handler_must_be_a_coroutine() -> None:
    bus = EventBus()

    def sync_handler(_event: Parent) -> None:
        return None

    with pytest.raises(RegistryError, match="coroutine"):
        bus.subscribe(Parent, sync_handler)
