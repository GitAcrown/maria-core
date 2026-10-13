"""Météo OpenWeather. current pour maintenant, forecast pour la semaine ou un jour précis."""

from collections.abc import Mapping
from datetime import date, datetime, timedelta
from typing import Any

from maria_core.capabilities import Capability, Context, Result, Risk
from maria_core.capabilities.http import HttpClient, HttpError, parse_json, with_query
from maria_core.plugins import PluginHost
from maria_core.plugins.weather_view import PARIS, current, day, render_weather, week

_CURRENT = "https://api.openweathermap.org/data/2.5/weather"
_FORECAST = "https://api.openweathermap.org/data/2.5/forecast"
_WEEKDAYS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")

NAME = "weather"


def setup(app: PluginHost) -> None:
    app.capabilities.register(weather_capability(app.http, app.settings.openweathermap_api_key))
    app.widgets.register("get_weather", render_weather)


def weather_capability(http: HttpClient, api_key: str) -> Capability:
    async def run(_context: Context, args: Mapping[str, Any]) -> Result:
        city = str(args["city"]).strip()
        try:
            if str(args["type"]) == "forecast":
                raw = await _get(http, api_key, _FORECAST, city)
                payload = forecast(city, raw, str(args.get("target_date") or ""))
            else:
                payload = current(await _get(http, api_key, _CURRENT, city))
        except (ValueError, HttpError) as exc:
            return Result(ok=False, data={}, error=str(exc))
        return Result(ok=True, data=payload, widget="get_weather")

    return Capability(
        name="get_weather",
        description=(
            "Météo d'une ville. type=current pour maintenant, type=forecast pour les jours. "
            "target_date : demain, un jour (lundi), ou YYYY-MM-DD ; vide : la semaine. "
            "Ville absente (« chez moi », « ma ville ») : celle du PROFIL ; sinon search_memory "
            "avant de demander."
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


def forecast(city: str, raw: Mapping[str, Any], target: str) -> dict[str, Any]:
    today = datetime.now(PARIS).date()
    wanted = target_day(target, today)
    if wanted is None:
        return week(city, raw)
    found = day(city, raw, wanted, today)
    if found is None:
        raise ValueError(f"Pas de prévision pour le {wanted.isoformat()} (5 jours maximum).")
    return found


def target_day(raw: str, today: date) -> date | None:
    value = raw.strip().casefold()
    if not value:
        return None
    if value in {"aujourd'hui", "aujourdhui", "auj", "today"}:
        return today
    if value in {"demain", "tomorrow"}:
        return today + timedelta(days=1)
    if value in {"après-demain", "apres-demain"}:
        return today + timedelta(days=2)
    if value in _WEEKDAYS:
        delta = (_WEEKDAYS.index(value) - today.weekday()) % 7
        return today + timedelta(days=delta or 7)
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


async def _get(http: HttpClient, api_key: str, url: str, city: str) -> dict[str, Any]:
    response = await http.request(
        "GET",
        with_query(url, {"q": city, "units": "metric", "lang": "fr", "appid": api_key}),
    )
    if response.status == 404:
        raise ValueError(f"Ville introuvable : {city}.")
    payload = parse_json(response)
    if not isinstance(payload, dict) or payload.get("cod") in {404, "404"}:
        raise ValueError(f"Ville introuvable : {city}.")
    return payload
