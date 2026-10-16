"""Repère une demande de calcul ou de conversion : l'outil `calculate` est alors imposé."""

import re

HINT = (
    "[CALCUL] Cette demande contient un calcul ou une conversion : appelle l'outil calculate, "
    "ne calcule jamais de tête, puis réponds avec son résultat."
)
_TIMES = chr(0xD7) + chr(0xF7)  # signes multiplier et diviser
_OPERATION = re.compile(rf"\d\s*(?:[-+*/{_TIMES}^]|\bx\b)\s*\d|\d\s*(?:%|pour ?cent)")
_UNITS = (
    r"miles?|km|kilom[èe]tres?|pieds?|pouces?|livres?|kilos?|grammes?|litres?|fahrenheit"
    r"|celsius|degr[ée]s|m/s|km/h|mph|octets?|mo|go"
)
_REQUEST = re.compile(
    r"\b(?:calcule[rz]?|convertis(?:sez)?|convertir|conversion"
    r"|combien (?:font|fait|ça fait|cela fait)|racine carr[ée]e|pourcentage|moyenne de"
    rf"|en (?:{_UNITS}))\b",
    re.IGNORECASE,
)
_CURRENCY = re.compile(
    r"€|\$|\b(?:euros?|dollars?|livres? sterling|yens?|francs?|devises?|cours|bitcoin|btc)\b",
    re.IGNORECASE,
)
_DATE = re.compile(
    r"\b\d{1,2}\s*[/-]\s*\d{1,2}(?:\s*[/-]\s*\d{2,4})?\b|\b\d{1,2}\s*[hH]\s*\d{0,2}\b"
)


def needs_calculation(text: str) -> bool:
    """Un chiffre à calculer ou à convertir, hors devises (le cours se cherche sur le web)."""
    plain = (text or "").replace(chr(0x2019), "'")
    if not any(char.isdigit() for char in plain) or _CURRENCY.search(plain):
        return False
    stripped = _DATE.sub(" ", plain)
    return bool(_OPERATION.search(stripped) or _REQUEST.search(stripped))
