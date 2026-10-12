"""Lecture d'une page publique, redirections comprises. Chaque saut est revérifié."""

import asyncio
from collections.abc import Callable
from urllib.parse import urljoin, urlparse

from maria_core.capabilities.http import HttpClient, HttpError
from maria_core.capabilities.net import assert_public_host, html_to_text, safe_url

type Resolver = Callable[[str], None]

MAX_REDIRECTS = 5
_REDIRECTS = frozenset({301, 302, 303, 307, 308})


async def fetch_text(
    http: HttpClient,
    url: str,
    *,
    resolve: Resolver = assert_public_host,
    max_bytes: int = 1_000_000,
) -> tuple[str, str]:
    """(texte, URL finale). Lève ValueError si la page reste illisible."""
    current = safe_url(url)
    for _ in range(MAX_REDIRECTS + 1):
        await asyncio.to_thread(resolve, urlparse(current).hostname or "")
        try:
            response = await http.request("GET", current, timeout=15, max_bytes=max_bytes)
        except HttpError as exc:
            raise ValueError(str(exc) or "Lecture impossible.") from exc
        if response.status in _REDIRECTS:
            target = _header(response.headers, "location")
            if not target:
                raise ValueError(f"Redirection sans destination (HTTP {response.status}).")
            current = safe_url(urljoin(current, target))
            continue
        if response.status != 200:
            raise ValueError(f"Page illisible (HTTP {response.status}).")
        raw = response.body.decode(_charset(response.headers), errors="replace")
        text = await asyncio.to_thread(html_to_text, raw)
        if not text:
            raise ValueError("Page vide.")
        return text, current
    raise ValueError("Trop de redirections.")


def _header(headers: object, name: str) -> str:
    if not isinstance(headers, dict):
        return ""
    for key, value in headers.items():
        if str(key).lower() == name:
            return str(value)
    return ""


def _charset(headers: object) -> str:
    kind = _header(headers, "content-type").lower()
    if "charset=" in kind:
        charset = kind.split("charset=", 1)[1].split(";", 1)[0].strip()
        try:
            "".encode(charset)
        except LookupError:
            return "utf-8"
        return charset
    return "utf-8"
