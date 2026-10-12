"""Données OpenWeather -> cartes, à l'identique de MARIA_R (actuel, semaine, jour par tranches)."""

from collections import Counter
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from maria_core.ui.widgets import Card, Rendered, card, footer, separator, text

PARIS = ZoneInfo("Europe/Paris")
_ICONS = {
    "01": "☀️",
    "02": "🌤️",
    "03": "⛅",
    "04": "☁️",
    "09": "🌦️",
    "10": "🌧️",
    "11": "⛈️",
    "13": "🌨️",
    "50": "🌫️",
}
_DAYS_FULL = ("Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche")
_DAYS_SHORT = ("Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim")
_WIND = ("N", "NE", "E", "SE", "S", "SO", "O", "NO")
_PERIODS = (
    ("🌅 Matin", 6, 12),
    ("☀️ Après-midi", 12, 18),
    ("🌆 Soir", 18, 22),
    ("🌙 Nuit", 0, 6),
)


def current(raw: Mapping[str, Any]) -> dict[str, Any]:
    weather = _weather(raw)
    main = raw.get("main") or {}
    wind = raw.get("wind") or {}
    return {
        "kind": "current",
        "city": _city(
            str(raw.get("name") or "?"), str((raw.get("sys") or {}).get("country") or "")
        ),
        "emoji": emoji(str(weather.get("icon") or "01d")),
        "description": str(weather.get("description") or "").capitalize(),
        "temp": round(float(main.get("temp") or 0)),
        "feels": round(float(main.get("feels_like") or 0)),
        "min": round(float(main.get("temp_min") or 0)),
        "max": round(float(main.get("temp_max") or 0)),
        "humidity": main.get("humidity", 0),
        "pressure": main.get("pressure", 0),
        "wind_kmh": round(float(wind.get("speed") or 0) * 3.6),
        "wind_dir": wind_dir(float(wind.get("deg") or 0)),
        "visibility_km": round(float(raw.get("visibility") or 10000) / 1000, 1),
    }


def week(city: str, raw: Mapping[str, Any]) -> dict[str, Any]:
    full = _city(city, str((raw.get("city") or {}).get("country") or ""))
    days = []
    for key, slots in list(_by_day(raw).items())[:5]:
        moment = date.fromisoformat(key)
        temps = [float(slot["main"]["temp"]) for slot in slots]
        days.append(
            {
                "date": key,
                "label": f"{_DAYS_SHORT[moment.weekday()]} {moment:%d/%m}",
                "emoji": emoji(_day_icon(slots)),
                "max": round(max(temps)),
                "min": round(min(temps)),
                "description": _common([_desc(slot) for slot in slots]).capitalize(),
            }
        )
    return {"kind": "week", "city": full, "days": days}


def day(city: str, raw: Mapping[str, Any], target: date, today: date) -> dict[str, Any] | None:
    slots = _by_day(raw).get(target.isoformat())
    if not slots:
        return None
    temps = [float(slot["main"]["temp"]) for slot in slots]
    winds = [slot.get("wind") or {} for slot in slots]
    return {
        "kind": "day",
        "city": _city(city, str((raw.get("city") or {}).get("country") or "")),
        "label": _day_label(target, today),
        "date": target.isoformat(),
        "emoji": emoji(_day_icon(slots)),
        "periods": _periods(slots),
        "max": round(max(temps)),
        "min": round(min(temps)),
        "humidity": round(sum(float(s["main"].get("humidity") or 0) for s in slots) / len(slots)),
        "wind_kmh": round(sum(float(w.get("speed") or 0) for w in winds) / len(winds) * 3.6),
        "wind_dir": wind_dir(sum(float(w.get("deg") or 0) for w in winds) / len(winds)),
        "description": _common([_desc(slot) for slot in slots]).capitalize(),
    }


def render_weather(data: Mapping[str, Any]) -> Rendered:
    kind = data.get("kind")
    if kind == "current":
        return Rendered(cards=(_current_card(data),), note=summary(data))
    if kind == "day":
        return Rendered(cards=(_day_card(data),), note=summary(data))
    return Rendered(cards=(_week_card(data),), note=summary(data))


def summary(data: Mapping[str, Any]) -> str:
    kind = data.get("kind")
    if kind == "current":
        return (
            f"{data['city']} : {data['description']}, {data['temp']}°C (ressenti "
            f"{data['feels']}°C), {data['min']}°/{data['max']}°, vent {data['wind_kmh']} km/h, "
            f"humidité {data['humidity']}%."
        )
    if kind == "day":
        periods = " ; ".join(f"{p['label']} {p['temp']}°C" for p in data.get("periods") or [])
        return (
            f"{data['city']}, {data['label']} : {data['description']}, {data['max']}°/"
            f"{data['min']}°, {periods}."
        )
    days = " ; ".join(
        f"{d['label']} {d['description']} {d['max']}°/{d['min']}°" for d in data.get("days") or []
    )
    return f"{data.get('city')} sur 5 jours : {days}."


