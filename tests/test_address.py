"""Le prénom en bord de phrase est une adresse. Une liste de prénoms ne l'est pas."""

from maria_core.conversation.address import middle_is_address, name_hit_kind


def _route(content: str, name: str = "Maria") -> str:
    kind = name_hit_kind(content, name)
    if kind == "edge":
        return "edge"
    if kind == "middle" and middle_is_address(content):
        return "middle_address"
    return kind


def test_edge_is_an_address() -> None:
    for text in (
        "Maria ?",
        "Maria tu penses quoi",
        "Maria devrait venir",
        "t'en penses quoi Maria",
        "hey Maria",
        "Maria.",
    ):
        assert _route(text) == "edge", text


def test_middle_question_addresses_the_bot() -> None:
    assert _route("au fait Maria c'est quoi le TCP") == "middle_address"
    assert _route("dis Maria c'est quoi X") == "edge"


def test_a_name_list_is_not_an_address() -> None:
    assert _route("Maria et Bob") == "list"
    assert _route("Maria, Léa") == "list"
    assert _route("faut que Maria fasse ça") == "middle"
