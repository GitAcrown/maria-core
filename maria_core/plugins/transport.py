"""Prochains passages PRIM (Île-de-France) et, à défaut, SNCF."""

from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

from maria_core.capabilities import Capability, Context, Result, Risk
from maria_core.capabilities.http import HttpClient, HttpError, parse_json, with_query
from maria_core.config import Settings
from maria_core.plugins import PluginHost

_PRIM = "https://prim.iledefrance-mobilites.fr/marketplace/v2/navitia"
_SNCF = "https://api.sncf.com/v1/coverage/sncf"


NAME = "transport"


def setup(app: PluginHost) -> None:
    app.capabilities.register(transport_capability(app.http, app.settings))
    app.widgets.register("get_transport", render_transport)


def transport_capability(http: HttpClient, settings: Settings) -> Capability:
    async def run(_context: Context, args: Mapping[str, Any]) -> Result:
        stop = str(args.get("stop") or "").strip()
        line = str(args.get("line") or "").strip()
        try:
            if stop:
                payload = await _departures(http, settings, stop, line)
            else:
                payload = await _disruptions(http, settings, line)
        except (ValueError, HttpError) as exc:
            return Result(ok=False, data={}, error=str(exc))
        return Result(ok=True, data=payload, widget="get_transport")

    return Capability(
        name="get_transport",
        description=(
            "Transports Île-de-France (PRIM) et trains SNCF. "
            "stop = arrêt ou gare : prochains passages. "
            "line seule : perturbations de la ligne. Ni l'un ni l'autre : perturbations en cours."
        ),
        parameters={
            "type": "object",
            "properties": {
                "stop": {"type": "string", "description": "Arrêt ou gare"},
                "line": {"type": "string", "description": "Ligne, ex. RER B ou 11"},
            },
            "required": [],
        },
        risk=Risk.EXTERNAL,
        run=run,
        requires_any=frozenset({"PRIM_API_KEY", "SNCF_API_KEY"}),
    )


def render_transport(data: Mapping[str, Any]) -> str:
    rows = data.get("rows") or []
    title = str(data.get("title") or "Transports")
    body = "\n".join(f"- {row}" for row in rows if isinstance(row, str))
    return f"{title}\n{body}".strip()


async def _departures(http: HttpClient, settings: Settings, stop: str, line: str) -> dict[str, Any]:
    place = await _place(http, settings, stop)
    if place is None:
        raise ValueError(f"Arrêt introuvable : {stop}.")
    rows = await _times(http, settings, place)
    if line:
        folded = line.casefold()
        rows = [row for row in rows if folded in row.casefold()]
    if not rows:
        raise ValueError(f"Aucun passage à {place[1]}.")
    return {"title": place[1], "rows": rows[:6]}


async def _place(http: HttpClient, settings: Settings, stop: str) -> tuple[str, str, str] | None:
    for source in _sources(settings):
        try:
            payload = await _get(
                http, settings, source, "places", {"q": stop, "count": "1"}, stop_area=True
            )
        except (ValueError, HttpError):
            continue
        places = payload.get("places") if isinstance(payload, dict) else None
        if places and isinstance(places[0], dict) and places[0].get("id"):
            return source, str(places[0]["id"]), str(places[0].get("name") or stop)
    return None


async def _times(http: HttpClient, settings: Settings, place: tuple[str, str, str]) -> list[str]:
    source, stop_id, _name = place
    path = f"stop_areas/{quote(stop_id, safe='')}/departures"
    payload = await _get(http, settings, source, path, {"count": "6"})
    rows = []
    for item in (payload.get("departures") or []) if isinstance(payload, dict) else []:
        if isinstance(item, dict):
            rows.append(_departure(item))
    return [row for row in rows if row]


async def _disruptions(http: HttpClient, settings: Settings, line: str) -> dict[str, Any]:
    source = "prim" if settings.prim_api_key else "sncf"
    if source == "sncf" and not settings.sncf_api_key:
        raise ValueError("Aucune clé transport.")
    path = "coverage/fr-idf/disruptions" if source == "prim" else "disruptions"
    payload = await _get(http, settings, source, path, {"count": "8"})
    rows = _notes(payload, line)
    title = f"Trafic {line}".strip() if line else "Trafic"
    if not rows:
        rows = ["Pas de perturbation listée."]
    return {"title": title, "rows": rows[:6]}


async def _get(
    http: HttpClient,
    settings: Settings,
    source: str,
    path: str,
    params: dict[str, str],
    *,
    stop_area: bool = False,
) -> Any:
    base = _PRIM if source == "prim" else _SNCF
    key = settings.prim_api_key if source == "prim" else settings.sncf_api_key
    query = dict(params)
    if stop_area and source == "prim":
        query["type[]"] = "stop_area"
    response = await http.request(
        "GET",
        with_query(f"{base}/{path}", query),
        headers=_headers(source, key),
    )
    return parse_json(response)


def _sources(settings: Settings) -> tuple[str, ...]:
    sources = []
    if settings.prim_api_key:
        sources.append("prim")
    if settings.sncf_api_key:
        sources.append("sncf")
    return tuple(sources)


def _headers(source: str, key: str) -> dict[str, str]:
    if source == "prim":
        return {"apikey": key}
    return {"Authorization": key}


def _departure(item: Mapping[str, Any]) -> str:
    info = (
        item.get("display_informations")
        if isinstance(item.get("display_informations"), dict)
        else {}
    )
    stop_time = item.get("stop_date_time") if isinstance(item.get("stop_date_time"), dict) else {}
    label = str(info.get("label") or info.get("code") or "")
    direction = str(info.get("direction") or "")
    return (
        f"{_clock(str(stop_time.get('departure_date_time') or ''))} {label} → {direction}".strip()
    )


def _notes(payload: Any, line: str) -> list[str]:
    disruptions = payload.get("disruptions") if isinstance(payload, dict) else None
    notes = []
    for item in disruptions or []:
        if not isinstance(item, dict):
            continue
        text = _message(item)
        if text and (not line or line.casefold() in text.casefold()):
            notes.append(text[:240])
    return notes


def _message(item: Mapping[str, Any]) -> str:
    messages = item.get("messages") if isinstance(item.get("messages"), list) else []
    if messages and isinstance(messages[0], dict):
        return str(messages[0].get("text") or "")
    return ""


def _clock(value: str) -> str:
    if "T" in value and len(value) >= 13:
        return f"{value[9:11]}:{value[11:13]}"
    return value
