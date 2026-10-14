"""Tirages au sort, heures dans le monde et tracé de fonctions. Petits outils, aucun compte."""

import random
import re
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from maria_core.capabilities.base import Capability, Context, Result, Risk
from maria_core.capabilities.builtin.formula import compile_formula
from maria_core.capabilities.builtin.visuals import PALETTE, chart_url, shown
from maria_core.capabilities.http import HttpClient
from maria_core.ui.widgets import Rendered, card, footer, separator, text

_RNG = random.SystemRandom()
_DICE = re.compile(r"^\s*(\d{0,3})\s*[dD]\s*(\d{1,4})\s*(?:([+-])\s*(\d{1,6}))?\s*$")
_MAX_ZONES = 6
_POINTS = 90
_LIMIT = 1e9
_DAYS = ("lun", "mar", "mer", "jeu", "ven", "sam", "dim")


def fun_capabilities(http: HttpClient) -> tuple[Capability, ...]:
    return (
        Capability(
            name="random_pick",
            description=_PICK_TEXT,
            parameters=_pick_schema(),
            risk=Risk.READ,
            run=_pick,
        ),
        Capability(
            name="convert_time",
            description=_TIME_TEXT,
            parameters=_time_schema(),
            risk=Risk.READ,
            run=_convert,
        ),
        Capability(
            name="plot_function",
            description=_PLOT_TEXT,
            parameters=_plot_schema(),
            risk=Risk.EXTERNAL,
            run=_plot(http),
            cache_s=3600,
            timeout_s=45,
        ),
    )


def render_clock(data: Mapping[str, Any]) -> Rendered:
    rows = [row for row in data.get("rows") or [] if isinstance(row, Mapping)]
    lines = [
        f"**{row['label']}** · {row['time']}  -# {row['day']} · {row['offset']}" for row in rows
    ]
    built = card(
        text(f"## 🕒 {data.get('moment')}"),
        separator(wide=True),
        text("\n".join(lines)),
        footer("fuseaux horaires IANA"),
    )
    return Rendered(
        cards=(built,), note="Heures affichées : " + "; ".join(line[:60] for line in lines)
    )


async def _pick(_context: Context, args: Mapping[str, Any]) -> Result:
    kind = str(args["kind"])
    try:
        found = {
            "dice": _dice,
            "coin": _coin,
            "pick": _choose,
            "number": _number,
        }[kind](args)
    except ValueError as exc:
        return Result(ok=False, data={}, error=str(exc))
    return Result(ok=True, data=found)


def _dice(args: Mapping[str, Any]) -> dict[str, Any]:
    found = _DICE.match(str(args.get("notation") or "1d6"))
    if found is None:
        raise ValueError("Notation de dés : 2d6, d20, 3d8+2.")
    count, faces = int(found.group(1) or 1), int(found.group(2))
    if not 1 <= count <= 100 or faces < 2:
        raise ValueError("Entre 1 et 100 dés, d'au moins 2 faces.")
    bonus = int(found.group(4) or 0) * (-1 if found.group(3) == "-" else 1)
    rolls = [_RNG.randint(1, faces) for _ in range(count)]
    return {"kind": "dice", "rolls": rolls, "bonus": bonus, "total": sum(rolls) + bonus}


def _coin(args: Mapping[str, Any]) -> dict[str, Any]:
    flips = max(1, min(20, int(args.get("count") or 1)))
    return {"kind": "coin", "results": [_RNG.choice(("pile", "face")) for _ in range(flips)]}


def _choose(args: Mapping[str, Any]) -> dict[str, Any]:
    options = [str(item).strip() for item in args.get("options") or [] if str(item).strip()]
    if len(options) < 2:
        raise ValueError("Donne au moins deux options.")
    wanted = max(1, min(int(args.get("count") or 1), len(options), 20))
    return {"kind": "pick", "chosen": _RNG.sample(options[:50], min(wanted, len(options[:50])))}


def _number(args: Mapping[str, Any]) -> dict[str, Any]:
    low, high = int(args.get("low") or 1), int(args.get("high") or 100)
    if low > high or abs(low) > _LIMIT or abs(high) > _LIMIT:
        raise ValueError("Bornes invalides (low <= high).")
    return {"kind": "number", "number": _RNG.randint(low, high), "between": [low, high]}


async def _convert(_context: Context, args: Mapping[str, Any]) -> Result:
    try:
        base = _base(args)
        rows = [_row(base, name) for name in args["to_zones"][:_MAX_ZONES]]
    except ValueError as exc:
        return Result(ok=False, data={}, error=str(exc))
    origin = _row(base, str(args.get("from_zone") or "Europe/Paris"))
    moment = f"{origin['label']} : {origin['time']} ({origin['day']})"
    return Result(ok=True, data={"moment": moment, "rows": rows}, widget="render_clock")


