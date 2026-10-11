"""Client HTTP scripté."""

from collections.abc import Callable, Mapping

from maria_core.capabilities.http import HttpResponse

type Handler = Callable[[str, str, Mapping[str, str], bytes | None], HttpResponse]


class FakeHttp:
    def __init__(self, handler: Handler) -> None:
        self._handler = handler
        self.calls: list[tuple[str, str]] = []

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
        timeout: float = 15,
        max_bytes: int = 1_048_576,
    ) -> HttpResponse:
        self.calls.append((method, url))
        return self._handler(method, url, headers or {}, body)
