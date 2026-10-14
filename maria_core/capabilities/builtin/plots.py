"""Tracé de fonctions : formule évaluée ici sans eval, image dessinée par QuickChart."""

from collections.abc import Callable, Mapping
from typing import Any

from maria_core.capabilities.base import Capability, Context, Result, Risk
from maria_core.capabilities.builtin.formula import compile_formula
from maria_core.capabilities.builtin.visuals import (
    THEMES,
    chart_url,
    look_of,
    look_options,
    palette_of,
    shown,
)
from maria_core.capabilities.http import HttpClient

_POINTS = 90
_LIMIT = 1e9


def plot_capability(http: HttpClient) -> Capability:
    return Capability(
        name="plot_function",
        description=_PLOT_TEXT,
        parameters=_plot_schema(),
        risk=Risk.EXTERNAL,
        run=_plot(http),
        cache_s=3600,
        timeout_s=45,
    )


def _plot(http: HttpClient) -> Callable[[Context, Mapping[str, Any]], Any]:
    async def run(_context: Context, args: Mapping[str, Any]) -> Result:
        try:
            config = _plot_config(args)
            url = await chart_url(http, config, look_of(args.get("theme")).background)
        except ValueError as exc:
            return Result(ok=False, data={}, error=str(exc))
        return shown("plot", str(args.get("title") or "").strip(), url)

    return run


def _plot_config(args: Mapping[str, Any]) -> dict[str, Any]:
    low, high = float(args["xmin"]), float(args["xmax"])
    if not low < high or abs(low) > _LIMIT or abs(high) > _LIMIT:
        raise ValueError("xmin doit être plus petit que xmax (valeurs raisonnables).")
    expressions = [str(item) for item in args["expressions"]][:3]
    xs = [low + (high - low) * i / (_POINTS - 1) for i in range(_POINTS)]
    colors = palette_of(args.get("colors"))
    datasets = [_curve(source, xs, index, colors) for index, source in enumerate(expressions)]
    title = str(args.get("title") or "").strip()
    options = look_options("line", look_of(args.get("theme")))
    options["title"] |= {"display": bool(title), "text": title, "fontSize": 18}
    options["legend"]["display"] = len(datasets) > 1
    options["elements"] = {"point": {"radius": 0}}
    options["scales"]["xAxes"][0] = {**options["scales"]["xAxes"][0]}
    options["scales"]["xAxes"][0]["ticks"] = {
        **options["scales"]["xAxes"][0]["ticks"],
        "maxTicksLimit": 10,
    }
    return {
        "type": "line",
        "data": {"labels": [round(x, 3) for x in xs], "datasets": datasets},
        "options": options,
    }


def _curve(source: str, xs: list[float], index: int, colors: tuple[str, ...]) -> dict[str, Any]:
    function = compile_formula(source)
    values: list[float | None] = []
    for x in xs:
        try:
            y = function(x)
        except (ArithmeticError, ValueError):
            y = None
        values.append(round(y, 6) if y is not None and abs(y) < _LIMIT else None)
    if all(value is None for value in values):
        raise ValueError(f"« {source} » n'est définie nulle part sur cet intervalle.")
    color = colors[index % len(colors)]
    return {
        "label": f"f(x) = {source}"[:60],
        "data": values,
        "borderColor": color,
        "backgroundColor": color,
        "fill": False,
        "borderWidth": 2,
        "spanGaps": False,
    }


_PLOT_TEXT = (
    "Trace la courbe d'une ou plusieurs fonctions de x : « trace sin(x)/x », « x^2 et 2x+1 entre "
    "-5 et 5 ». expressions : formules en x (sin, cos, tan, exp, log, sqrt, abs, pi, e ; ^ pour "
    "les puissances ; * obligatoire : 2*x). xmin, xmax : l'intervalle."
)


def _plot_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "expressions": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "maxItems": 3,
            },
            "xmin": {"type": "number"},
            "xmax": {"type": "number"},
            "title": {"type": "string"},
            "theme": {"type": "string", "enum": list(THEMES)},
            "colors": {"type": "array", "items": {"type": "string"}, "maxItems": 10},
        },
        "required": ["expressions", "xmin", "xmax"],
    }
