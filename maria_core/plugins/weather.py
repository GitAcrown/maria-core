"""Météo OpenWeather. current pour maintenant, forecast pour les jours."""

from collections import Counter
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from maria_core.capabilities import Capability, Context, Result, Risk
from maria_core.capabilities.http import HttpClient, HttpError, parse_json, with_query
from maria_core.plugins import PluginHost
from maria_core.ui.widgets import Rendered, card, footer, heading, separator, text

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
_SHORT = ("lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim.")
_ICONS = {
    "01": "☀️",
    "02": "🌤️",
    "03": "⛅",
    "04": "☁️",
    "09": "🌧️",
    "10": "🌦️",
    "11": "⛈️",
    "13": "❄️",
    "50": "🌫️",
}
_DIRECTIONS = ("N", "NE", "E", "SE", "S", "SO", "O", "NO")
_BLUE = 0x3B82F6

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
                payload = forecast(city, data, str(args.get("target_date") or ""))
            else:
                payload = current(await _get(http, api_key, _CURRENT, city))
        except (ValueError, HttpError) as exc:
            return Result(ok=False, data={}, error=str(exc))
        return Result(ok=True, data=payload, widget="get_weather")

    return Capability(
        name="get_weather",
        description=(
            "Météo d'une ville. type=current pour maintenant, type=forecast pour les jours. "
            "target_date : demain, un jour (lundi), ou YYYY-MM-DD. Vide : les cinq jours. "
            "Ville absente : celle du PROFIL de la personne."
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
    if data.get("kind") == "current":
        details = (
            f"💨 **{data.get('wind_kmh')} km/h** {data.get('wind_dir', '')}  ·  "
            f"💧 **{data.get('humidity')}%**  ·  🌡 {data.get('pressure')} hPa"
        )
        built = card(
            heading(f"{data.get('emoji', '')} {data.get('city')}".strip()),
            separator(),
            text(
                f"# {data.get('temp')}°C\n-# {data.get('description')}  ·  ressenti "
                f"**{data.get('feels')}°C**  ·  {data.get('min')}° / {data.get('max')}°"
            ),
            text(details),
            footer("OpenWeather"),
            accent=_BLUE,
        )
        return Rendered(cards=(built,), note=str(data.get("summary") or ""))
    days = [item for item in data.get("days") or [] if isinstance(item, dict)]
    lines = [
        f"**{item['label']}**  {item['emoji']}  **{item['max']}°** / {item['min']}°  ·  "
        f"{item['description']}"
        for item in days
    ]
    span = "prévisions" if len(days) != 1 else str(days[0]["label"])
    built = card(
        heading(f"{data.get('city')} — {span}"),
        separator(),
        text("\n".join(lines)),
        footer("OpenWeather"),
        accent=_BLUE,
    )
    return Rendered(cards=(built,), note=str(data.get("summary") or ""))


def current(data: Mapping[str, Any]) -> dict[str, Any]:
    weather = _first_weather(data)
    main = data.get("main") if isinstance(data.get("main"), dict) else {}
    wind = data.get("wind") if isinstance(data.get("wind"), dict) else {}
    country = str((data.get("sys") or {}).get("country") or "")
    city = str(data.get("name") or "")
    payload = {
        "kind": "current",
        "city": f"{city}, {country}" if country else city,
        "emoji": _ICONS.get(str(weather.get("icon") or "01d")[:2], ""),
        "description": str(weather.get("description") or "").capitalize(),
        "temp": _round(main.get("temp")),
        "feels": _round(main.get("feels_like")),
        "min": _round(main.get("temp_min")),
        "max": _round(main.get("temp_max")),
        "humidity": main.get("humidity"),
        "pressure": main.get("pressure"),
        "wind_kmh": _round((wind.get("speed") or 0) * 3.6),
        "wind_dir": _DIRECTIONS[int(((wind.get("deg") or 0) + 22.5) // 45) % 8],
    }
    payload["summary"] = (
        f"{payload['city']} : {payload['description']}, {payload['temp']}°C (ressenti "
        f"{payload['feels']}°C), vent {payload['wind_kmh']} km/h, humidité {payload['humidity']}%."
    )
    return payload


def forecast(city: str, data: Mapping[str, Any], target: str) -> dict[str, Any]:
    days = _days(data.get("list") or [], timezone_of(data))
    wanted = _target_day(target, datetime.now(_PARIS).date())
    if wanted is not None:
        days = [item for item in days if item["date"] == wanted.isoformat()]
        if not days:
            raise ValueError(f"Pas de prévision pour le {wanted.isoformat()} (5 jours maximum).")
    days = days[:5]
    summary = " ; ".join(
        f"{item['label']} {item['description']} {item['min']}°/{item['max']}°" for item in days
    )
    return {"kind": "forecast", "city": city, "days": days, "summary": f"{city} : {summary}"}


def timezone_of(data: Mapping[str, Any]) -> timedelta:
    city = data.get("city") if isinstance(data.get("city"), dict) else {}
    return timedelta(seconds=int(city.get("timezone") or 0))


def _days(entries: list[Any], offset: timedelta) -> list[dict[str, Any]]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for entry in entries:
        if isinstance(entry, dict) and "dt" in entry:
            moment = datetime.fromtimestamp(int(entry["dt"]), UTC) + offset
            grouped.setdefault(moment.date().isoformat(), []).append(entry)
    return [_day(day, items) for day, items in grouped.items()]


def _day(day: str, items: list[Mapping[str, Any]]) -> dict[str, Any]:
    temps = [float((item.get("main") or {}).get("temp") or 0) for item in items]
    icons = [str(_first_weather(item).get("icon") or "01d") for item in items]
    daytime = [icon for icon in icons if icon.endswith("d")] or icons
    descriptions = [str(_first_weather(item).get("description") or "") for item in items]
    parsed = date.fromisoformat(day)
    return {
        "date": day,
        "label": f"{_SHORT[parsed.weekday()]} {parsed:%d/%m}",
        "emoji": _ICONS.get(Counter(daytime).most_common(1)[0][0][:2], ""),
        "max": round(max(temps)),
        "min": round(min(temps)),
        "description": Counter(descriptions).most_common(1)[0][0].capitalize(),
    }


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


def _first_weather(entry: Mapping[str, Any]) -> Mapping[str, Any]:
    weather = entry.get("weather")
    if isinstance(weather, list) and weather and isinstance(weather[0], dict):
        return weather[0]
    return {}


def _round(raw: object) -> int | None:
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        return None
    return round(raw)


def _target_day(raw: str, today: date) -> date | None:
    value = raw.strip().casefold()
    if not value:
        return None
    if value in {"aujourd'hui", "aujourdhui", "today"}:
        return today
    if value in {"demain", "tomorrow"}:
        return today + timedelta(days=1)
    if value in {"après-demain", "apres-demain"}:
        return today + timedelta(days=2)
    if value in _WEEKDAYS:
        delta = (_WEEKDAYS[value] - today.weekday()) % 7
        return today + timedelta(days=delta or 7)
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None
