"""Football : API-Football d'abord (direct, buteurs, stats), TheSportsDB en secours gratuit."""

from collections.abc import Mapping
from typing import Any

from maria_core.capabilities import Capability, Context, Result, Risk
from maria_core.capabilities.http import HttpClient, HttpError, parse_json, with_query
from maria_core.plugins import PluginHost
from maria_core.plugins.football_view import name_matches, normalize, render_football

_API = "https://v3.football.api-sports.io"
_TSDB = "https://www.thesportsdb.com/api/v1/json/123"
_LIVE = frozenset({"1H", "2H", "ET", "BT", "P", "LIVE", "INT", "HT"})

NAME = "football"


def setup(app: PluginHost) -> None:
    app.capabilities.register(football_capability(app.http, app.settings.api_football_key))
    app.widgets.register("get_football", render_football)


def football_capability(http: HttpClient, api_key: str = "") -> Capability:
    source = _Sources(http, api_key)

    async def run(_context: Context, args: Mapping[str, Any]) -> Result:
        team = str(args.get("team") or "").strip()
        opponent = str(args.get("opponent") or "").strip()
        when = str(args.get("when") or "auto")
        try:
            data = await source.answer(team, opponent, when)
        except (ValueError, HttpError) as exc:
            return Result(ok=False, data={}, error=str(exc))
        return Result(ok=True, data=normalize(data), widget="get_football")

    return Capability(
        name="get_football",
        description=(
            "Score et stats d'un match de foot en cours ou récent. team = club ou sélection "
            "(PSG, France), ou @profil pour « mon équipe » ; opponent si deux équipes citées. "
            "when : auto (direct sinon dernier match), live, last, next, recent (5 derniers). "
            "Sans team : matchs en direct."
        ),
        parameters={
            "type": "object",
            "properties": {
                "team": {"type": "string", "description": "Équipe"},
                "opponent": {"type": "string", "description": "Adversaire, si cité"},
                "when": {"type": "string", "enum": ["auto", "live", "last", "next", "recent"]},
            },
            "required": [],
        },
        risk=Risk.EXTERNAL,
        profile_args=(("team", "team", False),),
        cache_s=45,
        run=run,
    )


class _Sources:
    def __init__(self, http: HttpClient, api_key: str) -> None:
        self._http = http
        self._key = api_key
        self._ids: dict[str, int | None] = {}

    async def answer(self, team: str, opponent: str, when: str) -> dict[str, Any]:
        if not team:
            return await self._live_list()
        canonical = await self._tsdb_name(team)
        if self._key:
            found = await self._api_answer(team, canonical, opponent, when)
            if found is not None:
                return found
        return await self._tsdb_answer(canonical or team, when)

    async def _api_answer(
        self, team: str, canonical: str, opponent: str, when: str
    ) -> dict[str, Any] | None:
        names = tuple(name for name in (team, canonical) if name)
        if when in {"auto", "live"}:
            live = await self._live_for(names, opponent)
            if live is not None:
                return {"mode": "match", "match": await self._enrich(live)}
            if when == "live":
                raise ValueError(f"{team} ne joue pas en ce moment.")
        team_id = await self._team_id(names)
        if team_id is None:
            return None
        if when == "recent":
            fixtures = await self._api("fixtures", {"team": str(team_id), "last": "5"})
            return (
                {"mode": "list", "title": canonical or team, "matches": fixtures}
                if fixtures
                else None
            )
        kind = "next" if when == "next" else "last"
        fixtures = await self._api("fixtures", {"team": str(team_id), kind: "1"})
        if not fixtures:
            return None
        return {"mode": "match", "match": await self._enrich(fixtures[0])}

    async def _live_for(self, names: tuple[str, ...], opponent: str) -> dict[str, Any] | None:
        for fixture in await self._api("fixtures", {"live": "all"}):
            teams = fixture.get("teams") or {}
            home = str((teams.get("home") or {}).get("name") or "")
            away = str((teams.get("away") or {}).get("name") or "")
            if not any(name_matches(name, home) or name_matches(name, away) for name in names):
                continue
            if opponent and not (name_matches(opponent, home) or name_matches(opponent, away)):
                continue
            return fixture
        return None

    async def _enrich(self, fixture: dict[str, Any]) -> dict[str, Any]:
        status = str(((fixture.get("fixture") or {}).get("status") or {}).get("short") or "")
        fixture_id = (fixture.get("fixture") or {}).get("id")
        if fixture_id and status not in {"NS", "TBD", "PST", "CANC"}:
            fixture["events"] = await self._api("fixtures/events", {"fixture": str(fixture_id)})
            if status in _LIVE:
                fixture["statistics"] = await self._api(
                    "fixtures/statistics", {"fixture": str(fixture_id)}
                )
        return fixture

    async def _live_list(self) -> dict[str, Any]:
        if not self._key:
            raise ValueError("Pas de liste des matchs en direct sans clé API-Football.")
        return {"mode": "live", "matches": (await self._api("fixtures", {"live": "all"}))[:15]}

    async def _team_id(self, names: tuple[str, ...]) -> int | None:
        for name in names:
            key = name.casefold()
            if key not in self._ids:
                found = await self._api("teams", {"search": name})
                team = (found[0].get("team") or {}) if found else {}
                self._ids[key] = team.get("id") if isinstance(team.get("id"), int) else None
            if self._ids[key] is not None:
                return self._ids[key]
        return None

    async def _api(self, endpoint: str, params: dict[str, str]) -> list[dict[str, Any]]:
        response = await self._http.request(
            "GET", with_query(f"{_API}/{endpoint}", params), headers={"x-apisports-key": self._key}
        )
        payload = parse_json(response)
        if not isinstance(payload, dict) or payload.get("errors"):
            return []
        rows = payload.get("response")
        return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []

    async def _tsdb_name(self, team: str) -> str:
        try:
            payload = await self._tsdb("searchteams.php", {"t": team})
        except (ValueError, HttpError):
            return ""
        teams = payload.get("teams") or []
        return str(teams[0].get("strTeam") or "") if teams and isinstance(teams[0], dict) else ""

    async def _tsdb_answer(self, team: str, when: str) -> dict[str, Any]:
        payload = await self._tsdb("searchteams.php", {"t": team})
        teams = payload.get("teams") or []
        if not teams or not isinstance(teams[0], dict):
            raise ValueError(f"Équipe introuvable : {team}.")
        found = teams[0]
        script = "eventsnext.php" if when == "next" else "eventslast.php"
        events = await self._tsdb(script, {"id": str(found["idTeam"])})
        rows = events.get("results") or events.get("events") or []
        matches = [item for item in rows if isinstance(item, dict)]
        if not matches:
            raise ValueError(f"Aucun match trouvé pour {found.get('strTeam') or team}.")
        return {
            "mode": "tsdb",
            "title": str(found.get("strTeam") or team),
            "matches": matches[:5],
            "single": when != "recent",
        }

    async def _tsdb(self, script: str, params: dict[str, str]) -> dict[str, Any]:
        payload = parse_json(
            await self._http.request("GET", with_query(f"{_TSDB}/{script}", params))
        )
        if not isinstance(payload, dict):
            raise ValueError("Réponse football inattendue.")
        return payload
