"""Halloween 2026 : les bonbons à collectionner et les gages que le code sait vérifier.

Fichier de l'événement : il part avec le plugin (voir RETRAIT_HALLOWEEN.md).
"""

import random
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass

CANDY = "<:candy:1560363012874043422>"
LOLIPOP = "<:lolipop:1560368870190223410>"
CANDYCORN = "<:candycorn:1560368868990521496>"
CANDYBAR = "<:candybar:1560368867564322926>"
CARAMEL = "<:caramel:1560368866444578927>"
TRICK_WORDS = ("citrouille", "fantôme", "squelette", "sorcière", "vampire", "bonbon")


@dataclass(frozen=True, slots=True)
class Sweet:
    key: str
    emoji: str
    gift: str  # ce que MARIA donne, tel qu'on le lit dans « Tu reçois … »
    pieces: int
    weight: int
    fallback: str  # emoji Unicode si le bot ne peut pas utiliser le sien


SWEETS = (
    Sweet("candy", CANDY, "un bonbon", 1, 30, "🍬"),
    Sweet("caramel", CARAMEL, "deux caramels", 2, 25, "🍮"),
    Sweet("candycorn", CANDYCORN, "une poignée de bonbons de maïs", 2, 20, "🌽"),
    Sweet("lolipop", LOLIPOP, "une sucette", 1, 15, "🍭"),
    Sweet("candybar", CANDYBAR, "une barre chocolatée", 1, 10, "🍫"),
)
BY_KEY = {sweet.key: sweet for sweet in SWEETS}
SWEET_FALLBACKS = {sweet.emoji: sweet.fallback for sweet in SWEETS}


def draw_sweet(dice: random.Random) -> Sweet:
    return dice.choices(SWEETS, weights=[sweet.weight for sweet in SWEETS])[0]


@dataclass(frozen=True, slots=True)
class Trick:
    """Un sort. `kind` vide : un vol de bonbons ; sinon un gage que le code vérifie."""

    kind: str
    text: str
    steal: int = 0
    word: str = ""

    @property
    def is_dare(self) -> bool:
        return bool(self.kind)


_DARES = {
    "caps": "Écris l'un de tes 3 prochains messages tout en MAJUSCULES (8 lettres au moins).",
    "emoji": "Glisse un 🎃 ou un 👻 dans l'un de tes 3 prochains messages.",
    "long": "Écris un message de 20 mots ou plus parmi tes 3 prochains.",
    "question": "Pose une question (avec un « ? ») dans l'un de tes 3 prochains messages.",
}
_THEFTS = (
    Trick("", "Une sorcière te chipe deux bonbons dans ton sac !", steal=2),
    Trick("", "Un fantôme farceur te prend un bonbon !", steal=1),
)


def dare_text(kind: str, word: str) -> str:
    if kind == "word":
        return f"Place le mot « {word} » dans l'un de tes 3 prochains messages."
    return _DARES.get(kind, "")


def draw_trick(dice: random.Random) -> Trick:
    options = [
        *(Trick(kind, text) for kind, text in _DARES.items()),
        Trick("word", "", word=dice.choice(TRICK_WORDS)),
        *_THEFTS,
    ]
    chosen = dice.choice(options)
    return Trick(
        chosen.kind, dare_text(chosen.kind, chosen.word) or chosen.text, chosen.steal, chosen.word
    )


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(char for char in decomposed if not unicodedata.combining(char)).casefold()


def _has_word(text: str, word: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(_fold(word))}(?!\w)", _fold(text)) is not None


def _shouting(text: str) -> bool:
    letters = [char for char in text if char.isalpha()]
    return len(letters) >= 8 and all(char.isupper() for char in letters)


def respects(kind: str, word: str, text: str) -> bool:
    """Le message accomplit-il ce gage ?"""
    checks: dict[str, Callable[[], bool]] = {
        "word": lambda: _has_word(text, word),
        "caps": lambda: _shouting(text),
        "emoji": lambda: "🎃" in text or "👻" in text,
        "long": lambda: len(text.split()) >= 20,
        "question": lambda: "?" in text,
    }
    return checks.get(kind, lambda: False)()