def emoji(icon: str) -> str:
    return _ICONS.get(icon[:2], "🌡️")


def wind_dir(degrees: float) -> str:
    return _WIND[round(degrees / 45) % 8]


def _current_card(data: Mapping[str, Any]) -> Card:
    details = (
        f"💨 **{data['wind_kmh']} km/h** {data['wind_dir']}  ·  💧 **{data['humidity']}%**"
        f"  ·  👁 {data['visibility_km']} km  ·  🌡 {data['pressure']} hPa"
    )
    return card(
        text(f"## {data['emoji']} {data['city']}"),
        separator(wide=True),
        text(
            f"# {data['temp']}°C\n-# {data['description']}  ·  ressenti **{data['feels']}°C**"
            f"  ·  {data['min']}° / {data['max']}°"
        ),
        separator(),
        text(details),
        footer(f"{_stamp()} · OWM"),
    )


def _week_card(data: Mapping[str, Any]) -> Card:
    blocks = [text(f"## {data.get('city')} — Prévisions 5 jours"), separator(wide=True)]
    days = [item for item in data.get("days") or [] if isinstance(item, dict)]
    for index, item in enumerate(days):
        blocks.append(
            text(
                f"**{item['label']}**  {item['emoji']}  **{item['max']}°** / {item['min']}°"
                f"  ·  {item['description']}"
            )
        )
        if index < len(days) - 1:
            blocks.append(separator())
    blocks.append(footer(f"{_stamp()} · OWM"))
    return card(*blocks)


def _day_card(data: Mapping[str, Any]) -> Card:
    periods = [f"{p['label']}  {p['emoji']}  **{p['temp']}°C**" for p in data.get("periods") or []]
    return card(
        text(f"## {data['emoji']} {data['label']} · {data['city']}"),
        separator(wide=True),
        text("\n".join(periods)) if periods else None,
        separator() if periods else None,
        text(
            f"🌡 **{data['max']}°** / {data['min']}°  ·  💧 {data['humidity']}%"
            f"  ·  💨 {data['wind_kmh']} km/h {data['wind_dir']}"
        ),
        footer(f"{_stamp()} · OWM"),
    )


def _by_day(raw: Mapping[str, Any]) -> dict[str, list[Mapping[str, Any]]]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for item in raw.get("list") or []:
        if isinstance(item, dict) and "dt" in item and isinstance(item.get("main"), dict):
            moment = datetime.fromtimestamp(int(item["dt"]), tz=PARIS)
            grouped.setdefault(moment.date().isoformat(), []).append(item)
    return grouped


def _periods(slots: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    found = []
    for label, start, end in _PERIODS:
        chosen = [slot for slot in slots if _in_period(_hour(slot), start, end)]
        if not chosen:
            continue
        temps = [float(slot["main"]["temp"]) for slot in chosen]
        icon = _common([str(_weather(slot).get("icon") or "01d") for slot in chosen])
        found.append({"label": label, "emoji": emoji(icon), "temp": round(sum(temps) / len(temps))})
    return found


def _in_period(hour: int, start: int, end: int) -> bool:
    if start < end:
        return start <= hour < end
    return hour < end or hour >= 22


def _hour(slot: Mapping[str, Any]) -> int:
    return datetime.fromtimestamp(int(slot["dt"]), tz=PARIS).hour


def _day_icon(slots: list[Mapping[str, Any]]) -> str:
    icons = [str(_weather(slot).get("icon") or "01d") for slot in slots]
    daytime = [icon for icon in icons if icon.endswith("d")]
    return _common(daytime or icons)


def _day_label(target: date, today: date) -> str:
    if target == today:
        return "Aujourd'hui"
    if target == today + timedelta(days=1):
        return "Demain"
    return f"{_DAYS_FULL[target.weekday()]} {target:%d/%m}"


def _weather(entry: Mapping[str, Any]) -> Mapping[str, Any]:
    weather = entry.get("weather")
    if isinstance(weather, list) and weather and isinstance(weather[0], dict):
        return weather[0]
    return {}


def _desc(slot: Mapping[str, Any]) -> str:
    return str(_weather(slot).get("description") or "")


def _common(values: list[str]) -> str:
    return Counter(values).most_common(1)[0][0] if values else ""


def _city(name: str, country: str) -> str:
    return f"{name}, {country}" if country else name


def _stamp() -> str:
    return datetime.now(UTC).astimezone(PARIS).strftime("%H:%M")
