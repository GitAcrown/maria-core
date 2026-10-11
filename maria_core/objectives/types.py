"""Familles d'objectifs. Les types concrets (rappel, veille, écoute) viendront ensuite."""

from dataclasses import dataclass

from maria_core.errors import RegistryError
from maria_core.names import require_name
from maria_core.registry import Registry

_FAMILIES = frozenset({"trigger", "condition", "action"})


@dataclass(frozen=True, slots=True)
class ObjectiveKind:
    name: str
    family: str
    description: str

    def __post_init__(self) -> None:
        require_name(self.name, what="Type d'objectif")
        if self.family not in _FAMILIES:
            raise RegistryError(
                f"Famille inconnue : {self.family!r}. Attendu : {', '.join(sorted(_FAMILIES))}."
            )
        if not self.description.strip():
            raise RegistryError(f"Le type {self.name} n'a pas de description.")
        object.__setattr__(self, "description", self.description.strip())


class ObjectiveTypes:
    def __init__(self) -> None:
        self._by_family = {
            "trigger": Registry[ObjectiveKind](kind="Déclencheur"),
            "condition": Registry[ObjectiveKind](kind="Condition"),
            "action": Registry[ObjectiveKind](kind="Action"),
        }

    def register_trigger(self, kind: ObjectiveKind) -> None:
        self._register("trigger", kind)

    def register_condition(self, kind: ObjectiveKind) -> None:
        self._register("condition", kind)

    def register_action(self, kind: ObjectiveKind) -> None:
        self._register("action", kind)

    def names(self, family: str) -> tuple[str, ...]:
        try:
            bucket = self._by_family[family]
        except KeyError as exc:
            raise RegistryError(f"Famille inconnue : {family}") from exc
        return bucket.names()

    def _register(self, family: str, kind: ObjectiveKind) -> None:
        if not isinstance(kind, ObjectiveKind):
            raise RegistryError("Type d'objectif attendu.")
        if kind.family != family:
            raise RegistryError(
                f"{kind.name} appartient à la famille {kind.family}, pas à {family}."
            )
        self._by_family[family].add(kind.name, kind)
