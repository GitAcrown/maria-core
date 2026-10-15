"""Le profil vu de MARIA : ce qu'elle sait de la personne, et ce qu'elle en déduit."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from maria_core.conversation.model import Inbound
from maria_core.db import Database
from maria_core.profile.extract import extract
from maria_core.profile.slots import BY_KEY, FACTS, GUIDANCE, SLOTS, STYLE, Slot
from maria_core.profile.store import ProfileStore
from maria_core.profile.style import StyleTracker

type Clock = Callable[[], datetime]


@dataclass(frozen=True, slots=True)
class Resolved:
    """Valeur retenue pour un champ, et d'où elle vient : user, auto ou style (déduit)."""

    slot: Slot
    value: str
    source: str


class Profiles:
    def __init__(self, database: Database, clock: Clock | None = None) -> None:
        self.store = ProfileStore(database)
        self.style = StyleTracker(database)
        self._clock = clock or _now

    def now(self) -> datetime:
        return self._clock()

    def resolve(self, user_id: int) -> dict[str, Resolved]:
        """Un champ par clé : réglé par la personne, appris, ou déduit du style."""
        saved = self.store.all(user_id)
        deduced = self.style.learned(user_id)
        found: dict[str, Resolved] = {}
        for slot in SLOTS:
            entry = saved.get(slot.key)
            if entry is not None:
                found[slot.key] = Resolved(slot, entry.value, entry.source)
            elif slot.key in deduced:
                found[slot.key] = Resolved(slot, deduced[slot.key], "style")
        return found

    def value(self, user_id: int, key: str) -> str:
        """Valeur utilisable par un outil : un champ de faits, jamais un style déduit."""
        return self.store.value(user_id, key) if key in {slot.key for slot in FACTS} else ""

    def label(self, key: str) -> str:
        slot = BY_KEY.get(key)
        return slot.label if slot is not None else key

    def prompt_for(self, message: Inbound) -> str:
        if message.is_dm:
            return ""
        found = self.resolve(message.author_id)
        facts = [
            f"{item.slot.label.lower()} : {item.value}"
            for item in found.values()
            if item.slot in FACTS
        ]
        style = [
            GUIDANCE[(item.slot.key, item.value)]
            for item in found.values()
            if item.slot in STYLE and (item.slot.key, item.value) in GUIDANCE
        ]
        lines: list[str] = []
        if facts:
            lines.append("- " + " ; ".join(facts))
        if style:
            lines.append("- à ton interlocuteur : " + ", ".join(style) + " (sans le dire)")
        if not lines:
            return ""
        name = message.author_name or "la personne"
        head = (
            f"PROFIL DE {name} (elle le voit et le règle dans /moi, onglet Profil). "
            "Pour une demande sur "
            "« chez moi », « mon équipe », « mon arrêt », passe la valeur @profil à l'outil :"
        )
        return "\n".join([head, *lines])

    def observe(self, message: Inbound) -> list[str]:
        """Style d'abord, puis champs dits clairement. Renvoie les champs appris pour la trace."""
        if message.is_dm or message.author_is_bot:
            return []
        now = self.now()
        self.style.observe(message.author_id, message.text, now)
        learned: list[str] = []
        for key, value in extract(message.text).items():
            if self.store.learn(message.author_id, key, value, now):
                learned.append(f"{BY_KEY[key].label} : {value}")
        return learned

    def reset_style(self, user_id: int) -> None:
        self.style.reset(user_id)
        for slot in STYLE:
            self.store.clear(user_id, slot.key)


def _now() -> datetime:
    return datetime.now(UTC)
