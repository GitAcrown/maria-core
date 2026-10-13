"""Registre d'outils : délai, risque, clés, et les capacités avec un faux HTTP."""

import asyncio
import json
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from maria_core.capabilities import Capability, CapabilityRegistry, Context, Result, Risk
from maria_core.capabilities.builtin.about import about_capability
from maria_core.capabilities.builtin.polls import poll_capability
from maria_core.capabilities.builtin.python_tool import python_capability, set_python
from maria_core.capabilities.builtin.sandbox import execute
from maria_core.capabilities.builtin.summary import summary_capability
from maria_core.capabilities.builtin.web import web_capabilities
from maria_core.capabilities.http import HttpResponse
from maria_core.capabilities.net import safe_url
from maria_core.capabilities.runner import available, invoke
from maria_core.config import Settings
from maria_core.db import Database
from maria_core.llm.types import ToolCall
from maria_core.plugins.football import football_capability
from maria_core.plugins.spotify import track_capability
from maria_core.plugins.steam import game_capability
from maria_core.plugins.tmdb import media_capability
from maria_core.plugins.transport import transport_capability
from maria_core.plugins.weather import render_weather, weather_capability
from maria_core.plugins.youtube import video_id, youtube_capability
from tests.http_fake import FakeHttp

_SCHEMA = {
    "type": "object",
    "properties": {"query": {"type": "string"}, "note": {"type": "string"}},
    "required": ["query"],
}


def _context(*, owner: bool = False, guild_id: int | None = 5) -> Context:
    return Context(
        user_id=7,
        guild_id=guild_id,
        channel_id=3,
        message_id=9,
        is_owner=owner,
        is_moderator=False,
        text="",
    )


def _json(payload: object, status: int = 200) -> HttpResponse:
    return HttpResponse(
        status=status,
        body=json.dumps(payload).encode(),
        headers={},
    )


async def _echo(_context: Context, args: Mapping[str, Any]) -> Result:
    return Result(ok=True, data={"query": args.get("query")})


def _capability(**overrides: object) -> Capability:
    values: dict[str, object] = {
        "name": "echo",
        "description": "Répète",
        "parameters": _SCHEMA,
        "risk": Risk.READ,
        "run": _echo,
    }
    values.update(overrides)
    return Capability(**values)  # type: ignore[arg-type]


def _database(tmp_path: Path) -> Database:
    database = Database(tmp_path / "maria.db")
    database.migrate()
    return database


async def test_missing_argument_and_timeout_become_results(tmp_path: Path) -> None:
    registry = CapabilityRegistry()
    registry.register(_capability())

    async def slow(_context: Context, _args: Mapping[str, Any]) -> Result:
        await asyncio.sleep(5)
        return Result(ok=True, data={})

    registry.register(
        _capability(name="slow", run=slow, timeout_s=0.05, parameters={"properties": {}})
    )
    settings = Settings.for_tests(tmp_path)
    database = _database(tmp_path)
    missing = await invoke(
        registry,
        settings,
        _context(),
        ToolCall(id="1", name="echo", arguments={}),
        database=database,
    )
    assert missing.ok is False
    assert "query" in missing.error
    timed = await invoke(
        registry,
        settings,
        _context(),
        ToolCall(id="2", name="slow", arguments={}),
        database=database,
    )
    assert timed.error == "Délai dépassé."
    rows = database.fetchall("SELECT name, ok FROM capability_calls ORDER BY id")
    assert [row["name"] for row in rows] == ["echo", "slow"]
    database.close()


