"""Valide les arguments d'un outil avant de l'exécuter.

Le schéma est celui annoncé au modèle : une propriété absente de `required`
peut manquer ou valoir null. Tout le reste est refusé.
"""

from collections.abc import Mapping
from typing import Any


def prepare_arguments(schema: Mapping[str, Any], raw: Mapping[str, Any]) -> dict[str, Any]:
    properties = schema.get("properties") or {}
    if not isinstance(properties, dict):
        raise ValueError("Schéma d'outil invalide.")
    required = set(schema.get("required", ()))
    cleaned: dict[str, Any] = {}
    for key, value in raw.items():
        if key not in properties:
            raise ValueError(f"Argument inattendu : {key}.")
        if value is None:
            continue
        cleaned[key] = _check(key, value, properties[key])
    missing = [name for name in properties if name in required and name not in cleaned]
    if missing:
        raise ValueError("Argument manquant : " + ", ".join(missing) + ".")
    return cleaned


def _check(name: str, value: Any, spec: Mapping[str, Any]) -> Any:
    kind = spec.get("type")
    if isinstance(kind, str) and not _matches(value, kind):
        raise ValueError(f"{name} doit être de type {kind}.")
    if "enum" in spec and value not in spec["enum"]:
        raise ValueError(f"{name} n'est pas une valeur autorisée.")
    _bounds(name, value, spec)
    if kind == "array":
        _items(name, value, spec.get("items") or {})
    return value


def _matches(value: Any, kind: str) -> bool:
    if kind == "string":
        return isinstance(value, str)
    if kind == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "number":
        return isinstance(value, int | float) and not isinstance(value, bool)
    if kind == "boolean":
        return isinstance(value, bool)
    if kind == "array":
        return isinstance(value, list)
    if kind == "object":
        return isinstance(value, dict)
    return True


def _bounds(name: str, value: Any, spec: Mapping[str, Any]) -> None:
    if isinstance(value, int | float) and not isinstance(value, bool):
        if "minimum" in spec and value < spec["minimum"]:
            raise ValueError(f"{name} est trop petit.")
        if "maximum" in spec and value > spec["maximum"]:
            raise ValueError(f"{name} est trop grand.")
    if isinstance(value, list):
        if "minItems" in spec and len(value) < spec["minItems"]:
            raise ValueError(f"{name} n'a pas assez d'éléments.")
        if "maxItems" in spec and len(value) > spec["maxItems"]:
            raise ValueError(f"{name} a trop d'éléments.")


def _items(name: str, value: list[Any], spec: Mapping[str, Any]) -> None:
    kind = spec.get("type")
    if not isinstance(kind, str):
        return
    for item in value:
        if not _matches(item, kind):
            raise ValueError(f"{name} contient un élément de type inattendu.")
