"""Faut-il répondre ? Uniquement des règles, pas de modèle."""

from maria_core.conversation.address import middle_is_address, name_hit_kind
from maria_core.conversation.model import Action, Inbound, Policy, ReplyMode, Route


def decide(message: Inbound, policy: Policy) -> Route:
    if message.author_is_bot:
        return _bot(message)
    if message.is_dm:
        return Route(Action.IGNORE, "dm")
    if policy.mode is ReplyMode.OFF:
        return Route(Action.STORE, "off")
    if message.reply_to_bot:
        return Route(Action.RESPOND, "reply")
    if message.mentioned:
        return Route(Action.RESPOND, "mention")
    if message.mention_everyone and policy.respond_everyone:
        return Route(Action.RESPOND, "everyone")
    called = _called_by_name(message.text, message.bot_names)
    if called is not None:
        return called
    if policy.mode is ReplyMode.GREEDY:
        return _greedy(message.text, message.bot_names)
    return Route(Action.STORE, "not_addressed")


def _bot(message: Inbound) -> Route:
    if message.is_dm:
        return Route(Action.IGNORE, "other_bot")
    return Route(Action.STORE, "other_bot")


def _called_by_name(text: str, names: tuple[str, ...]) -> Route | None:
    """« maria ? » ou « hey maria » s'adresse à elle, même en mode strict."""
    for name in names:
        if name_hit_kind(text, name) == "edge":
            return Route(Action.RESPOND, "name_edge")
    return None


def _greedy(text: str, names: tuple[str, ...]) -> Route:
    ambiguous: Route | None = None
    saw_list = False
    for name in names:
        route = _one_name(text, name)
        if route is None:
            continue
        if route.decision is not None:
            ambiguous = route
            continue
        if route.reason == "name_list":
            saw_list = True
            continue
        return route
    if ambiguous is not None:
        return ambiguous
    if saw_list:
        return Route(Action.STORE, "name_list")
    return Route(Action.STORE, "not_addressed")


def _one_name(text: str, name: str) -> Route | None:
    kind = name_hit_kind(text, name)
    if kind == "absent":
        return None
    if kind == "edge":
        return Route(Action.RESPOND, "name_edge")
    if kind == "list":
        return Route(Action.STORE, "name_list")
    if middle_is_address(text):
        return Route(Action.RESPOND, "name_middle")
    return Route(
        Action.STORE,
        "name_ambiguous",
        decision="addressed_to_bot",
        detail=name,
    )
