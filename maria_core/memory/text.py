"""Comparaison stable des souvenirs, sans appel au modèle."""

import re

_TOKEN = re.compile(r"\w+", re.UNICODE)
_IDENTITY = re.compile(
    r"\b(habite|habitant|ville|adresse|vit (?:à|a|en|au)|demeure|anniv\w*|naissance|née?|"
    r"âge|ans|prénom|s'appelle|travaille|boulot|métier|études?|étudie|coloc|en couple|"
    r"copine|copain|conjoint|gaucher|droitier)\b",
    re.IGNORECASE,
)
_EXPLICIT = re.compile(
    "\\b(?:retiens(?:\\s+que)?|souviens-toi(?:\\s+que)?|n['\u2019]oublie pas que|remember that)\\b",
    re.IGNORECASE,
)
_SAME = 0.85
_STOP = frozenset(
    {
        "le",
        "la",
        "les",
        "un",
        "une",
        "des",
        "de",
        "du",
        "et",
        "ou",
        "a",
        "à",
        "au",
        "aux",
        "en",
        "est",
        "que",
        "qui",
        "quoi",
        "il",
        "elle",
        "je",
        "tu",
        "on",
        "nous",
        "vous",
        "ils",
        "elles",
        "ce",
        "ça",
        "sa",
        "son",
        "ses",
        "mon",
        "ma",
        "mes",
        "ton",
        "ta",
        "tes",
        "pour",
        "pas",
        "ne",
        "se",
        "sur",
        "dans",
        "avec",
        "par",
        "plus",
        "the",
        "and",
        "is",
        "j",
        "l",
        "d",
        "t",
        "c",
        "qu",
        "s",
        "m",
        "n",
        "y",
    }
)
_FIRST_PERSON = re.compile(
    r"\b(?:je suis|j['\u2019]aime|j['\u2019]adore|je déteste|j['\u2019]habite|je vis"
    r"|je m['\u2019]appelle|je travaille|je bosse|je joue|je fais|mon |ma |mes )",
    re.IGNORECASE,
)
_SECOND_PERSON = (
    (r"\bje suis\b", "tu es"),
    (r"\bj['\u2019]ai\b", "tu as"),
    (r"\bj['\u2019]aime\b", "tu aimes"),
    (r"\bj['\u2019]adore\b", "tu adores"),
    (r"\bje déteste\b", "tu détestes"),
    (r"\bj['\u2019]habite\b", "tu habites"),
    (r"\bje vis\b", "tu vis"),
    (r"\bje m['\u2019]appelle\b", "tu t'appelles"),
    (r"\bje travaille\b", "tu travailles"),
    (r"\bje bosse\b", "tu bosses"),
    (r"\bje joue\b", "tu joues"),
    (r"\bje fais\b", "tu fais"),
    (r"\bje\b", "tu"),
    (r"\bmoi\b", "toi"),
    (r"\bmon\b", "ton"),
    (r"\bma\b", "ta"),
    (r"\bmes\b", "tes"),
)
_THIRD_PERSON = re.compile(r"^\s*(?:que\s+)?(?:il|elle|iel|[A-ZÀ-Ý][\w-]+)\s", re.UNICODE)


def normalize(text: str) -> str:
    return " ".join((text or "").casefold().split())


def tokens(text: str) -> set[str]:
    return {token.casefold() for token in _TOKEN.findall(text or "")}


def content_tokens(text: str) -> set[str]:
    return {token for token in tokens(text) if token not in _STOP and len(token) > 1}


def overlap(left: str, right: str) -> float:
    first, second = content_tokens(left), content_tokens(right)
    if not first or not second:
        return 0.0
    return len(first & second) / len(first | second)


def close(left: str, right: str) -> bool:
    """Même fait reformulé. « j'aime le foot » et « j'aime le rugby » restent deux faits."""
    if normalize(left) == normalize(right):
        return True
    first, second = content_tokens(left), content_tokens(right)
    if len(first) < 3 or len(second) < 3:
        return False
    return overlap(left, right) >= _SAME


def proposal_fact(text: str) -> str:
    """Une phrase courte à la première personne. Le reste du tchat n'est pas un souvenir."""
    cleaned = " ".join((text or "").split())
    if not 12 <= len(cleaned) <= 160 or _FIRST_PERSON.search(cleaned) is None:
        return ""
    if cleaned.endswith("?"):
        return ""
    return cleaned.strip(" .")


def explicit_fact(text: str) -> str:
    """Le fait demandé explicitement, ou une chaîne vide."""
    match = _EXPLICIT.search(text or "")
    if match is None:
        return ""
    return (text or "")[match.end() :].strip(" .,:;!?")


def about_someone_else(fact: str) -> bool:
    """« retiens que Paul est végétarien » ne parle pas de l'auteur."""
    return _FIRST_PERSON.search(fact) is None and _THIRD_PERSON.match(fact) is not None


def second_person(fact: str) -> str:
    """« je suis végétarien » devient « tu es végétarien », pour le demander à la personne."""
    out = fact
    for pattern, replacement in _SECOND_PERSON:
        out = re.sub(pattern, replacement, out, flags=re.IGNORECASE)
    return out


def match_query(text: str) -> str:
    words = sorted(content_tokens(text))[:12]
    if not words:
        return ""
    return " OR ".join(f'"{word}"' for word in words)


def identity_fact(content: str) -> bool:
    """Ville, âge, métier, couple… : ce qui doit rester dans le profil, comme dans MARIA_R."""
    return bool(_IDENTITY.search(content or ""))
