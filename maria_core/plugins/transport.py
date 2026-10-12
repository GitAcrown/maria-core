"""Transports : Île-de-France (PRIM) et trains SNCF. Passages, trafic d'une ligne, trafic global."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import quote

from maria_core.capabilities import Capability, Context, Result, Risk
from maria_core.capabilities.http import HttpClient, HttpError, parse_json, with_query
from maria_core.config import Settings
from maria_core.plugins import PluginHost
from maria_core.plugins.transport_text import (
    PARIS,
    disruption_copy,
    mode_rank,
    name_bonus,
    parse_time,
    plain,
    render_transport,
    wait_label,
)

_SNCF_HINT = re.compile(r"\b(gare|tgv|ter|intercit|lyria|eurostar|train|ouigo)\b", re.IGNORECASE)
_IDF_HINT = re.compile(r"\b(m[ée]tro|rer|tram|bus)\b", re.IGNORECASE)
_ACCESSIBILITY = re.compile(r"\b(ascenseur|escalier|escalator)\b", re.IGNORECASE)
_MAX_ROWS = 10

NAME = "transport"


@dataclass(frozen=True, slots=True)
class _Backend:
    label: str
    base: str
    key: str
    header: str


def setup(app: PluginHost) -> None:
    app.capabilities.register(transport_capability(app.http, app.settings))
    app.widgets.register("get_transport", render_transport)


def transport_capability(http: HttpClient, settings: Settings) -> Capability:
    navitia = _Navitia(http, settings)

    async def run(_context: Context, args: Mapping[str, Any]) -> Result:
        stop = str(args.get("stop") or "").strip()
        line = str(args.get("line") or "").strip()
        try:
            if stop:
                payload = await navitia.departures(stop, line)
            elif line:
                payload = await navitia.line_traffic(line)
            else:
                payload = await navitia.global_traffic()
        except (ValueError, HttpError) as exc:
            return Result(ok=False, data={}, error=str(exc))
        return Result(ok=True, data=payload, widget="get_transport")

    return Capability(
        name="get_transport",
        description=(
            "Transports : Île-de-France (PRIM) et trains SNCF (TGV, TER, Intercités). "
            "stop = arrêt ou gare : prochains passages (line pour filtrer). line seule (RER B, "
            "11, T3a) : trafic de la ligne. Ni l'un ni l'autre : trafic global IDF. "
            "« mon métro » : l'arrêt est peut-être dans le PROFIL."
        ),
        parameters={
            "type": "object",
            "properties": {
                "stop": {"type": "string", "description": "Arrêt ou gare (République, Part-Dieu)"},
                "line": {"type": "string", "description": "Ligne IDF : RER B, 11, T3a"},
            },
            "required": [],
        },
        risk=Risk.EXTERNAL,
        run=run,
        requires_any=frozenset({"PRIM_API_KEY", "SNCF_API_KEY"}),
    )


class _Navitia:
    def __init__(self, http: HttpClient, settings: Settings) -> None:
        self._http = http
        self._prim = _Backend(
            "Île-de-France Mobilités",
            "https://prim.iledefrance-mobilites.fr/marketplace/v2/navitia",
            settings.prim_api_key,
            "apikey",
        )
        self._sncf = _Backend(
            "SNCF", "https://api.sncf.com/v1/coverage/sncf", settings.sncf_api_key, "Authorization"
        )

    async def departures(self, stop: str, line: str) -> dict[str, Any]:
        blob = f"{stop} {line}"
        prefer_sncf = bool(_SNCF_HINT.search(blob)) and not _IDF_HINT.search(blob)
        order = (self._sncf, self._prim) if prefer_sncf else (self._prim, self._sncf)
        last_error = "Aucune clé transport."
        for backend in (item for item in order if item.key):
            try:
                found = await self._departures_on(backend, stop, line)
            except (ValueError, HttpError) as exc:
                last_error = str(exc)
                continue
            if found["rows"]:
                return found
            last_error = f"Aucun passage proche à {found['stop']}."
        raise ValueError(last_error)

    async def line_traffic(self, line: str) -> dict[str, Any]:
        if not self._prim.key:
            raise ValueError("Le trafic d'une ligne demande la clé PRIM.")
        found = await self._line(line)
        payload = await self._get(
            self._prim, f"lines/{quote(found['id'], safe=':')}/line_reports", {"count": "20"}
        )
        notes = _notes(payload, found["id"])
        title = found["name"]
        if found["code"] and found["code"] not in title:
            title = f"{found['mode'] or 'Ligne'} {found['code']}".strip()
        status = "Perturbé" if notes else "Trafic normal"
        return {
            "kind": "traffic",
            "title": title,
            "status": status,
            "notes": notes,
            "source": "IDFM",
        }

    async def global_traffic(self) -> dict[str, Any]:
        if not self._prim.key:
            raise ValueError("Le trafic global demande la clé PRIM.")
        notes = _notes(
            await self._get(self._prim, "line_reports/line_reports", {"count": "20"}), ""
        )
        status = f"{len(notes)} perturbation(s)" if notes else "Rien de notable"
        return {
            "kind": "traffic",
            "title": "Trafic IDF",
            "status": status,
            "notes": notes[:8],
            "source": "IDFM",
        }

    async def _departures_on(self, backend: _Backend, stop: str, line: str) -> dict[str, Any]:
        place = await self._place(backend, stop)
        segment = "stop_points" if place["kind"] == "stop_point" else "stop_areas"
        path = f"{segment}/{quote(place['id'], safe=':')}/departures"
        payload = await self._get(backend, path, {"count": "30", "data_freshness": "realtime"})
        rows, realtime = _group(payload, line)
        return {
            "kind": "departures",
            "stop": place["name"],
            "rows": rows,
            "realtime": realtime,
            "source": "IDFM" if backend is self._prim else "SNCF",
        }

    async def _place(self, backend: _Backend, query: str) -> dict[str, str]:
        payload = await self._get(backend, "places", {"q": query, "count": "8"})
        best: dict[str, str] | None = None
        best_rank = -(10**9)
        for place in payload.get("places") or []:
            kind = str(place.get("embedded_type") or "")
            embedded = place.get("stop_area") or place.get("stop_point")
            if not isinstance(embedded, dict):
                continue
            name = str(embedded.get("name") or place.get("name") or query)
            bonus = {"stop_area": 20, "stop_point": 10}.get(kind, 0)
            rank = int(place.get("quality") or 0) * 10 + bonus + name_bonus(query, name)
            if rank > best_rank:
                best_rank = rank
                best = {
                    "id": str(embedded.get("id") or place.get("id")),
                    "name": name,
                    "kind": kind,
                }
        if best is None:
            raise ValueError(f"Arrêt introuvable : {query}.")
        return best

    async def _line(self, query: str) -> dict[str, str]:
        payload = await self._get(
            self._prim, "pt_objects", {"q": query, "type[]": "line", "count": "8"}
        )
        wanted = query.strip().lower()
        tokens = re.findall(r"[a-z0-9]+", wanted)
        best: dict[str, Any] | None = None
        best_score = -(10**9)
        for item in payload.get("pt_objects") or []:
            line = item.get("line") or {}
            if not line.get("id"):
                continue
            score = _line_score(item, line, wanted, tokens)
            if score > best_score:
                best_score, best = score, line
        if best is None:
            raise ValueError(f"Ligne introuvable : {query}.")
        modes = best.get("physical_modes") or []
        return {
            "id": str(best["id"]),
            "name": str(best.get("name") or best.get("code") or query),
            "code": str(best.get("code") or ""),
            "mode": str((modes[0].get("name") if modes else "") or ""),
        }

    async def _get(self, backend: _Backend, path: str, params: dict[str, str]) -> dict[str, Any]:
        if not backend.key:
            raise ValueError(f"Clé {backend.label} manquante.")
        response = await self._http.request(
            "GET",
            with_query(f"{backend.base}/{path}", params),
            headers={backend.header: backend.key, "Accept": "application/json"},
        )
        payload = parse_json(response)
        if not isinstance(payload, dict):
            raise ValueError("Réponse transport inattendue.")
        if payload.get("error"):
            message = (
                (payload.get("error") or {}).get("message")
                if isinstance(payload.get("error"), dict)
                else payload.get("error")
            )
            raise ValueError(f"{backend.label} : {message}")
        return payload


def _line_score(
    item: Mapping[str, Any], line: Mapping[str, Any], wanted: str, tokens: list[str]
) -> int:
    code = str(line.get("code") or "").strip().lower()
    name = str(line.get("name") or "").lower()
    modes = line.get("physical_modes") or []
    mode = str((modes[0].get("name") if modes else "") or "").lower()
    score = int(item.get("quality") or 0)
    score -= 80 if "remplacement" in name else 0
    for pattern, needle in ((r"\brer\b", "rer"), (r"\bm[ée]tro\b", "métro"), (r"\btram", "tram")):
        if re.search(pattern, wanted) and needle in mode:
            score += 40
    return score + (25 if code and code in tokens else 0)


def _group(payload: Mapping[str, Any], line: str) -> tuple[list[dict[str, Any]], bool]:
    now = datetime.now(PARIS)
    wanted = line.strip().lower()
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    realtime = False
    for departure in payload.get("departures") or []:
        info = departure.get("display_informations") or {}
        code = str(info.get("code") or info.get("label") or "?").strip() or "?"
        mode = str(info.get("commercial_mode") or info.get("physical_mode") or "").strip()
        direction = str(info.get("direction") or info.get("headsign") or "").strip()
        haystack = f"{code} {info.get('label', '')} {mode} {direction}".lower()
        if wanted and wanted not in haystack:
            continue
        stamp = departure.get("stop_date_time") or {}
        moment = parse_time(str(stamp.get("departure_date_time") or ""))
        if moment is None or moment < now - timedelta(minutes=1):
            continue
        realtime = realtime or stamp.get("data_freshness") == "realtime"
        slot = grouped.setdefault(
            (code, direction), {"code": code, "mode": mode, "direction": direction, "times": []}
        )
        if len(slot["times"]) < 2:
            slot["times"].append(moment)
    rows = sorted(grouped.values(), key=lambda row: (mode_rank(row["mode"]), row["times"][0]))
    return [
        {
            **{key: row[key] for key in ("code", "mode", "direction")},
            "waits": [wait_label(t, now) for t in row["times"]],
        }
        for row in rows[:_MAX_ROWS]
    ], realtime


def _notes(payload: Mapping[str, Any], line_id: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for item in payload.get("disruptions") or []:
        status = str(item.get("status") or "").lower()
        if status and status not in {"active", "future"}:
            continue
        message = disruption_copy(item.get("messages") or []) or plain(str(item.get("cause") or ""))
        if not message or message.lower() in seen or _ACCESSIBILITY.search(message):
            continue
        seen.add(message.lower())
        found.append(message)
    return found[:6] if line_id else found
