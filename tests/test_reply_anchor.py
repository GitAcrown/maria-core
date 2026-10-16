"""Reply seulement si d'autres ont écrit ; la ligne d'attente de MARIA ne compte pas."""

from types import SimpleNamespace
from typing import Any

from maria_core.conversation.model import Reply
from maria_core.discord.chat import reply_anchor


def _message(last: int) -> Any:
    return SimpleNamespace(
        id=10, guild=SimpleNamespace(id=5), channel=SimpleNamespace(id=3, last_message_id=last)
    )


def _reply(*, reply: bool = True) -> Reply:
    return Reply(chunks=("ok",), user_message_id=10, edit_message_id=None, reply=reply)


def test_a_reply_only_when_someone_wrote_after_the_question() -> None:
    assert reply_anchor(_message(last=10), _reply(), set()) is None
    anchor = reply_anchor(_message(last=11), _reply(), set())
    assert anchor is not None and anchor.message_id == 10


def test_her_own_waiting_line_is_not_taken_for_another_message() -> None:
    # le message d'attente (id 900) est le dernier du salon : sans lui, personne n'a écrit
    assert reply_anchor(_message(last=900), _reply(), {900}) is None
    assert reply_anchor(_message(last=901), _reply(), {900}) is not None


def test_no_anchor_when_the_reply_was_not_asked_to_be_one() -> None:
    assert reply_anchor(_message(last=11), _reply(reply=False), set()) is None
