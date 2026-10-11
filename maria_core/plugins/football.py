"""Scores via TheSportsDB (clé publique). Pas de quota, pas de live minute par minute."""

from collections.abc import Mapping
from typing import Any

from maria_core.capabilities import Capability, Context, Result, Risk
from maria_core.capabilities.http import HttpClient, HttpError, parse_json, with_query
from maria_core.plugins import PluginHost

_BASE = "https://www.thesportsdb.com/api/v1/json/123"


NAME = "football"


def setup(app: PluginHost) -> None:
    app.capabilities.register(football_capability(app.http))
    app.widgets.register("get_football", render_football)


def football_capability(http: HttpClient) -> Capability:
    async def run(_context: Context, args: Mapping[str, Any]) -> Result:
        team = str(args["team"]).strip()
        when = str(args.get("when") or "next")
        try:
            found = await _team(http, team)
            events = await _events(http, str(found["idTeam"]), when)
        except (ValueError, HttpError) as exc:
            return Result(ok=False, data={}, error=str(exc))
        lines = [_line(item) for item in events[:5]]
        if not lines:
            return Result(ok=False, data={}, error=f"Aucun match pour {found['strTeam']}.")
        return Result(
            ok=True,
            data={"team": found["strTeam"], "matches": lines},
            widget="get_football",
        )

    return Capability(
        name="get_football",
        description=(
            "Prochains ou derniers matchs d'une équipe. when=next (défaut) ou last. "
            "Le score est celui au moment de l'appel."
        ),
        parameters={
            "type": "object",
            "properties": {
                "team": {"type": "string", "description": "Nom d'équipe, ex. PSG"},
                "when": {"type": "string", "enum": ["next", "last"]},
            },
            "required": ["team"],
        },
        risk=Risk.EXTERNAL,
        run=run,
    )


def render_football(data: Mapping[str, Any]) -> str:
    matches = data.get("matches") or []
    body = "\n".join(f"- {item}" for item in matches if isinstance(item, str))
    team = data.get("team") or ""
    return f"{team}\n{body}".strip()


async def _team(http: HttpClient, name: str) -> dict[str, Any]:
    payload = await _json(http, f"{_BASE}/searchteams.php", {"t": name})
    teams = payload.get("teams") or []
    if not teams or not isinstance(teams[0], dict):
        raise ValueError(f"Équipe introuvable : {name}.")
    return teams[0]


async def _events(http: HttpClient, team_id: str, when: str) -> list[Any]:
    script = "eventsnext.php" if when != "last" else "eventslast.php"
    payload = await _json(http, f"{_BASE}/{script}", {"id": team_id})
    results = payload.get("results")
    events = results if isinstance(results, list) else payload.get("events")
    return events if isinstance(events, list) else []


async def _json(http: HttpClient, url: str, params: dict[str, str]) -> dict[str, Any]:
    response = await http.request("GET", with_query(url, params))
    payload = parse_json(response)
    if not isinstance(payload, dict):
        raise ValueError("Réponse football inattendue.")
    return payload


def _line(event: Any) -> str:
    if not isinstance(event, dict):
        return ""
    home = event.get("strHomeTeam") or "?"
    away = event.get("strAwayTeam") or "?"
    score = _score(event.get("intHomeScore"), event.get("intAwayScore"))
    when = " ".join(part for part in (event.get("dateEvent"), event.get("strTime")) if part)
    return f"{when} {home} {score} {away}".strip()


def _score(home: object, away: object) -> str:
    if home in {None, ""} or away in {None, ""}:
        return "-"
    return f"{home}-{away}"
