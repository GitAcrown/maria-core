"""Fiche Steam Store, mise en page comme dans MARIA_R. Pas de clé."""

from collections.abc import Mapping
from typing import Any
from urllib.parse import quote as escape

from maria_core.capabilities import Capability, Context, Result, Risk
from maria_core.capabilities.http import HttpClient, HttpError, parse_json, with_query
from maria_core.plugins import PluginHost
from maria_core.ui.emojis import GAMES
from maria_core.ui.widgets import (
    Rendered,
    card,
    footer,
    joined,
    quote,
    separator,
    text,
    thumbnail,
)

_SEARCH = "https://store.steampowered.com/api/storesearch/"
_DETAILS = "https://store.steampowered.com/api/appdetails"
_REVIEWS = "https://store.steampowered.com/appreviews/{}"
_HEADER = "https://cdn.akamai.steamstatic.com/steam/apps/{}/header.jpg"
_STORE = "https://store.steampowered.com/app/{}"
_REVIEW_MAP = {
    "Overwhelmingly Positive": ("🥇", "Acclamé"),
    "Very Positive": ("👍", "Très positif"),
    "Positive": ("👍", "Positif"),
    "Mostly Positive": ("🙂", "Plutôt positif"),
    "Mixed": ("😐", "Mitigé"),
    "Mostly Negative": ("👎", "Plutôt négatif"),
    "Negative": ("👎", "Négatif"),
    "Very Negative": ("💀", "Très négatif"),
    "Overwhelmingly Negative": ("💀", "Descendu en flammes"),
}

NAME = "steam"


def setup(app: PluginHost) -> None:
    app.capabilities.register(game_capability(app.http))
    app.widgets.register("search_game", render_game)


def game_capability(http: HttpClient) -> Capability:
    async def run(_context: Context, args: Mapping[str, Any]) -> Result:
        query = str(args["query"]).strip()
        try:
            game = await _find(http, query)
        except (ValueError, HttpError) as exc:
            return Result(ok=False, data={}, error=str(exc))
        if game is None:
            return Result(ok=False, data={}, error=f"Jeu introuvable sur Steam : {query}.")
        return Result(ok=True, data=game, widget="search_game")

    return Capability(
        name="search_game",
        description=(
            "Fiche Steam d'un jeu (prix, soldes, avis, description, genres, développeur). Nom "
            "exact ou le plus précis ; nom flou : search_web d'abord. Un appel par jeu."
        ),
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        risk=Risk.EXTERNAL,
        cache_s=3600,
        run=run,
    )


def render_game(data: Mapping[str, Any]) -> Rendered:
    if not data.get("name"):
        return Rendered()
    app_id = str(data.get("app_id") or "")
    lines = [str(data.get("price_line") or "*Prix inconnu.*")]
    if data.get("review"):
        lines.append(f"**Steam** · {data['review']}")
    description = str(data.get("description") or "").strip()
    if len(description) > 300:
        description = description[:300].rstrip(" ,;:") + "…"
    meta = joined("Jeu", *(data.get("genres") or [])[:3])
    link = f"[Steam](<{_STORE.format(app_id)}>)" if app_id else ""
    built = card(
        text(f"## {GAMES} {data['name']}\n-# {meta}"),
        separator(wide=True),
        thumbnail("\n".join(lines), _HEADER.format(app_id) if app_id else ""),
        text(quote(description)) if description else None,
        footer(joined(data.get("developer"), link)),
    )
    note = f"{data['name']} : {data.get('price') or 'prix inconnu'}. {data.get('review_label', '')}"
    return Rendered(cards=(built,), note=note.strip())


async def _find(http: HttpClient, query: str) -> dict[str, Any] | None:
    payload = parse_json(
        await http.request("GET", with_query(_SEARCH, {"term": query, "l": "french", "cc": "FR"}))
    )
    items = payload.get("items") if isinstance(payload, dict) else None
    if not items or not isinstance(items[0], dict):
        return None
    app_id = str(items[0].get("id") or "")
    name = str(items[0].get("name") or query)
    details = await _details(http, app_id)
    review = await _review(http, app_id)
    return {"name": name, "app_id": app_id, **details, **review}


async def _details(http: HttpClient, app_id: str) -> dict[str, Any]:
    if not app_id:
        return {}
    response = await http.request("GET", f"{_DETAILS}?appids={escape(app_id)}&l=french&cc=FR")
    payload = parse_json(response)
    block = payload.get(app_id) if isinstance(payload, dict) else None
    data = block.get("data") if isinstance(block, dict) else None
    if not isinstance(data, dict):
        return {}
    price = data.get("price_overview") if isinstance(data.get("price_overview"), dict) else {}
    genres = [str(g.get("description")) for g in data.get("genres") or [] if isinstance(g, dict)]
    developers = [str(item) for item in data.get("developers") or []]
    return {
        "price": "Gratuit" if data.get("is_free") else str(price.get("final_formatted") or ""),
        "price_line": _price_line(bool(data.get("is_free")), price),
        "description": str(data.get("short_description") or "")[:500],
        "genres": genres[:3],
        "developer": developers[0] if developers else "",
    }


async def _review(http: HttpClient, app_id: str) -> dict[str, str]:
    """Avis Steam en une étiquette ; rien si l'appel échoue, la fiche reste affichable."""
    if not app_id:
        return {}
    url = with_query(
        _REVIEWS.format(escape(app_id)),
        {"json": "1", "language": "all", "purchase_type": "all", "num_per_page": "0"},
    )
    try:
        payload = parse_json(await http.request("GET", url))
    except (ValueError, HttpError):
        return {}
    summary = payload.get("query_summary") if isinstance(payload, dict) else None
    desc = str((summary or {}).get("review_score_desc") or "")
    icon, label = _REVIEW_MAP.get(desc, ("", ""))
    return {"review": f"{icon} {label}".strip(), "review_label": label} if label else {}


def _price_line(free: bool, price: Mapping[str, Any]) -> str:
    if free:
        return "**Gratuit**"
    final = price.get("final")
    if not isinstance(final, int):
        return str(price.get("final_formatted") or "Prix inconnu")
    discount = int(price.get("discount_percent") or 0)
    if not discount:
        return f"**{_euros(final)}**"
    initial = price.get("initial")
    was = f" ~~{_euros(initial)}~~" if isinstance(initial, int) else ""
    return f"**{_euros(final)}**{was}  🏷️ **-{discount}%**"


def _euros(cents: int) -> str:
    return f"{cents / 100:.2f} €"
