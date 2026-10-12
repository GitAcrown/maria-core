"""Un objectif : quand, à quelle condition, quoi envoyer."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any

_STATUSES = frozenset({"draft", "active", "paused", "done", "cancelled", "failed"})
_DELIVERS = frozenset({"channel", "dm"})


@dataclass(frozen=True, slots=True)
class Objective:
    id: int
    owner_id: int
    guild_id: int | None
    channel_ids: tuple[int, ...]
    deliver: str
    title: str
    trigger: Mapping[str, Any]
    condition: Mapping[str, Any] | None
    action: Mapping[str, Any]
    status: str
    next_run_at: datetime | None
    fires: int
    max_fires: int | None
    cooldown_s: int
    expires_at: datetime | None
    state: Mapping[str, Any]
    version: int
    last_error: str
    origin_message_id: int | None = None

    def __post_init__(self) -> None:
        if self.status not in _STATUSES:
            raise ValueError(f"Statut inconnu : {self.status}")
        if self.deliver not in _DELIVERS:
            raise ValueError(f"Destination inconnue : {self.deliver}")
        object.__setattr__(self, "trigger", MappingProxyType(dict(self.trigger)))
        object.__setattr__(self, "action", MappingProxyType(dict(self.action)))
        if self.condition is not None:
            object.__setattr__(self, "condition", MappingProxyType(dict(self.condition)))
        object.__setattr__(self, "state", MappingProxyType(dict(self.state)))
        object.__setattr__(self, "channel_ids", tuple(self.channel_ids))


class ObjectiveQuota(Exception):
    """Trop d'objectifs ouverts, ou budget d'une action épuisé."""


class StaleObjective(Exception):
    """Quelqu'un a modifié l'objectif entre-temps."""
