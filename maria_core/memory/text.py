"""Comparaison stable des souvenirs, sans appel au modèle."""

import re

_TOKEN = re.compile(r"\w+", re.UNICODE)
_EXPLICIT = re.compile(
    "\\b(?:retiens(?:\\s+que)?|souviens-toi(?:\\s+que)?|n['\u2019]oublie pas que|remember that)\\b",
    re.IGNORECASE,
)
_OVERLAP = 0.6


def normalize(text: str) -> str:
    return " ".join((text or "").casefold().split())


def tokens(text: str) -> set[str]:
    return {token.casefold() for token in _TOKEN.findall(text or "")}


def overlap(left: str, right: str) -> float:
    first, second = tokens(left), tokens(right)
    if not first or not second:
        return 0.0
    return len(first & second) / len(first | second)


def close(left: str, right: str) -> bool:
    if normalize(left) == normalize(right):
        return True
    return overlap(left, right) >= _OVERLAP


_FACT = re.compile(
    "\\b(?:je suis|j'aime|j'habite|je m'appelle|mon |ma |mes )\\b",
    re.IGNORECASE,
)


def proposal_fact(text: str) -> str:
    """Une phrase courte à la première personne. Le reste du tchat n'est pas un souvenir."""
    cleaned = " ".join((text or "").split())
    if not 12 <= len(cleaned) <= 160 or _FACT.search(cleaned) is None:
        return ""
    return cleaned.strip(" .")


def explicit_fact(text: str) -> str:
    """Le fait demandé explicitement, ou une chaîne vide."""
    match = _EXPLICIT.search(text or "")
    if match is None:
        return ""
    return (text or "")[match.end() :].strip(" .,:;!?")


def match_query(text: str) -> str:
    words = list(tokens(text))[:12]
    if not words:
        return ""
    return " OR ".join(f'"{word}"' for word in words)
