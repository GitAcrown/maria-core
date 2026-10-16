"""Les champs du profil. Chacun est visible et modifiable dans /moi (onglet Profil)."""

from collections.abc import Callable
from dataclasses import dataclass

from maria_core.profile.birthday import normalize, show


@dataclass(frozen=True, slots=True)
class Slot:
    key: str
    label: str
    hint: str
    choices: tuple[tuple[str, str], ...] = ()
    normalize: Callable[[str], str] | None = None
    show: Callable[[str], str] | None = None

    @property
    def is_choice(self) -> bool:
        return bool(self.choices)

    def label_of(self, value: str) -> str:
        if self.show is not None:
            return self.show(value)
        return dict(self.choices).get(value, value)


CITY = Slot("city", "Ville", "Météo, « chez moi », « ici »")
TEAM = Slot("team", "Équipe de foot", "« Mon équipe », « le match d'hier »")
STOP = Slot("stop", "Arrêt ou gare habituel", "« Mon métro », « mon train »")
BIRTHDAY = Slot(
    "birthday",
    "Anniversaire",
    "Jour et mois, par exemple 22 juillet",
    normalize=normalize,
    show=show,
)
LENGTH = Slot(
    "length",
    "Longueur des réponses",
    "Court, équilibré ou détaillé",
    (("short", "Courtes"), ("normal", "Équilibrées"), ("long", "Détaillées")),
)
TONE = Slot(
    "tone",
    "Ton",
    "Décontracté, neutre ou soigné",
    (("casual", "Décontracté"), ("neutral", "Neutre"), ("polished", "Soigné")),
)
EMOJI = Slot(
    "emoji",
    "Emojis",
    "Par défaut MARIA n'en met pas",
    (("none", "Aucun"), ("some", "Quelques-uns"), ("many", "Volontiers")),
)

FACTS = (CITY, TEAM, STOP, BIRTHDAY)
STYLE = (LENGTH, TONE, EMOJI)
SLOTS = (*FACTS, *STYLE)
BY_KEY = {slot.key: slot for slot in SLOTS}

# Ce que le modèle lit dans le prompt pour chaque choix de style.
GUIDANCE = {
    ("length", "short"): "réponses courtes, une ou deux phrases",
    ("length", "long"): "réponses développées quand le sujet le mérite",
    ("tone", "casual"): "ton décontracté, comme entre amis",
    ("tone", "polished"): "ton soigné, sans familiarité",
    ("emoji", "none"): "aucun emoji",
    ("emoji", "some"): "quelques emojis sont bienvenus",
    ("emoji", "many"): "emojis volontiers",
}
