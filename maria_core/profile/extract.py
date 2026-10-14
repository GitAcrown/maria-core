"""Repère les champs du profil dits clairement par la personne. Des règles, pas de modèle."""

import re

_PLACE = r"([A-Z][\w'-]*(?:[ -][A-Z][\w'-]*){0,2})"
_CITY = re.compile(
    r"\b(?:j'habite|je vis|j'ai emm[eé]nag[eé]|je suis install[eé]e?)"
    r"\s+(?:à|a|en|au|aux|dans le|pr[eè]s de|vers)?\s*" + _PLACE
)
_TEAM = re.compile(
    r"\b(?:je supporte|je suis supporte(?:u)?r (?:de|du|des|d')|"
    r"mon (?:équipe|club)(?: de foot)?(?: pr[eé]f[eé]r[eé]e?)? c'est)"
    r"\s*(?:l'|le |la |les )?\s*" + _PLACE
)
_ALIASES = {"Paris Saint-Germain": "PSG"}


def extract(text: str) -> dict[str, str]:
    """Ville et équipe, quand la phrase est sans ambiguïté."""
    plain = (text or "").replace(chr(0x2019), "'")
    found: dict[str, str] = {}
    city = _CITY.search(plain)
    if city:
        found["city"] = _tidy(city.group(1))
    team = _TEAM.search(plain)
    if team:
        name = _tidy(team.group(1))
        found["team"] = _ALIASES.get(name, name)
    return found


def _tidy(value: str) -> str:
    return value.strip(" -'.,")
