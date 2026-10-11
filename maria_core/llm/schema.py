"""Schéma d'outil strict, adapté du registre MARIA_R.

En mode strict, OpenAI exige que chaque objet liste toutes ses propriétés dans
`required` et refuse les propriétés supplémentaires. Un paramètre facultatif
devient donc obligatoire mais nullable.
"""

from collections.abc import Mapping
from typing import Any

from maria_core.capabilities import Capability


def openai_tool(capability: Capability) -> dict[str, Any]:
    parameters = strict_schema({"type": "object", **capability.parameters})
    return {
        "type": "function",
        "function": {
            "name": capability.name,
            "description": capability.description,
            "strict": True,
            "parameters": parameters,
        },
    }


def strict_schema(schema: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(schema)
    if "items" in result and isinstance(result["items"], Mapping):
        result["items"] = strict_schema(result["items"])
    for key in ("anyOf", "oneOf", "allOf"):
        if key in result:
            result[key] = [strict_schema(item) for item in result[key]]
    if result.get("type") == "object":
        _strict_object(result)
    return result


def _strict_object(schema: dict[str, Any]) -> None:
    properties = dict(schema.get("properties") or {})
    required = set(schema.get("required", properties))
    schema["properties"] = {
        name: strict_schema(value) if name in required else _nullable(strict_schema(value))
        for name, value in properties.items()
    }
    schema["required"] = list(properties)
    schema["additionalProperties"] = False


def _nullable(schema: dict[str, Any]) -> dict[str, Any]:
    kind = schema.get("type")
    if "enum" in schema or not isinstance(kind, str | list):
        return {"anyOf": [schema, {"type": "null"}]}
    kinds = [kind] if isinstance(kind, str) else list(kind)
    if "null" in kinds:
        return schema
    return {**schema, "type": [*kinds, "null"]}
