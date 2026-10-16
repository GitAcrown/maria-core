"""Un message édité ne reçoit jamais deux réponses : corrigée sur place, ou remplacée."""

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from maria_core.conversation.model import Reply
from maria_core.discord.chat import ChatCog
from maria_core.llm.types import Completion
from tests.fakes import ScriptedClient
from tests.test_service import _message, _open


class _Sent:
    def __init__(self, identifier: int) -> None:
        self.id = identifier


class _Channel:
    def __init__(self, last: int) -> None:
        self.id = 3
        self.last_message_id = last
        self.sent: list[dict[str, Any]] = []
        self.edited: list[tuple[int, str]] = []
        self.deleted: list[int] = []
        self._next = 500

    async def send(self, content: str | None = None, **options: Any) -> _Sent:
        self._next += 1
        self.sent.append({"content": content, **options})
        return _Sent(self._next)

    async def fetch_message(self, identifier: int) -> Any:
        async def edit(*, content: str, **_options: Any) -> None:
            self.edited.append((identifier, content))

        return SimpleNamespace(edit=edit)

    def get_partial_message(self, identifier: int) -> Any:
        async def delete() -> None:
            self.deleted.append(identifier)

        return SimpleNamespace(delete=delete)


def _cog(channel: _Channel) -> tuple[ChatCog, list[tuple[int, ...]], Any]:
    remembered: list[tuple[int, ...]] = []
    conversation = SimpleNamespace(
        remember_reply=lambda user_id, *ids: remembered.append((user_id, *ids))
    )
    app = SimpleNamespace(conversation=conversation)
    message = SimpleNamespace(id=10, guild=SimpleNamespace(id=5), channel=channel)
    return ChatCog(None, app), remembered, message  # type: ignore[arg-type]


def _reply(*previous: int) -> Reply:
    single = previous[0] if len(previous) == 1 else None
    return Reply(
        chunks=("corrigée",),
        user_message_id=10,
        edit_message_id=single,
        reply=single is None,
        previous=previous,
    )


async def test_the_reply_is_edited_in_place_when_it_is_still_the_last_message() -> None:
    channel = _Channel(last=99)
    cog, remembered, message = _cog(channel)
    await cog._publish(message, _reply(99))
    assert channel.edited == [(99, "corrigée")] and not channel.sent and not channel.deleted
    assert remembered == []


async def test_a_reply_that_cannot_be_edited_is_replaced_not_doubled() -> None:
    channel = _Channel(last=250)  # quelqu'un a écrit depuis : on ne peut plus modifier la réponse
    cog, remembered, message = _cog(channel)
    await cog._publish(message, _reply(99))
    assert channel.deleted == [99] and len(channel.sent) == 1
    assert channel.sent[0]["content"] == "corrigée" and channel.sent[0]["reference"] is not None
    assert remembered == [(10, 501)]


async def test_every_part_of_a_long_reply_is_removed_when_the_message_is_edited() -> None:
    channel = _Channel(last=250)
    cog, remembered, message = _cog(channel)
    await cog._publish(message, _reply(99, 100, 101))
    assert channel.deleted == [99, 100, 101] and len(channel.sent) == 1
    assert remembered == [(10, 501)]


async def test_a_first_reply_has_nothing_to_remove() -> None:
    channel = _Channel(last=10)
    cog, remembered, message = _cog(channel)
    await cog._publish(message, _reply())
    assert channel.deleted == [] and len(channel.sent) == 1 and remembered == [(10, 501)]


async def test_the_service_remembers_all_parts_of_a_reply(tmp_path: Any) -> None:
    client = ScriptedClient(
        [Completion(text="première", model="fake"), Completion(text="deuxième", model="fake")]
    )
    service, database = _open(tmp_path, client)
    assert await service.handle(_message(mentioned=True, message_id=4, text="Maria"))
    service.remember_reply(4, 99, 100)
    again = await service.handle(
        _message(mentioned=True, message_id=4, text="Maria corrigée", edited=True)
    )
    assert again is not None and again.previous == (99, 100) and again.edit_message_id is None
    database.close()


async def test_an_edit_during_the_answer_waits_for_it_instead_of_answering_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []
    channel = _Channel(last=10)

    async def fake_inbound(message: Any, **_options: Any) -> Any:
        return SimpleNamespace(edited=_options["edited"])

    async def slow_handle(inbound: Any, **_options: Any) -> Any:
        order.append("début modifié" if inbound.edited else "début")
        await asyncio.sleep(0.05)
        order.append("fin modifié" if inbound.edited else "fin")
        return None

    monkeypatch.setattr("maria_core.discord.chat.inbound_from_message", fake_inbound)
    monkeypatch.setattr("maria_core.discord.chat._publish_signal", lambda *_args: None)

    async def keep(_app: Any, _message: Any, inbound: Any) -> Any:
        return inbound

    monkeypatch.setattr("maria_core.discord.chat.prepare_voice", keep)
    app = SimpleNamespace(conversation=SimpleNamespace(handle=slow_handle))
    cog = ChatCog(None, app)  # type: ignore[arg-type]
    message = SimpleNamespace(id=10, channel=channel, jump_url="")
    channel.typing = lambda: None
    first = asyncio.create_task(cog._incoming(message, edited=False))
    await asyncio.sleep(0.01)
    second = asyncio.create_task(cog._incoming(message, edited=True))
    await asyncio.gather(first, second)
    assert order == ["début", "fin", "début modifié", "fin modifié"]
