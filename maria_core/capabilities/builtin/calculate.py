"""Calcul et conversion d'unités exacts : le modèle ne fait jamais l'arithmétique de tête.

Le calcul passe par l'évaluateur de formules sans `eval` ; les conversions par une table fermée
d'unités courantes. Aucune devise (le cours change : la recherche web s'en charge).
"""

import math
import unicodedata
from collections.abc import Mapping
from typing import Any

from maria_core.capabilities.base import Capability, Context, Result, Risk
from maria_core.capabilities.builtin.formula import compile_formula

_FAMILIES: dict[str, dict[str, float]] = {
    "longueur": {
        "mm": 0.001, "cm": 0.01, "m": 1.0, "km": 1000.0,
        "in": 0.0254, "ft": 0.3048, "yd": 0.9144, "mi": 1609.344,
    },
    "masse": {
        "mg": 1e-6, "g": 0.001, "kg": 1.0, "t": 1000.0,
        "oz": 0.028349523125, "lb": 0.45359237,
    },
    "volume": {
        "ml": 0.001, "cl": 0.01, "dl": 0.1, "l": 1.0,
        "gal": 3.785411784, "floz": 0.0295735295625,
    },
    "vitesse": {"km/h": 1 / 3.6, "m/s": 1.0, "mph": 0.44704, "kn": 1852 / 3600},
    "durée": {"s": 1.0, "min": 60.0, "h": 3600.0, "j": 86400.0, "sem": 604800.0},
    "données": {
        "o": 1.0, "ko": 1e3, "mo": 1e6, "go": 1e9, "to": 1e12,
        "kio": 1024.0, "mio": 1024.0**2, "gio": 1024.0**3, "tio": 1024.0**4,
    },
    "surface": {
        "cm2": 1e-4, "m2": 1.0, "ha": 1e4, "km2": 1e6,
        "ft2": 0.09290304, "acre": 4046.8564224, "mi2": 2589988.110336,
    },
}  # fmt: skip
_TEMPERATURES = {"c", "f", "k"}
_ALIASES = {
    "pouce": "in", "inch": "in", "pied": "ft", "foot": "ft", "feet": "ft", "yard": "yd",
    "mile": "mi", "metre": "m", "kilometre": "km", "centimetre": "cm", "millimetre": "mm",
    "gramme": "g", "kilo": "kg", "kilogramme": "kg", "tonne": "t", "once": "oz",
    "livre": "lb", "pound": "lb", "lbs": "lb", "litre": "l", "millilitre": "ml",
    "centilitre": "cl", "gallon": "gal", "kmh": "km/h", "km/heure": "km/h", "noeud": "kn",
    "seconde": "s", "minute": "min", "heure": "h", "jour": "j", "semaine": "sem",
    "octet": "o", "m²": "m2", "km²": "km2", "cm²": "cm2", "mètre carré": "m2",
    "hectare": "ha", "metre carre": "m2", "metres carres": "m2", "celsius": "c",
    "fahrenheit": "f", "kelvin": "k",
}  # fmt: skip
_DESCRIPTION = (
    "Calcul et conversion exacts : à utiliser pour TOUT calcul (opération, pourcentage, "
    "moyenne, racine) et TOUTE conversion d'unités (km/miles, kg/livres, °C/°F, km/h/mph, "
    "durées, octets, surfaces), sans jamais calculer de tête. expression : un calcul avec + - * "
    "/ ^ % (modulo) ( ), sqrt, abs, log, sin, pi ; « 20 % de 150 » s'écrit 0.2*150. "
    "Pour une conversion : value, from_unit, to_unit (pas de devises : recherche web)."
)


def calculate_capability() -> Capability:
    async def run(_context: Context, args: Mapping[str, Any]) -> Result:
        try:
            expression = str(args.get("expression") or "").strip()
            data = _evaluate(expression) if expression else _convert(args)
        except (ValueError, ZeroDivisionError, OverflowError) as exc:
            return Result(ok=False, data={}, error=str(exc) or "Calcul impossible.")
        return Result(ok=True, data=data)

    return Capability(
        name="calculate",
        description=_DESCRIPTION,
        parameters={
            "type": "object",
            "properties": {
                "expression": {"type": "string", "description": "Calcul à effectuer"},
                "value": {"type": "number", "description": "Valeur à convertir"},
                "from_unit": {"type": "string", "description": "Unité de départ (km, lb, °C…)"},
                "to_unit": {"type": "string", "description": "Unité d'arrivée"},
            },
            "required": [],
        },
        risk=Risk.READ,
        run=run,
    )


def _evaluate(expression: str) -> dict[str, Any]:
    result = compile_formula(expression)(0.0)
    if not math.isfinite(result):
        raise ValueError("Le résultat n'est pas un nombre fini.")
    return {"expression": expression, "result": _show(result)}


def _convert(args: Mapping[str, Any]) -> dict[str, Any]:
    raw = args.get("value")
    source, target = _unit(args.get("from_unit")), _unit(args.get("to_unit"))
    if isinstance(raw, bool) or not isinstance(raw, int | float) or not source or not target:
        raise ValueError("Donne soit une expression, soit value, from_unit et to_unit.")
    value = float(raw)
    if source in _TEMPERATURES and target in _TEMPERATURES:
        result = _kelvin_to(target, _to_kelvin(source, value))
    else:
        family = _family_of(source, target)
        result = value * family[source] / family[target]
    return {
        "from": f"{_show(value)} {source}",
        "to": f"{_show(result)} {target}",
        "result": _show(result),
    }


def _family_of(source: str, target: str) -> dict[str, float]:
    for family in _FAMILIES.values():
        if source in family and target in family:
            return family
    raise ValueError(f"Conversion impossible de « {source} » vers « {target} » : unités inconnues.")


def _to_kelvin(unit: str, value: float) -> float:
    if unit == "c":
        return value + 273.15
    return (value - 32) * 5 / 9 + 273.15 if unit == "f" else value


def _kelvin_to(unit: str, kelvin: float) -> float:
    if unit == "c":
        return kelvin - 273.15
    return (kelvin - 273.15) * 9 / 5 + 32 if unit == "f" else kelvin


def _unit(raw: object) -> str:
    text = unicodedata.normalize("NFKD", str(raw or "").casefold())
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.replace("°", "").replace("degres", "").replace("degre", "").strip()
    folded = {_fold(key): value for key, value in _ALIASES.items()}
    known = {unit for family in _FAMILIES.values() for unit in family} | _TEMPERATURES
    if text in known:
        return text
    if text in folded:
        return folded[text]
    singular = text[:-1] if text.endswith("s") and len(text) > 2 else text
    return folded.get(singular, singular)


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _show(number: float) -> str:
    return f"{number:.10g}"
