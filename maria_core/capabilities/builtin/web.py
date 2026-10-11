"""Recherche, lecture de page et images. Brave pour chercher, la page elle-même pour lire."""

import asyncio
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urlparse

from maria_core.capabilities.base import Capability, Context, Result, Risk, Source
from maria_core.capabilities.http import HttpClient, HttpError, parse_json, with_query
from maria_core.capabilities.net import assert_public_host, html_to_text, safe_url
from maria_core.ui.render import split_message

_SEARCH = "https://api.search.brave.com/res/v1/web/search"
_IMAGES = "https://api.search.brave.com/res/v1/images/search"
_PAGE_CHARS = 4000
type Resolver = Callable[[str], None]


def web_capabilities(
    http: HttpClient,
    api_key: str,
    *,
    resolve: Resolver = assert_public_host,
) -> tuple[Capability, ...]:
    return (
        _tool("search_web", _SEARCH_TEXT, _search_schema(), _search(http, api_key)),
        _tool("read_web_page", _READ_TEXT, _read_schema(), _read(http, resolve)),
        _tool("search_images", _IMAGE_TEXT, _image_schema(), _images(http, api_key)),
    )


def render_search(data: Mapping[str, Any]) -> str:
    lines = [
        f"- {item.get('title', '')} — {item.get('url', '')}"
        for item in data.get("results") or []
        if isinstance(item, dict)
    ]
    return "\n".join(lines)


def render_images(data: Mapping[str, Any]) -> str:
    lines = [
        f"- {item.get('title', '')}\n{item.get('url', '')}"
        for item in data.get("images") or []
        if isinstance(item, dict)
    ]
    return "\n".join(lines)


def _tool(
    name: str,
    description: str,
    parameters: dict[str, Any],
    run: Callable[[Context, Mapping[str, Any]], Any],
) -> Capability:
    return Capability(
        name=name,
        description=description,
        parameters=parameters,
        risk=Risk.EXTERNAL,
        run=run,
        requires=frozenset({"BRAVE_API_KEY"}) if name != "read_web_page" else frozenset(),
    )


def _search(http: HttpClient, api_key: str) -> Callable[[Context, Mapping[str, Any]], Any]:
    async def run(_context: Context, args: Mapping[str, Any]) -> Result:
        payload = await _brave(
            http,
            _SEARCH,
            api_key,
            {"q": str(args["query"]), "count": "5", "search_lang": _lang(args)},
        )
        if isinstance(payload, str):
            return Result(ok=False, data={}, error=payload)
        hits = _web_hits(payload)
        sources = tuple(Source(title=item["title"], url=item["url"]) for item in hits)
        return Result(ok=True, data={"results": hits}, sources=sources, widget="search_web")

    return run


def _images(http: HttpClient, api_key: str) -> Callable[[Context, Mapping[str, Any]], Any]:
    async def run(_context: Context, args: Mapping[str, Any]) -> Result:
        count = int(args.get("count") or 1)
        payload = await _brave(
            http,
            _IMAGES,
            api_key,
            {"q": str(args["query"]), "count": str(count), "search_lang": _lang(args)},
        )
        if isinstance(payload, str):
            return Result(ok=False, data={}, error=payload)
        images = _image_hits(payload)[:count]
        if not images:
            return Result(ok=False, data={}, error="Aucune image trouvée.")
        return Result(ok=True, data={"images": images}, widget="search_images")

    return run


def _read(
    http: HttpClient,
    resolve: Resolver,
) -> Callable[[Context, Mapping[str, Any]], Any]:
    async def run(_context: Context, args: Mapping[str, Any]) -> Result:
        try:
            url = safe_url(str(args["url"]))
            await asyncio.to_thread(resolve, urlparse(url).hostname or "")
            response = await http.request("GET", url, timeout=15, max_bytes=1_000_000)
            raw = response.body.decode("utf-8", errors="replace")
            text = await asyncio.to_thread(html_to_text, raw)
        except (ValueError, HttpError, UnicodeError) as exc:
            return Result(ok=False, data={}, error=str(exc) or "Lecture impossible.")
        if response.status != 200 or not text:
            return Result(ok=False, data={}, error=f"Page illisible (HTTP {response.status}).")
        pages = split_message(text, limit=_PAGE_CHARS)
        index = _chunk(args.get("chunk"), len(pages))
        return Result(
            ok=True,
            data={
                "url": url,
                "content": pages[index],
                "chunk": index,
                "total_chunks": len(pages),
                "next_chunk": index + 1 if index + 1 < len(pages) else None,
            },
        )

    return run


async def _brave(
    http: HttpClient,
    url: str,
    api_key: str,
    params: dict[str, str],
) -> Any:
    try:
        response = await http.request(
            "GET",
            with_query(url, params),
            headers={"X-Subscription-Token": api_key, "Accept": "application/json"},
        )
        return parse_json(response)
    except (ValueError, HttpError) as exc:
        return str(exc)


def _web_hits(payload: Mapping[str, Any]) -> list[dict[str, str]]:
    web = payload.get("web")
    results = web.get("results") if isinstance(web, dict) else None
    hits = []
    for item in results:
        if not isinstance(item, dict) or not item.get("url"):
            continue
        hits.append(
            {
                "title": str(item.get("title") or item["url"]),
                "url": str(item["url"]),
                "snippet": str(item.get("description") or ""),
            }
        )
    return hits[:5]


def _image_hits(payload: Mapping[str, Any]) -> list[dict[str, str]]:
    hits = []
    for item in payload.get("results") or []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or (item.get("properties") or {}).get("url") or "")
        if url.startswith("http"):
            hits.append({"title": str(item.get("title") or ""), "url": url})
    return hits


def _lang(args: Mapping[str, Any]) -> str:
    lang = str(args.get("lang") or "fr").strip().lower()
    return lang or "fr"


def _chunk(raw: object, total: int) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int):
        return 0
    return max(0, min(raw, total - 1))


def _search_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Requête précise"},
            "lang": {"type": "string", "description": "Code langue, défaut fr"},
        },
        "required": ["query"],
    }


def _read_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL https complète"},
            "chunk": {"type": "integer", "description": "Morceau à lire, 0 au début"},
        },
        "required": ["url"],
    }


def _image_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Ce qu'il faut montrer"},
            "count": {"type": "integer", "minimum": 1, "maximum": 4},
            "lang": {"type": "string"},
        },
        "required": ["query"],
    }


_SEARCH_TEXT = (
    "Recherche web (actu, faits, dates, chiffres). Une requête par question. "
    "Si les extraits suffisent, réponds ; sinon read_web_page sur une URL. "
    "Les liens sont affichés sous la réponse : ne les répète pas en [s1]."
)
_READ_TEXT = (
    "Lit une URL déjà connue (recherche ou lien du message). "
    "Si next_chunk est présent, rappelle cet outil avec chunk=next_chunk. "
    "Pas pour YouTube (read_youtube)."
)
_IMAGE_TEXT = (
    "Cherche des images et les affiche. count entre 1 et 4, défaut 1. Un appel par sujet distinct."
)
