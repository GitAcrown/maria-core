"""Client HTTP minimal. Les tests passent un faux, les capacités n'ouvrent rien d'autre."""

import asyncio
import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

_MAX_BYTES = 1_048_576
_USER_AGENT = "Maria/0.1"


class HttpError(Exception):
    """Réseau indisponible, schéma refusé ou réponse trop grosse."""


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status: int
    body: bytes
    headers: Mapping[str, str]


class HttpClient(Protocol):
    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
        timeout: float = 15,
        max_bytes: int = _MAX_BYTES,
    ) -> HttpResponse: ...


class UrllibHttpClient:
    """Appels bloquants hors de la boucle. Pas de redirection : l'appelant redemande."""

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
        timeout: float = 15,
        max_bytes: int = _MAX_BYTES,
    ) -> HttpResponse:
        return await asyncio.to_thread(
            _request,
            method,
            url,
            dict(headers or {}),
            body,
            timeout,
            max_bytes,
        )


def parse_json(response: HttpResponse) -> Any:
    if not 200 <= response.status < 300:
        raise ValueError(f"HTTP {response.status}")
    try:
        return json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Réponse illisible.") from exc


def with_query(url: str, params: Mapping[str, str]) -> str:
    return f"{url}?{urllib.parse.urlencode(params)}"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def http_error_302(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
    ) -> Any:
        raise urllib.error.HTTPError(req.full_url, code, msg, headers, fp)

    http_error_301 = http_error_303 = http_error_307 = http_error_308 = http_error_302


def _request(
    method: str,
    url: str,
    headers: dict[str, str],
    body: bytes | None,
    timeout: float,
    max_bytes: int,
) -> HttpResponse:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise HttpError("Seuls http et https sont acceptés.")
    headers.setdefault("User-Agent", _USER_AGENT)
    request = urllib.request.Request(url, data=body, headers=headers, method=method.upper())
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=timeout) as response:
            return _pack(response.status, response.headers, response.read(max_bytes + 1), max_bytes)
    except urllib.error.HTTPError as exc:
        payload = exc.read(max_bytes + 1) if exc.fp is not None else b""
        return _pack(exc.code, exc.headers, payload, max_bytes)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise HttpError(str(exc)) from exc


def _pack(status: int, headers: Any, payload: bytes, max_bytes: int) -> HttpResponse:
    if len(payload) > max_bytes:
        raise HttpError("Réponse trop volumineuse.")
    pairs = dict(headers.items()) if headers is not None else {}
    return HttpResponse(
        status=status, body=payload, headers={str(k): str(v) for k, v in pairs.items()}
    )
