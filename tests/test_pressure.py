"""Les réponses suivent le nombre de messages du salon."""

from maria_core.conversation.pressure import Pressure
from maria_core.social.levels import room_budget


def test_a_person_can_be_answered_once_per_message_they_sent() -> None:
    pressure = Pressure()
    assert pressure.allow(7, 3, author_pace=40, channel_pace=200) is True
    assert all(pressure.allow(7, 3, author_pace=40, channel_pace=200) for _ in range(39))
    assert pressure.allow(7, 3, author_pace=40, channel_pace=200) is False
    assert pressure.allow(8, 3, author_pace=10, channel_pace=200) is True


def test_a_direct_message_without_a_room_is_not_capped() -> None:
    pressure = Pressure()
    assert all(pressure.allow(7, 1, author_pace=0, channel_pace=0) for _ in range(30))


def test_the_reaction_budget_grows_with_the_room() -> None:
    assert room_budget(3, 1) == 3
    assert room_budget(3, 10) == 30
    assert room_budget(0, 10) == 0
