"""Prix lu dans un texte. Assez pour une veille, sans crawler dédié."""

import re

_PRICE = re.compile(r"(\d{1,6})(?:[.,](\d{1,2}))?\s*(?:€|eur)", re.I)


def extract_price(text: str) -> float | None:
    match = _PRICE.search(text or "")
    if match is None:
        return None
    fraction = (match.group(2) or "0").ljust(2, "0")
    return float(f"{match.group(1)}.{fraction}")
