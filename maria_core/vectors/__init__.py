"""Voisinage sémantique, derrière une interface. FTS5 ne passe pas par ici."""

from maria_core.vectors.index import VectorIndex
from maria_core.vectors.null import NullIndex

__all__ = ["NullIndex", "VectorIndex"]
