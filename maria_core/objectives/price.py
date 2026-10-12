"""Prix lu dans une page : candidats notés selon le contexte, ancre gardée entre deux passages.

Adapté de MARIA_R (`common/task_watch.py`).
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

_PRICE = re.compile(
    r"(?:€\s*)(\d{1,3}(?:[ \u202f\u00a0.]\d{3})*(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)"
    r"|(\d{1,3}(?:[ \u202f\u00a0.]\d{3})*(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)\s*"
    r"(?:€|eur\b|euros?\b)",
    re.IGNORECASE,
)
_GOOD = (
    "prix",
    "price",
    "à partir de",
    "a partir de",
    "seulement",
    "maintenant",
    "offre",
    "promo",
    "ajouter au panier",
    "add to cart",
    "acheter",
    "buy",
)
_BAD = (
    "livraison",
    "frais",
    "port",
    "shipping",
    "expédition",
    "expedition",
    "économisez",
    "economisez",
    "remise de",
    "save ",
    "mensualité",
    "par mois",
    "/mois",
    "x fois",
    "paiement en",
    "garantie",
    "abonnement",
)


@dataclass(frozen=True, slots=True)
class Candidate:
    value: float
    score: int
    position: int
    snippet: str
    anchor: str


def candidates(text: str, anchor: str = "") -> list[Candidate]:
    """Montants en euros, le plus plausible d'abord. L'ancre connue l'emporte."""
    source = text or ""
    wanted = " ".join((anchor or "").casefold().split())
    found: list[Candidate] = []
    for index, match in enumerate(_PRICE.finditer(source)):
        value = to_float(match.group(1) or match.group(2) or "")
        if value is None or value <= 0 or value > 1_000_000:
            continue
        found.append(_candidate(source, match, index, value, wanted))
    found.sort(key=lambda item: (-item.score, item.position))
    return found


def extract_price(text: str, anchor: str = "") -> float | None:
    found = candidates(text, anchor)
    return found[0].value if found else None


def ambiguous(found: list[Candidate]) -> list[Candidate]:
    """Montants distincts au coude à coude : un juge tranche."""
    distinct: list[Candidate] = []
    for item in found:
        if all(abs(item.value - other.value) > 0.001 for other in distinct):
            distinct.append(item)
    if len(distinct) > 1 and distinct[0].score - distinct[1].score < 2:
        return distinct[:4]
    return []


def to_float(raw: str) -> float | None:
    text = (raw or "").strip().replace("\u202f", "").replace("\u00a0", "").replace(" ", "")
    if not text:
        return None
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")
    elif text.count(".") > 1 or (text.count(".") == 1 and len(text.split(".")[-1]) == 3):
        text = text.replace(".", "")
    try:
        return float(text)
    except ValueError:
        return None


def price_holds(condition: Mapping[str, Any], price: float | None, previous: float | None) -> bool:
    kind = str(condition.get("type") or "")
    if price is None:
        return False
    threshold = _number(condition.get("threshold"))
    if kind == "price_below":
        return threshold is not None and price < threshold
    if kind == "price_above":
        return threshold is not None and price > threshold
    if previous is None or previous <= 0:
        return False
    if kind == "price_drop":
        percent = _number(condition.get("percent")) or 0.0
        return (previous - price) / previous * 100 >= percent
    if kind == "price_lower":
        return price < previous - (threshold or 0.0)
    if kind == "price_higher":
        return price > previous + (threshold or 0.0)
    return False


def _candidate(
    source: str, match: re.Match[str], index: int, value: float, wanted: str
) -> Candidate:
    around = source[max(0, match.start() - 24) : match.end() + 18].casefold()
    score = 0
    if any(word in around for word in _GOOD):
        score += 2
    if any(word in around for word in _BAD):
        score -= 3
    if value < 1:
        score -= 2
    before = " ".join(source[max(0, match.start() - 40) : match.start()].casefold().split())
    if wanted and wanted in before:
        score += 5
    snippet = " ".join(source[max(0, match.start() - 40) : match.end() + 18].split())
    anchor = " ".join(
        re.split(r"[€\d]", source[max(0, match.start() - 18) : match.start()])[-1].split()
    )
    return Candidate(value, score, index, snippet, anchor)


def _number(raw: object) -> float | None:
    if isinstance(raw, bool) or not isinstance(raw, int | float | str):
        return None
    try:
        return float(raw)
    except ValueError:
        return None
