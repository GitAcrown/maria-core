"""Règles déterministes. `None` veut dire : laisser le modèle trancher."""

from collections.abc import Mapping
from typing import Any

from maria_core.conversation.address import middle_is_address, name_hit_kind
from maria_core.decisions.types import RuleHit

_YES = frozenset({"oui", "ouais", "ok", "okay", "vas-y", "go", "yes", "ouep"})
_NO = frozenset({"non", "nan", "no", "stop", "annule", "laisse"})
_GENERATE = ("résume", "resume", "cherche", "explique", "analyse")


def address_rules(state: Mapping[str, Any]) -> RuleHit | None:
    text = _text(state, "text")
    name = _text(state, "bot_name")
    kind = name_hit_kind(text, name)
    if kind == "edge" or (kind == "middle" and middle_is_address(text)):
        return RuleHit("respond", 1.0)
    if kind in {"list", "absent"}:
        return RuleHit("ignore", 1.0)
    return None


def draft_rules(state: Mapping[str, Any]) -> RuleHit | None:
    token = _text(state, "text").casefold().strip(" .!?")
    if token in _YES:
        return RuleHit("accept", 1.0)
    if token in _NO:
        return RuleHit("reject", 1.0)
    return None


def alert_rules(state: Mapping[str, Any]) -> RuleHit | None:
    text = _text(state, "instruction").strip()
    if not text:
        return RuleHit("ping_only", 1.0)
    folded = text.casefold()
    if len(text) <= 80 and not any(word in folded for word in _GENERATE):
        return RuleHit("verbatim", 1.0)
    return None


def listen_rules(state: Mapping[str, Any]) -> RuleHit | None:
    message = _text(state, "message").casefold()
    pattern = _text(state, "pattern").strip()
    if not pattern:
        return RuleHit("ignore", 1.0)
    if " " not in pattern:
        return None
    if pattern.casefold() in message:
        return RuleHit("fire", 1.0)
    return RuleHit("ignore", 1.0)


def condition_rules(state: Mapping[str, Any]) -> RuleHit | None:
    if "price" not in state or "threshold" not in state:
        return None
    try:
        price = float(state["price"])
        threshold = float(state["threshold"])
    except (TypeError, ValueError):
        return None
    op = _text(state, "op") or "lt"
    if op == "lt":
        return RuleHit(price < threshold, 1.0)
    if op == "gt":
        return RuleHit(price > threshold, 1.0)
    return None


def price_rules(state: Mapping[str, Any]) -> RuleHit | None:
    scores = state.get("scores")
    if not isinstance(scores, list) or not scores:
        return None
    try:
        numbers = [float(item) for item in scores]
    except (TypeError, ValueError):
        return None
    if len(numbers) == 1:
        return RuleHit("0", 1.0)
    ordered = sorted(numbers, reverse=True)
    if ordered[0] - ordered[1] >= 2:
        return RuleHit(str(numbers.index(ordered[0])), 1.0)
    return None


def intent_rules(state: Mapping[str, Any]) -> RuleHit | None:
    if state.get("has_image") is True:
        return RuleHit("images", 1.0)
    if not _text(state, "text").strip():
        return RuleHit("none", 1.0)
    return None


def memory_worth_rules(state: Mapping[str, Any]) -> RuleHit | None:
    if len(_text(state, "text").strip()) < 12:
        return RuleHit(False, 1.0)
    return None


def memory_relevance_rules(state: Mapping[str, Any]) -> RuleHit | None:
    if "distance" not in state:
        return None
    try:
        distance = float(state["distance"])
    except (TypeError, ValueError):
        return None
    if distance <= 0.2:
        return RuleHit(True, 1.0)
    if distance >= 0.42:
        return RuleHit(False, 1.0)
    return None


def followup_rules(state: Mapping[str, Any]) -> RuleHit | None:
    try:
        elapsed = float(state.get("elapsed_s") or 0)
        depth = int(state.get("depth") or 0)
    except (TypeError, ValueError):
        return None
    if state.get("same_author") is False or elapsed > 20 or depth > 2:
        return RuleHit("ignore", 1.0)
    return None


def ambient_rules(state: Mapping[str, Any]) -> RuleHit | None:
    try:
        score = float(state["score"])
    except (KeyError, TypeError, ValueError):
        return None
    if score < 0.4:
        return RuleHit(False, 1.0)
    return None


def reaction_rules(state: Mapping[str, Any]) -> RuleHit | None:
    options = state.get("options")
    if isinstance(options, list) and len(options) == 1:
        return RuleHit("0", 1.0)
    return None


def join_rules(state: Mapping[str, Any]) -> RuleHit | None:
    if state.get("already") is True:
        return RuleHit(False, 1.0)
    try:
        humans = int(state.get("humans") or 0)
    except (TypeError, ValueError):
        return None
    if humans < 2:
        return RuleHit(False, 1.0)
    return None


def _text(state: Mapping[str, Any], key: str) -> str:
    return str(state.get(key) or "")