def _base(args: Mapping[str, Any]) -> datetime:
    zone = _zone(str(args.get("from_zone") or "Europe/Paris"))
    now = datetime.now(UTC).astimezone(zone)
    moment = str(args.get("at") or "").strip()
    day = _day(str(args.get("date") or ""), now.date())
    if not moment:
        return datetime.combine(day, now.time().replace(microsecond=0), tzinfo=zone)
    found = re.match(r"^(\d{1,2})\s*[:hH]\s*(\d{2})?$", moment)
    if found is None or int(found.group(1)) > 23 or int(found.group(2) or 0) > 59:
        raise ValueError("Heure illisible : écris 18:30.")
    clock = time(int(found.group(1)), int(found.group(2) or 0))
    return datetime.combine(day, clock, tzinfo=zone)


def _day(raw: str, today: date) -> date:
    if not raw.strip():
        return today
    try:
        return date.fromisoformat(raw.strip())
    except ValueError as exc:
        raise ValueError("Date illisible : écris 2026-12-25.") from exc


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name.strip())
    except (ZoneInfoNotFoundError, ValueError, OSError) as exc:
        raise ValueError(f"Fuseau inconnu : {name}. Utilise un nom comme Asia/Tokyo.") from exc


def _row(base: datetime, name: str) -> dict[str, str]:
    zone = _zone(name)
    local = base.astimezone(zone)
    offset = local.utcoffset() or timedelta(0)
    minutes = int(offset.total_seconds() // 60)
    sign = "+" if minutes >= 0 else "-"
    hours, rest = divmod(abs(minutes), 60)
    return {
        "label": name.split("/")[-1].replace("_", " "),
        "zone": name,
        "time": f"{local:%H:%M}",
        "day": f"{_DAYS[local.weekday()]} {local:%d/%m}",
        "offset": f"UTC{sign}{hours}" + (f":{rest:02d}" if rest else ""),
    }


def _plot(http: HttpClient) -> Callable[[Context, Mapping[str, Any]], Any]:
    async def run(_context: Context, args: Mapping[str, Any]) -> Result:
        try:
            config = _plot_config(args)
            url = await chart_url(http, config)
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
    datasets = [_curve(source, xs, index) for index, source in enumerate(expressions)]
    title = str(args.get("title") or "").strip()
    return {
        "type": "line",
        "data": {"labels": [round(x, 3) for x in xs], "datasets": datasets},
        "options": {
            "title": {"display": bool(title), "text": title, "fontSize": 18},
            "legend": {"display": len(datasets) > 1},
            "elements": {"point": {"radius": 0}},
            "scales": {"xAxes": [{"ticks": {"maxTicksLimit": 10}}]},
        },
    }


def _curve(source: str, xs: list[float], index: int) -> dict[str, Any]:
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
    color = PALETTE[index % len(PALETTE)]
    return {
        "label": f"f(x) = {source}"[:60],
        "data": values,
        "borderColor": color,
        "backgroundColor": color,
        "fill": False,
        "borderWidth": 2,
        "spanGaps": False,
    }


_PICK_TEXT = (
    "Tire au hasard, pour de vrai : kind=dice (notation 2d6, d20, 3d8+2), coin (pile ou face, "
    "count lancers), pick (options = la liste, count = combien en choisir), number (entre low "
    "et high). Annonce le résultat simplement, avec un peu de punch."
)
_TIME_TEXT = (
    "Convertit une heure entre fuseaux : « il est quelle heure à Tokyo ? », « 18h à Paris, c'est "
    "quoi à New York ? ». from_zone (défaut Europe/Paris), at = HH:MM (défaut : maintenant), "
    "date AAAA-MM-JJ (défaut : aujourd'hui), to_zones = noms IANA (America/New_York, Asia/Tokyo). "
    "Gère l'heure d'été."
)
_PLOT_TEXT = (
    "Trace la courbe d'une ou plusieurs fonctions de x : « trace sin(x)/x », « x^2 et 2x+1 entre "
    "-5 et 5 ». expressions : formules en x (sin, cos, tan, exp, log, sqrt, abs, pi, e ; ^ pour "
    "les puissances ; * obligatoire : 2*x). xmin, xmax : l'intervalle."
)


def _pick_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": ["dice", "coin", "pick", "number"]},
            "notation": {"type": "string", "description": "dice : 2d6, d20, 3d8+2"},
            "count": {"type": "integer", "minimum": 1, "maximum": 20},
            "options": {"type": "array", "items": {"type": "string"}, "maxItems": 50},
            "low": {"type": "integer"},
            "high": {"type": "integer"},
        },
        "required": ["kind"],
    }


def _time_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "to_zones": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "maxItems": _MAX_ZONES,
            },
            "from_zone": {"type": "string"},
            "at": {"type": "string", "description": "HH:MM"},
            "date": {"type": "string", "description": "AAAA-MM-JJ"},
        },
        "required": ["to_zones"],
    }


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
        },
        "required": ["expressions", "xmin", "xmax"],
    }
