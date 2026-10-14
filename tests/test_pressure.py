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


def _admit(
    pressure: Pressure, *, limit: str, followup: bool, author: int = 4, room: int = 40
) -> bool:
    return pressure.admit(
        7, 3, author_messages=author, channel_messages=room, limit=limit, followup=followup
    )


def test_no_limit_by_default_and_follow_ups_are_the_only_ones_held_back() -> None:
    pressure = Pressure()
    assert all(_admit(pressure, limit="none", followup=False, author=1) for _ in range(50))
    # un suivi : au plus la moitié de ce que la personne écrit (4 messages -> 2 suivis)
    assert [_admit(pressure, limit="none", followup=True) for _ in range(3)] == [True, True, False]


def test_a_server_can_choose_to_limit_everyone() -> None:
    normal = Pressure()
    assert [_admit(normal, limit="normal", followup=False) for _ in range(5)] == [True] * 4 + [
        False
    ]
    strict = Pressure()
    assert [_admit(strict, limit="strict", followup=False) for _ in range(3)] == [True, True, False]


def test_follow_ups_and_calls_do_not_eat_each_others_quota() -> None:
    pressure = Pressure()
    assert _admit(pressure, limit="normal", followup=True)
    assert all(_admit(pressure, limit="normal", followup=False, author=3) for _ in range(3))
