"""Lecture d'une page pour fetch_then. Les tests injectent leur propre fonction."""

import asyncio
from urllib.parse import urlparse

from maria_core.capabilities.http import HttpClient
from maria_core.capabilities.net import assert_public_host, html_to_text, safe_url
from maria_core.objectives.runner import Fetcher


def http_fetcher(http: HttpClient) -> Fetcher:
    async def fetch(url: str) -> str:
        safe = safe_url(url)
        await asyncio.to_thread(assert_public_host, urlparse(safe).hostname or "")
        response = await http.request("GET", safe, timeout=15, max_bytes=1_000_000)
        if response.status != 200:
            raise ValueError(f"Page illisible (HTTP {response.status}).")
        raw = response.body.decode("utf-8", errors="replace")
        return await asyncio.to_thread(html_to_text, raw)

    return fetch
