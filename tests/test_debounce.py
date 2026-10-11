"""Pendant l'attente, seul le dernier message du créneau est gardé."""

import asyncio

from maria_core.conversation.debounce import Debouncer
from maria_core.conversation.model import Inbound


def _message(message_id: int) -> Inbound:
    return Inbound(
        channel_id=1,
        message_id=message_id,
        guild_id=5,
        author_id=7,
        author_name="Léa",
        text=str(message_id),
        is_dm=False,
        author_is_bot=False,
        mentioned=True,
        reply_to_bot=False,
        mention_everyone=False,
        edited=False,
        author_is_owner=False,
        author_is_moderator=False,
    )


async def test_debounce_keeps_the_latest_message() -> None:
    gate = asyncio.Event()

    async def sleep(_delay: float) -> None:
        await gate.wait()

    debouncer = Debouncer(0.33, sleep=sleep)
    first = asyncio.create_task(debouncer.submit(_message(1)))
    await asyncio.sleep(0)
    assert await debouncer.submit(_message(2)) is None
    gate.set()
    kept = await first
    assert kept is not None
    assert kept.message_id == 2
    assert len(debouncer) == 0
