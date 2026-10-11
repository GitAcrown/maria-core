"""Fiche Steam Store. Pas de clé."""

from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

from maria_core.capabilities import Capability, Context, Result, Risk
from maria_core.capabilities.http import HttpClient, HttpError, parse_json, with_query
from maria_core.plugins import PluginHost

_SEARCH = "https://store.steampowered.com/api/storesearch/"
_DETAILS = "https://store.steampowered.com/api/appdetails"


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
        description="Fiche Steam : prix, description courte. Passe le nom le plus précis possible.",
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        risk=Risk.EXTERNAL,
        run=run,
    )


def render_game(data: Mapping[str, Any]) -> str:
    if not data.get("name"):
        return ""
    price = data.get("price") or "prix inconnu"
    return f"{data['name']} — {price}\n{data.get('description', '')}".strip()


async def _find(http: HttpClient, query: str) -> dict[str, str] | None:
    response = await http.request(
        "GET",
        with_query(_SEARCH, {"term": query, "l": "french", "cc": "FR"}),
    )
    payload = parse_json(response)
    items = payload.get("items") if isinstance(payload, dict) else None
    if not items or not isinstance(items[0], dict):
        return None
    app_id = str(items[0].get("id") or "")
    name = str(items[0].get("name") or query)
    details = await _details(http, app_id)
    return {"name": name, "app_id": app_id, **details}


async def _details(http: HttpClient, app_id: str) -> dict[str, str]:
    if not app_id:
        return {"price": "", "description": ""}
    response = await http.request("GET", f"{_DETAILS}?appids={quote(app_id)}&l=french&cc=FR")
    payload = parse_json(response)
    block = payload.get(app_id) if isinstance(payload, dict) else None
    data = block.get("data") if isinstance(block, dict) else None
    if not isinstance(data, dict):
        return {"price": "", "description": ""}
    price = data.get("price_overview") if isinstance(data.get("price_overview"), dict) else {}
    return {
        "price": str(price.get("final_formatted") or ("gratuit" if data.get("is_free") else "")),
        "description": str(data.get("short_description") or "")[:500],
    }
