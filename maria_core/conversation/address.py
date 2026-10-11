"""Repère si un message cite le prénom du bot.

Adapté de MARIA_R (`common/greedy_address.py`) : premier ou dernier mot,
sauf une liste de prénoms. Au milieu, seulement une question ou un tutoiement.
"""

import re

_CUSTOM_EMOJI_RE = re.compile(r"<a?:\w+:\d+>")
_UNICODE_EMOJI_RE = re.compile(
    "[\U0001f1e6-\U0001f1ff]{2}|[#*0-9]\ufe0f?\u20e3|[\U0001f300-\U0001faff\u2600-\u27bf]\ufe0f?"
)
_WORD_RE = re.compile(r"[a-z0-9àâäéèêëïîôùûüçœæ_]+", re.IGNORECASE)
_GREETINGS = frozenset(
    {
        "hey",
        "hé",
        "he",
        "ey",
        "yo",
        "salut",
        "coucou",
        "bonjour",
        "bonsoir",
        "hello",
        "hi",
        "dis",
        "oh",
        "ohé",
        "eh",
        "ok",
        "okay",
    }
)
_LIST_TAIL_RE = re.compile(
    r"(?:\s*(?:,|et|ou|&|avec)\s+[a-zàâäéèêëïîôùûüçœæ][\w'-]*)+\s*",
    re.IGNORECASE,
)
_QUESTION_RE = re.compile(
    r"[?\uff1f]|\b(?:quoi|comment|pourquoi|quel|quelle|quels|quelles)\b|\best-ce\b",
    re.IGNORECASE,
)
_PRONOUN_RE = re.compile(r"\b(?:tu|toi|te|vous)\b|\bt['\u2019]", re.IGNORECASE)


def name_hit_kind(content: str, bot_name: str) -> str:
    """`absent`, `list`, `edge` ou `middle`."""
    name = (bot_name or "").strip().lower()
    if not name:
        return "absent"
    text = _normalize(content)
    if not text or _name_at(text, name) is None:
        return "absent"
    body = _strip_leading_greetings(text)
    name_tokens = _words(name)
    tokens = _words(body)
    if not name_tokens or not tokens:
        return "absent"
    at_start = tokens[: len(name_tokens)] == name_tokens
    at_end = tokens[-len(name_tokens) :] == name_tokens
    if at_start and _tail_is_name_list(body, name):
        return "list"
    if at_start or at_end:
        return "edge"
    return "middle"


def is_question(content: str) -> bool:
    return _QUESTION_RE.search(content or "") is not None


def middle_is_address(content: str) -> bool:
    text = content or ""
    return is_question(text) or _PRONOUN_RE.search(text) is not None


def _normalize(content: str) -> str:
    without_custom = _CUSTOM_EMOJI_RE.sub(" ", content or "")
    without_emoji = _UNICODE_EMOJI_RE.sub(" ", without_custom)
    return re.sub(r"\s+", " ", without_emoji).lower().strip()


def _words(text: str) -> list[str]:
    return [match.group(0).lower() for match in _WORD_RE.finditer(text or "")]


def _strip_leading_greetings(text: str) -> str:
    parts = (text or "").split()
    index = 0
    while index < len(parts):
        word = _words(parts[index])
        if len(word) != 1 or word[0] not in _GREETINGS:
            break
        index += 1
    return " ".join(parts[index:])


def _name_at(text: str, name: str) -> re.Match[str] | None:
    return re.search(
        rf"(?<![a-z0-9_]){re.escape(name)}(?![a-z0-9_])",
        text,
        flags=re.IGNORECASE,
    )


def _tail_is_name_list(body: str, name: str) -> bool:
    """« Maria et Bob » est une liste. « Maria, tu viens » ne l'est pas."""
    match = re.match(rf"{re.escape(name)}(?![a-z0-9_])", body, flags=re.IGNORECASE)
    if match is None:
        return False
    tail = body[match.end() :]
    if not tail.strip():
        return False
    return _LIST_TAIL_RE.fullmatch(tail) is not None
