"""Les champs du profil. Chacun est visible et modifiable dans /profil."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Slot:
    key: str
    label: str
    hint: str
    choices: tuple[tuple[str, str], ...] = ()

    @property
    def is_choice(self) -> bool:
        return bool(self.choices)

    def label_of(self, value: str) -> str:
        return dict(self.choices).get(value, value)


CITY = Slot("city", "Ville", "Météo, « chez moi », « ici »")
TEAM = Slot("team", "Équipe de foot", "« Mon équipe », « le match d'hier »")
STOP = Slot("stop", "Arrêt ou gare habituel", "« Mon métro », « mon train »")
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

FACTS = (CITY, TEAM, STOP)
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
