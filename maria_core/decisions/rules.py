"""Règles déterministes. `None` veut dire : laisser le modèle trancher."""

import re
from collections.abc import Mapping
from typing import Any

from maria_core.conversation.address import middle_is_address, name_hit_kind
from maria_core.decisions.types import RuleHit

_YES = frozenset({"oui", "ouais", "ok", "okay", "vas-y", "go", "yes", "ouep"})
_NO = frozenset({"non", "nan", "no", "stop", "annule", "laisse"})
_WEB = re.compile(
    r"(?:cherche|recherche|google|actu|actualités?|news|derni[eè]res? nouvelles"
    r"|qui a gagné|score d[eu]|résultats? d[eu]|quand sort|est sorti|vérifie|source)",
    re.IGNORECASE,
)
_CHAT_WORDS = 4


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
    text = _text(state, "text").strip()
    if state.get("has_image") is True:
        return RuleHit("images", 1.0)
    if not text:
        return RuleHit("none", 1.0)
    if _WEB.search(text):
        return RuleHit("web", 1.0)
    if len(text.split()) <= _CHAT_WORDS and "?" not in text:
        return RuleHit("none", 1.0)
    return None


_LIVE = re.compile(
    r"\b(?:aujourd['\u2019]hui|hier|demain|ce soir|cette semaine|actuel(?:le)?(?:ment)?|"
    r"en ce moment|r[e\u00e9]cemment|prix|score|cours|m[e\u00e9]t[e\u00e9]o|r[e\u00e9]sultats?)\b",
    re.IGNORECASE,
)


_SENSITIVE = re.compile(
    r"d[e\u00e9]prim|d[e\u00e9]pression|anxi|suicid|cancer|maladi|diagnostic|handicap|"
    r"th[e\u00e9]rap|psy(?:chiatr|ch)|enceinte|grossesse|v\.?i\.?h|s[e\u00e9]ropositi|"
    r"\bgay\b|lesbienn|bisexuel|homosexuel|transgenre|\btrans\b|religi|musulman|chr[e\u00e9]tien|"
    r"\bjuif|ath[e\u00e9]e|\bvote\b|parti politique|extr[e\u00ea]me (?:droite|gauche)|\bdettes?\b|"
    r"salaire|revenus|ch[o\u00f4]mage|addict|alcooli|drogue|casier|prison|harc[e\u00e8]l|"
    r"violence|\bviol\b|abus",
    re.IGNORECASE,
)


def sensitivity_rules(state: Mapping[str, Any]) -> RuleHit | None:
    """Santé, religion, orientation, argent, justice : jamais retenu sans accord."""
    return RuleHit("sensitive", 1.0) if _SENSITIVE.search(_text(state, "text")) else None


_REQUEST = re.compile(
    r"pr[e\u00e9]vien|\bping|rappel|alert|notifi|mentionn|surveill|guett|[e\u00e9]cout[eo]|"
    r"tiens?[- ]moi au courant|dis[- ]moi (?:quand|si|d[e\u00e8]s)|fais[- ]moi signe|"
    r"pr[e\u00e9]viens|pr[e\u00e9]venir|avertis|signale[- ]moi",
    re.IGNORECASE,
)


def request_rules(state: Mapping[str, Any]) -> RuleHit | None:
    """Une demande de surveillance se reconnaît à ses mots ; trop court, ce n'en est pas une."""
    text = _text(state, "text")
    if len(text.strip()) < 8:
        return RuleHit(False, 1.0)
    return RuleHit(True, 1.0) if _REQUEST.search(text) else None


def claim_rules(state: Mapping[str, Any]) -> RuleHit | None:
    """Sans chiffre ni repère de temps, ou déjà appuyée par un outil : rien à vérifier."""
    answer = _text(state, "answer")
    if state.get("tools") or len(answer) < 25:
        return RuleHit("grounded", 1.0)
    if not re.search(r"\d", answer) and not _LIVE.search(answer):
        return RuleHit("grounded", 1.0)
    return None


def memory_worth_rules(state: Mapping[str, Any]) -> RuleHit | None:
    if len(_text(state, "text").strip()) < 12:
        return RuleHit(False, 1.0)
    return None


def followup_rules(state: Mapping[str, Any]) -> RuleHit | None:
    try:
        elapsed = float(state.get("elapsed_s") or 0)
        depth = int(state.get("depth") or 0)
    except (TypeError, ValueError):
        return None
    if state.get("same_author") is False or elapsed > 120 or depth > 3:
        return RuleHit("ignore", 1.0)
    if state.get("question") is True and depth <= 1:
        return RuleHit("respond", 1.0)
    return None


def ambient_rules(state: Mapping[str, Any]) -> RuleHit | None:
    try:
        score = float(state["score"])
    except (KeyError, TypeError, ValueError):
        return None
    if score < 0.2:
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
    if humans < 1:
        return RuleHit(False, 1.0)
    return None


def topic_rules(state: Mapping[str, Any]) -> RuleHit | None:
    if len(_text(state, "message").split()) < 3:
        return RuleHit("ignore", 1.0)
    return None


def _text(state: Mapping[str, Any], key: str) -> str:
    return str(state.get(key) or "")
