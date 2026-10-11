"""Météo OpenWeather. current pour maintenant, forecast pour les jours."""

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from maria_core.capabilities import Capability, Context, Result, Risk
from maria_core.capabilities.http import HttpClient, HttpError, parse_json, with_query
from maria_core.plugins import PluginHost
from maria_core.ui.widgets import Rendered

_PARIS = ZoneInfo("Europe/Paris")
_CURRENT = "https://api.openweathermap.org/data/2.5/weather"
_FORECAST = "https://api.openweathermap.org/data/2.5/forecast"
_WEEKDAYS = {
    "lundi": 0,
    "mardi": 1,
    "mercredi": 2,
    "jeudi": 3,
    "vendredi": 4,
    "samedi": 5,
    "dimanche": 6,
}


NAME = "weather"


def setup(app: PluginHost) -> None:
    app.capabilities.register(weather_capability(app.http, app.settings.openweathermap_api_key))
    app.widgets.register("get_weather", render_weather)


def weather_capability(http: HttpClient, api_key: str) -> Capability:
    async def run(_context: Context, args: Mapping[str, Any]) -> Result:
        city = str(args["city"]).strip()
        kind = str(args["type"])
        try:
            if kind == "forecast":
                data = await _get(http, api_key, _FORECAST, city)
                payload = _forecast(city, data, str(args.get("target_date") or ""))
            else:
                data = await _get(http, api_key, _CURRENT, city)
                payload = _current(data)
        except (ValueError, HttpError) as exc:
            return Result(ok=False, data={}, error=str(exc))
        return Result(ok=True, data=payload, widget="get_weather")

    return Capability(
        name="get_weather",
        description=(
            "Météo d'une ville. type=current pour maintenant, type=forecast pour les jours. "
            "target_date : demain, un jour (lundi), ou YYYY-MM-DD. Vide : les cinq jours."
        ),
        parameters={
            "type": "object",
            "properties": {
                "city": {"type": "string"},
                "type": {"type": "string", "enum": ["current", "forecast"]},
                "target_date": {"type": "string"},
            },
            "required": ["city", "type"],
        },
        risk=Risk.EXTERNAL,
        run=run,
        requires=frozenset({"OPENWEATHERMAP_API_KEY"}),
    )


def render_weather(data: Mapping[str, Any]) -> Rendered:
    days = data.get("days") or []
    tabs = tuple(
        (str(item["label"]), str(item["text"]))
        for item in days
        if isinstance(item, dict) and item.get("label") and item.get("text")
    )
    return Rendered(str(data.get("summary") or ""), tabs)


async def _get(http: HttpClient, api_key: str, url: str, city: str) -> dict[str, Any]:
    response = await http.request(
        "GET",
        with_query(url, {"q": city, "units": "metric", "lang": "fr", "appid": api_key}),
    )
    payload = parse_json(response)
    if not isinstance(payload, dict) or payload.get("cod") in {404, "404"}:
        raise ValueError(f"Ville introuvable : {city}.")
    return payload


def _current(data: Mapping[str, Any]) -> dict[str, Any]:
    weather = _description(data)
    main = data.get("main") if isinstance(data.get("main"), dict) else {}
    temp = main.get("temp")
    feels = main.get("feels_like")
    name = str(data.get("name") or "")
    summary = f"{name} : {weather}, {temp}°C (ressenti {feels}°C)."
    return {"city": name, "kind": "current", "summary": summary, "days": []}


def _forecast(city: str, data: Mapping[str, Any], target: str) -> dict[str, Any]:
    zone = timezone_of(data)
    grouped = _by_day(data.get("list") or [], zone)
    wanted = _target_day(target, datetime.now(_PARIS).date())
    if wanted is not None:
        text = grouped.get(wanted.isoformat())
        if text is None:
            raise ValueError(f"Pas de prévision pour le {wanted.isoformat()}.")
        return {
            "city": city,
            "kind": "forecast",
            "summary": f"{city} le {wanted.isoformat()} : {text}",
            "days": [],
        }
    days = [
        {"label": day[5:], "text": f"{city} le {day} : {text}"}
        for day, text in list(grouped.items())[:5]
    ]
    summary = days[0]["text"] if days else f"Pas de prévision pour {city}."
    return {"city": city, "kind": "forecast", "summary": summary, "days": days}


def timezone_of(data: Mapping[str, Any]) -> timedelta:
    city = data.get("city") if isinstance(data.get("city"), dict) else {}
    return timedelta(seconds=int(city.get("timezone") or 0))


def _by_day(entries: list[Any], offset: timedelta) -> dict[str, str]:
    grouped: dict[str, list[str]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or "dt" not in entry:
            continue
        moment = datetime.fromtimestamp(int(entry["dt"]), UTC) + offset
        grouped.setdefault(moment.date().isoformat(), []).append(
            f"{moment:%H:%M} {_description(entry)} {entry.get('main', {}).get('temp')}°C"
        )
    return {day: " ; ".join(lines[:4]) for day, lines in grouped.items()}


def _description(entry: Mapping[str, Any]) -> str:
    weather = entry.get("weather")
    if isinstance(weather, list) and weather and isinstance(weather[0], dict):
        return str(weather[0].get("description") or "")
    return ""


def _target_day(raw: str, today: Any) -> Any:
    text = raw.strip().casefold()
    if not text:
        return None
    if text == "demain":
        return today + timedelta(days=1)
    if text in _WEEKDAYS:
        delta = (_WEEKDAYS[text] - today.weekday()) % 7
        return today + timedelta(days=delta or 7)
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None
