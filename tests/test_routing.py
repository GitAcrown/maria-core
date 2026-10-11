"""Matrice de routage : qui obtient une réponse, sans modèle."""

from maria_core.conversation.model import Action, Inbound, Policy, ReplyMode, Route
from maria_core.conversation.routing import decide


def _message(**overrides: object) -> Inbound:
    values: dict[str, object] = {
        "channel_id": 1,
        "message_id": 10,
        "guild_id": 5,
        "author_id": 7,
        "author_name": "Léa",
        "text": "salut",
        "is_dm": False,
        "author_is_bot": False,
        "mentioned": False,
        "reply_to_bot": False,
        "mention_everyone": False,
        "edited": False,
        "author_is_owner": False,
        "author_is_moderator": False,
        "bot_names": ("Maria",),
    }
    values.update(overrides)
    return Inbound(**values)  # type: ignore[arg-type]


def _route(message: Inbound, mode: ReplyMode = ReplyMode.STRICT, **policy: object) -> Route:
    settings = {"mode": mode, "respond_everyone": False, "auto_transcribe": False}
    settings.update(policy)
    return decide(message, Policy(**settings))  # type: ignore[arg-type]


def test_direct_messages_are_not_a_conversation() -> None:
    route = _route(_message(is_dm=True, guild_id=None), ReplyMode.OFF)
    assert route.action is Action.IGNORE
    assert route.reason == "dm"


def test_off_stores_even_a_mention() -> None:
    route = _route(_message(mentioned=True), ReplyMode.OFF)
    assert route.action is Action.STORE
    assert route.reason == "off"


def test_strict_answers_when_called_by_name() -> None:
    route = _route(_message(text="maria ?"))
    assert route.action is Action.RESPOND
    assert route.reason == "name_edge"
    about = _route(_message(text="faut que Maria fasse ça"))
    assert about.action is Action.STORE
    assert about.reason == "not_addressed"


def test_strict_answers_mention_reply_and_opt_in_everyone() -> None:
    assert _route(_message(mentioned=True)).reason == "mention"
    assert _route(_message(reply_to_bot=True)).reason == "reply"
    assert _route(_message(mention_everyone=True)).action is Action.STORE
    everyone = _route(_message(mention_everyone=True), respond_everyone=True)
    assert everyone.reason == "everyone"


def test_strict_stores_an_unaddressed_message() -> None:
    route = _route(_message())
    assert route.action is Action.STORE
    assert route.reason == "not_addressed"


def test_other_bots_are_context_in_a_guild_and_ignored_in_dm() -> None:
    guild = _route(_message(author_is_bot=True))
    assert guild.action is Action.STORE
    private = _route(_message(author_is_bot=True, is_dm=True, guild_id=None))
    assert private.action is Action.IGNORE


def test_greedy_name_rules() -> None:
    edge = _route(_message(text="hey Maria"), ReplyMode.GREEDY)
    assert edge.reason == "name_edge"
    middle = _route(_message(text="au fait Maria c'est quoi le TCP"), ReplyMode.GREEDY)
    assert middle.reason == "name_middle"
    listed = _route(_message(text="Maria et Bob"), ReplyMode.GREEDY)
    assert listed.action is Action.STORE
    assert listed.reason == "name_list"
    vague = _route(_message(text="faut que Maria fasse ça"), ReplyMode.GREEDY)
    assert vague.action is Action.STORE
    assert vague.reason == "name_ambiguous"
    assert vague.decision == "addressed_to_bot"
    absent = _route(_message(text="on se voit demain"), ReplyMode.GREEDY)
    assert absent.reason == "not_addressed"
