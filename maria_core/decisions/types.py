"""Objets partagés par le catalogue, le moteur et le backend."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

type DecisionPath = Literal["rules", "cache", "model", "fallback"]


@dataclass(frozen=True, slots=True)
class RuleHit:
    """Une règle a tranché. `None` à la place signifie « je ne sais pas »."""

    value: Any
    confidence: float = 1.0


@dataclass(frozen=True, slots=True)
class Question:
    """Question posée au backend structuré. Les critères sont des libellés courts."""

    instructions: str
    criteria: Mapping[str, str]
    kind: Literal["choice", "noul"] = "choice"
    field: str = "answer"


@dataclass(frozen=True, slots=True)
class StructuredAnswer:
    value: Any
    confidence: float


@dataclass(frozen=True, slots=True)
class Verdict:
    name: str
    value: Any
    path: DecisionPath
    confidence: float | None
