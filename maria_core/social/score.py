"""Score d'une réaction ambiante. Mêmes entrées, même nombre."""

from dataclasses import dataclass


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
    return Parts(
        activity=min(max(humans, 0), 4) / 4 * 0.35,
        reactions=min(max(human_reactions, 0), 3) / 3 * 0.25,
        expressive=0.3 if expressive else 0.0,
        attention=min(max(attention, 0.0), 2.0) / 2 * 0.3,
        fatigue=min(max(fatigue, 0.0), 4.0) / 4 * 0.45,
        recent=0.25 if maria_reacted else 0.0,
    )
