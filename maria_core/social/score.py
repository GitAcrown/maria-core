"""Score d'une réaction ambiante. Mêmes entrées, même nombre."""

from dataclasses import dataclass

from maria_core.social.room import ATTENTION_HOT, FATIGUE_EXHAUSTED


@dataclass(frozen=True, slots=True)
class Parts:
    activity: float
    reactions: float
    expressive: float
    attention: float
    fatigue: float
    recent: float

    def total(self) -> float:
        return (
            self.activity
            + self.reactions
            + self.expressive
            + self.attention
            - self.fatigue
            - self.recent
        )

    def as_dict(self) -> dict[str, float]:
        return {
            "activite": round(self.activity, 3),
            "reactions": round(self.reactions, 3),
            "expressif": round(self.expressive, 3),
            "attention": round(self.attention, 3),
            "fatigue": round(self.fatigue, 3),
            "recent": round(self.recent, 3),
            "total": round(self.total(), 3),
        }


def parts_from(
    *,
    humans: int,
    human_reactions: int,
    expressive: bool,
    attention: float,
    fatigue: float,
    maria_reacted: bool,
) -> Parts:
    """L'attention envers l'auteur pèse le plus : MARIA réagit surtout à qui lui parle."""
    return Parts(
        activity=min(max(humans, 0), 4) / 4 * 0.15,
        reactions=min(max(human_reactions, 0), 3) / 3 * 0.25,
        expressive=0.15 if expressive else 0.0,
        attention=min(max(attention, 0.0), ATTENTION_HOT) / ATTENTION_HOT * 0.45,
        fatigue=min(max(fatigue, 0.0), FATIGUE_EXHAUSTED) / FATIGUE_EXHAUSTED * 0.45,
        recent=0.2 if maria_reacted else 0.0,
    )
