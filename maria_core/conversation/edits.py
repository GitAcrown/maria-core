"""Une correction d'orthographe n'est pas une nouvelle question : MARIA ne refait pas sa réponse."""

import re
import unicodedata
from difflib import SequenceMatcher

_SIMILAR_CHARS = 0.88  # ressemblance minimale des deux textes, une fois nettoyés
_SIMILAR_WORD = 0.6  # un mot corrigé ressemble encore à l'ancien
_SHORT = 3  # un petit mot ajouté ou retiré (« a », « de », « le ») ne change pas le sens


def _words(text: str) -> list[str]:
    plain = unicodedata.normalize("NFKD", (text or "").casefold())
    plain = "".join(char for char in plain if not unicodedata.combining(char))
    return re.sub(r"[^\w\s]|_", " ", plain).split()


def is_minor_edit(old: str, new: str) -> bool:
    """Accents, majuscules, ponctuation, une faute de frappe : même demande qu'avant.

    Un chiffre qui change, un mot qui devient un autre, une phrase qui s'allonge : demande
    nouvelle, donc nouvelle réponse.
    """
    before, after = _words(old), _words(new)
    if before == after:
        return True
    if re.findall(r"\d+", " ".join(before)) != re.findall(r"\d+", " ".join(after)):
        return False
    if SequenceMatcher(None, " ".join(before), " ".join(after)).ratio() < _SIMILAR_CHARS:
        return False
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, before, after, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        if tag == "replace" and not _close(before[i1:i2], after[j1:j2]):
            return False
        if tag in {"insert", "delete"} and any(
            len(word) > _SHORT for word in before[i1:i2] + after[j1:j2]
        ):
            return False
    return True


def _close(old: list[str], new: list[str]) -> bool:
    """Les mots remplacés se ressemblent deux à deux (une faute corrigée, pas un autre mot)."""
    if len(old) != len(new):
        return False
    return all(
        SequenceMatcher(None, a, b).ratio() >= _SIMILAR_WORD or max(len(a), len(b)) <= _SHORT
        for a, b in zip(old, new, strict=True)
    )
