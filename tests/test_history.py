"""L'historique oublie le trop vieux, résume le trop long, et une édition se remplace."""

from datetime import UTC, datetime, timedelta

from maria_core.llm.history import SUMMARY_PREFIX, ChannelHistory, HistoryEntry, estimate_tokens

_NOON = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)


def _entry(
    content: str,
    *,
    message_id: int,
    hour: int = 12,
    minutes: int = 0,
    images: tuple[str, ...] = (),
) -> HistoryEntry:
    return HistoryEntry(
        role="user",
        content=content,
        created_at=datetime(2026, 10, 11, hour, minutes, tzinfo=UTC),
        message_id=message_id,
        name="Léa",
        images=images,
    )


def _reply(content: str, reply_to: int) -> HistoryEntry:
    return HistoryEntry(
        role="assistant",
        content=content,
        created_at=_NOON,
        name="MARIA",
        reply_to=reply_to,
    )


def _history(max_messages: int = 10) -> ChannelHistory:
    return ChannelHistory(
        max_messages=max_messages,
        max_tokens=10_000,
        max_age=timedelta(days=1),
        clock=lambda: _NOON,
    )


def test_expired_messages_are_dropped_without_summary() -> None:
    clock = datetime(2026, 10, 11, 14, 0, tzinfo=UTC)
    history = ChannelHistory(
        max_messages=10,
        max_tokens=10_000,
        max_age=timedelta(hours=1),
        clock=lambda: clock,
    )
    history.add(_entry("ancien", message_id=1))
    history.add(_entry("récent", message_id=2, hour=13, minutes=30))
    assert len(history) == 1
    assert history.summary == ""
    assert history.api_messages()[-1]["content"] == "récent"


def test_overflow_is_summarized_as_context_not_instruction() -> None:
    history = _history(max_messages=2)
    for index in range(3):
        history.add(_entry(f"message {index}", message_id=index))
    assert len(history) == 2
    assert "message 0" in history.summary
    messages = history.api_messages()
    assert messages[0]["role"] == "user"
    assert messages[0]["content"].startswith(SUMMARY_PREFIX)
    assert all(item["role"] != "system" for item in messages)
    assert [item["content"] for item in messages[1:]] == ["message 1", "message 2"]

    long_text = "x" * 40
    bounded = ChannelHistory(
        max_messages=10,
        max_tokens=estimate_tokens(long_text),
        max_age=timedelta(days=1),
        clock=lambda: _NOON,
    )
    bounded.add(_entry(long_text, message_id=1))
    bounded.add(_entry(long_text, message_id=2))
    assert len(bounded) == 1


def test_only_recent_entries_carry_images() -> None:
    history = _history()
    for index in range(6):
        history.add(_entry(f"photo {index}", message_id=index, images=("https://x/y.png",)))
    messages = history.api_messages()
    assert [isinstance(item["content"], list) for item in messages] == [
        False,
        False,
        True,
        True,
        True,
        True,
    ]


def test_edit_replaces_in_place_and_drops_only_its_reply() -> None:
    history = _history()
    history.add(_entry("première version", message_id=4))
    history.add(_reply("réponse à 4", reply_to=4))
    history.add(_entry("autre sujet", message_id=5))
    history.add(_reply("réponse à 5", reply_to=5))
    assert history.replace(4, _entry("corrigé", message_id=4))
    assert [item["content"] for item in history.api_messages()] == [
        "corrigé",
        "autre sujet",
        "réponse à 5",
    ]
    assert history.replace(99, _entry("inconnu", message_id=99)) is False
    assert history.contains(4)
    assert not history.contains(99)
