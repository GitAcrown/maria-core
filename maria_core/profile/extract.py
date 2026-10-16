"""Repère les champs du profil dits clairement par la personne. Des règles, pas de modèle."""

import re

from maria_core.profile.birthday import normalize

_PLACE = r"([A-Z][\w'-]*(?:[ -][A-Z][\w'-]*){0,2})"
_DATE = (
    r"(\d{1,2}\s*[/.-]\s*\d{1,2}(?:\s*[/.-]\s*\d{2,4})?"
    r"|\d{1,2}\s*(?:er)?\s+(?i:janvier|février|fevrier|mars|avril|mai|juin|juillet|août|aout"
    r"|septembre|octobre|novembre|décembre|decembre)(?:\s+\d{4})?)"
)
_CITY = re.compile(
    r"\b(?:j'habite|je vis|j'ai emm[eé]nag[eé]|je suis install[eé]e?)"
    r"\s+(?:à|a|en|au|aux|dans le|pr[eè]s de|vers)?\s*" + _PLACE
)
_TEAM = re.compile(
    r"\b(?:je supporte|je suis supporte(?:u)?r (?:de|du|des|d')|"
    r"mon (?:équipe|club)(?: de foot)?(?: pr[eé]f[eé]r[eé]e?)? c'est)"
    r"\s*(?:l'|le |la |les )?\s*" + _PLACE
)
_BIRTHDAY = re.compile(
    r"\b(?i:mon anniv(?:ersaire)?(?: c'est| est)(?: le)?|je suis n[ée]e? le"
    r"|je f[êe]te mon anniversaire le)\s*" + _DATE
)
_MEMORY_CITY = re.compile(
    r"\b(?i:tu (?:habites|vis)|le membre (?:habite|vit)|la membre (?:habite|vit))"
    r"\s+(?i:à|a|en|au|aux|dans le|près de|pres de)\s*" + _PLACE
)
_MEMORY_TEAM = re.compile(
    r"\b(?i:tu supportes|le membre supporte|tu es supporte(?:u)?r|le membre est supporte(?:u)?r)"
    r"\s*(?i:de|du|des|d')?\s*(?:l'|le |la |les )?\s*" + _PLACE
)
_MEMORY_BIRTHDAY = re.compile(
    r"(?i:\btu es n[ée]e? le|\bton anniversaire est le|(?:^|[.;]\s)anniversaire le"
    r"|^le membre\b.*?\bson anniversaire est le|^le membre est n[ée]e? le)\s*" + _DATE
)
_ALIASES = {"Paris Saint-Germain": "PSG"}

type Rules = tuple[tuple[str, re.Pattern[str]], ...]

_SAID: Rules = (("city", _CITY), ("team", _TEAM), ("birthday", _BIRTHDAY))
_REMEMBERED: Rules = (
    ("city", _MEMORY_CITY),
    ("team", _MEMORY_TEAM),
    ("birthday", _MEMORY_BIRTHDAY),
)


def extract(text: str) -> dict[str, str]:
    """Ville, équipe et anniversaire, quand la phrase est sans ambiguïté."""
    return _scan(text, _SAID)


def extract_memory(text: str) -> dict[str, str]:
    """Les mêmes champs d'un souvenir, écrit à la 2e ou 3e personne (« Tu habites à Lyon »)."""
    return _scan(text, _REMEMBERED)


def _scan(text: str, rules: Rules) -> dict[str, str]:
    plain = (text or "").replace(chr(0x2019), "'")
    found: dict[str, str] = {}
    for key, pattern in rules:
        match = pattern.search(plain)
        value = _value(key, match.group(1)) if match else ""
        if value:
            found[key] = value
    return found


def _value(key: str, raw: str) -> str:
    if key == "birthday":
        try:
            return normalize(raw)
        except ValueError:
            return ""
    name = _tidy(raw)
    return _ALIASES.get(name, name)


def _tidy(value: str) -> str:
    return value.strip(" -'.,")
