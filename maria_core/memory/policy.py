"""Qui peut écrire quel souvenir. Une proposition n'est pas une écriture."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Actor:
    user_id: int
    is_owner: bool
    is_moderator: bool


def denial(actor: Actor, scope: str, subject_id: int) -> str:
    """Message de refus, ou une chaîne vide si l'écriture est permise."""
    if scope == "user":
        if subject_id != actor.user_id:
            return "Tu ne peux pas créer un souvenir sur quelqu'un d'autre."
        return ""
    if scope == "guild":
        if actor.is_moderator or actor.is_owner:
            return ""
        return "La mémoire du serveur se propose, elle s'écrit par un modérateur."
    if scope == "self":
        if actor.is_owner:
            return ""
        return "La mémoire de MARIA est réservée à son propriétaire."
    return "Portée de souvenir inconnue."