async def test_python_is_open_to_everyone_and_a_server_can_switch_it_off(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    registry = CapabilityRegistry()
    registry.register(python_capability(database))
    settings = Settings.for_tests(tmp_path)
    call = ToolCall(id="1", name="run_python", arguments={"code": "1 + 1"})
    allowed = await invoke(registry, settings, _context(owner=False), call)
    assert allowed.ok is True
    assert allowed.data["result"] == 2
    set_python(database, 5, False, "2026-10-11T00:00:00+00:00")
    disabled = await invoke(registry, settings, _context(owner=True), call)
    assert "désactivé" in disabled.error
    database.close()


def test_sandbox_blocks_imports() -> None:
    assert "error" in execute("import os")
    assert execute("math.sqrt(4)")["result"] == 2


def test_private_and_credential_urls_are_refused() -> None:
    assert safe_url("https://example.com/a") == "https://example.com/a"
    for raw in (
        "http://127.0.0.1/",
        "http://localhost/x",
        "file:///tmp/a",
        "https://user:pw@example.com",
    ):
        try:
            safe_url(raw)
        except ValueError:
            continue
        raise AssertionError(raw)


async def test_web_search_reads_brave_and_a_page(tmp_path: Path) -> None:
    def handler(
        method: str, url: str, headers: Mapping[str, str], _body: bytes | None
    ) -> HttpResponse:
        if "web/search" in url:
            assert headers["X-Subscription-Token"] == "brave"
            return _json(
                {
                    "web": {
                        "results": [
                            {"title": "Actu", "url": "https://news.test", "description": "oui"}
                        ]
                    }
                }
            )
        return HttpResponse(
            status=200,
            body=b"<p>bonjour <b>tout</b> le monde</p><script>secret</script>",
            headers={},
        )

    http = FakeHttp(handler)
    registry = CapabilityRegistry()
    for capability in web_capabilities(http, "brave", resolve=lambda _host: None):
        registry.register(capability)
    settings = replace(Settings.for_tests(tmp_path), brave_api_key="brave")
    hidden = available(registry, Settings.for_tests(tmp_path))
    assert "search_web" not in {item.name for item in hidden}
    found = await invoke(
        registry,
        settings,
        _context(),
        ToolCall(id="1", name="search_web", arguments={"query": "maria"}),
    )
    assert found.ok is True
    assert found.data["results"][0]["url"] == "https://news.test"
    page = await invoke(
        registry,
        settings,
        _context(),
        ToolCall(id="2", name="read_web_page", arguments={"url": "https://news.test/a"}),
    )
    assert page.ok is True
    assert "bonjour tout le monde" in str(page.data["content"])
    assert "secret" not in str(page.data["content"])


async def test_summary_uses_the_transcript_and_a_focus() -> None:
    capability = summary_capability(
        lambda _channel: ("Léa: on mange des pâtes", "Noé: le bus est en retard"),
        lambda: None,
    )
    focused = await capability.run(_context(), {"focus": "ce qu'on mange"})
    assert focused.ok is True
    assert focused.data["count"] == 2
    assert focused.data["focus"] == "ce qu'on mange"
    elsewhere = await capability.run(_context(), {"channel_id": "999"})
    assert elsewhere.ok is False
    late = await capability.run(_context(), {"since": "25:00"})
    assert late.ok is False


async def test_about_lists_the_registered_tools() -> None:
    registry = CapabilityRegistry()
    registry.register(about_capability(registry))
    result = await registry.get("about_me").run(_context(), {"topic": "tools"})
    assert "about_me" in str(result.data["section"])


async def test_poll_is_posted_and_refuses_a_direct_message() -> None:
    posted: list[str] = []

    class _Poster:
        async def post(self, **kwargs: object) -> int:
            posted.append(str(kwargs["question"]))
            return 42

    capability = poll_capability(_Poster())
    dm = await capability.run(
        _context(guild_id=None), {"question": "Pizza ?", "options": ["oui", "non"]}
    )
    assert dm.ok is False
    ok = await capability.run(_context(), {"question": "Pizza ?", "options": ["oui", "non"]})
    assert ok.data["message_id"] == 42
    assert posted == ["Pizza ?"]


async def test_weather_forecast_lists_the_days() -> None:
    moment = 1_760_000_000

    def handler(
        _method: str, url: str, _headers: Mapping[str, str], _body: bytes | None
    ) -> HttpResponse:
        assert "appid=owm" in url
        return _json(
            {
                "city": {"timezone": 0, "name": "Lyon"},
                "list": [
                    {"dt": moment, "main": {"temp": 12}, "weather": [{"description": "pluie"}]},
                    {
                        "dt": moment + 86_400,
                        "main": {"temp": 18},
                        "weather": [{"description": "soleil"}],
                    },
                ],
            }
        )

    capability = weather_capability(FakeHttp(handler), "owm")
    result = await capability.run(_context(), {"city": "Lyon", "type": "forecast"})
    assert result.ok is True
    assert len(result.data["days"]) == 2
    assert result.data["days"][0]["description"] == "Pluie"
    rendered = render_weather(result.data)
    assert rendered.cards and "Pluie" in rendered.cards[0].as_text()


async def test_football_falls_back_to_thesportsdb_without_a_key() -> None:
    def handler(
        _method: str, url: str, _headers: Mapping[str, str], _body: bytes | None
    ) -> HttpResponse:
        if "searchteams" in url:
            return _json({"teams": [{"idTeam": "1", "strTeam": "PSG"}]})
        return _json(
            {"events": [{"dateEvent": "2026-10-12", "strHomeTeam": "PSG", "strAwayTeam": "OM"}]}
        )

    capability = football_capability(FakeHttp(handler))
    result = await capability.run(_context(), {"team": "PSG"})
    assert result.ok is True
    assert result.data["match"]["away"] == "OM"
    assert result.data["match"]["source"] == "TheSportsDB"


def test_youtube_ids_and_missing_captions() -> None:
    assert video_id("https://youtu.be/abcdefghijk") == "abcdefghijk"
    assert video_id("https://www.youtube.com/shorts/abcdefghijk") == "abcdefghijk"
    assert video_id("pas un lien") is None


async def test_youtube_reads_a_caption_track() -> None:
    html = '{"captionTracks":[{"baseUrl":"https://video.test/fr","languageCode":"fr"}]}'

    def handler(
        _method: str, url: str, _headers: Mapping[str, str], _body: bytes | None
    ) -> HttpResponse:
        if "oembed" in url:
            return _json({"title": "Démo", "author_name": "Ada"})
        if "video.test" in url:
            return HttpResponse(
                status=200, body=b"<transcript><text>bonjour</text></transcript>", headers={}
            )
        return HttpResponse(status=200, body=html.encode(), headers={})

    capability = youtube_capability(FakeHttp(handler))
    result = await capability.run(_context(), {"url": "abcdefghijk"})
    assert result.data["title"] == "Démo"
    assert result.data["transcript"] == "bonjour"


async def test_the_other_media_tools_parse_their_payloads(tmp_path: Path) -> None:
    def handler(
        method: str, url: str, headers: Mapping[str, str], body: bytes | None
    ) -> HttpResponse:
        if "themoviedb" in url and "/movie/1" in url:
            return _json({"genres": [{"name": "SF"}], "runtime": 155, "overview": "désert"})
        if "themoviedb" in url:
            return _json(
                {
                    "results": [
                        {
                            "media_type": "movie",
                            "id": 1,
                            "title": "Dune",
                            "overview": "désert",
                            "vote_average": 8,
                        }
                    ]
                }
            )
        if "storesearch" in url:
            return _json({"items": [{"id": 10, "name": "Hades"}]})
        if "appdetails" in url:
            return _json(
                {
                    "10": {
                        "data": {
                            "short_description": "rogue",
                            "price_overview": {"final_formatted": "10€"},
                        }
                    }
                }
            )
        if url.endswith("/api/token"):
            assert method == "POST"
            assert body == b"grant_type=client_credentials"
            return _json({"access_token": "tok", "expires_in": 3600})
        if "api.spotify.com" in url:
            assert headers["Authorization"] == "Bearer tok"
            return _json(
                {
                    "tracks": {
                        "items": [
                            {
                                "name": "Nights",
                                "artists": [{"name": "Frank"}],
                                "album": {"name": "Blond"},
                            }
                        ]
                    }
                }
            )
        if "/places?" in url:
            assert headers["apikey"] == "prim"
            return _json(
                {
                    "places": [
                        {
                            "embedded_type": "stop_area",
                            "quality": 90,
                            "stop_area": {"id": "stop_area:1", "name": "République"},
                        }
                    ]
                }
            )
        return _json(
            {
                "departures": [
                    {
                        "display_informations": {"label": "11", "direction": "Mairie"},
                        "stop_date_time": {"departure_date_time": _soon()},
                    }
                ]
            }
        )

    http = FakeHttp(handler)
    media = await media_capability(http, "tmdb").run(_context(), {"query": "Dune"})
    game = await game_capability(http).run(_context(), {"query": "Hades"})
    track = await track_capability(http, "id", "secret").run(_context(), {"query": "Nights"})
    settings = replace(Settings.for_tests(tmp_path), prim_api_key="prim")
    bus = await transport_capability(http, settings).run(_context(), {"stop": "République"})
    assert media.data["title"] == "Dune"
    assert media.data["length"] == "2h35"
    assert game.data["price"] == "10€"
    assert track.data["tracks"][0]["artists"] == "Frank"
    assert bus.data["rows"][0]["code"] == "11"
    assert bus.data["rows"][0]["waits"] == ["9 min"]


def _soon() -> str:
    moment = datetime.now(ZoneInfo("Europe/Paris")) + timedelta(minutes=9, seconds=10)
    return moment.strftime("%Y%m%dT%H%M%S")
