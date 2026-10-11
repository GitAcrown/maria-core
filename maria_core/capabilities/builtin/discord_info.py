"""Infos Discord live. Le répertoire est fourni par l'adaptateur."""

from collections.abc import Mapping
from typing import Any

from maria_core.capabilities.base import Capability, Context, Result, Risk
from maria_core.capabilities.ports import GuildDirectory, MemberCard


def discord_capabilities(directory: GuildDirectory) -> tuple[Capability, ...]:
    return (
        _cap(
            "get_server_users",
            "Membres du serveur présents dans le cache, filtrables par nom.",
            {"search": {"type": "string", "description": "Filtre de nom, optionnel"}},
            [],
            _users(directory),
        ),
        _cap(
            "get_member_info",
            "Fiche d'un membre : nom, rôles, arrivée. Par id ou par pseudo exact.",
            {
                "user_id": {"type": "string", "description": "Id Discord"},
                "username": {"type": "string", "description": "Pseudo exact"},
            },
            [],
            _member(directory),
        ),
        _cap(
            "get_channel_info",
            "Sujet et type d'un salon. Sans id : le salon actuel.",
            {"channel_id": {"type": "string"}},
            [],
            _channel(directory),
        ),
    )


def _cap(
    name: str,
    description: str,
    properties: dict[str, Any],
    required: list[str],
    run: Any,
) -> Capability:
    return Capability(
        name=name,
        description=description,
        parameters={"type": "object", "properties": properties, "required": required},
        risk=Risk.READ,
        run=run,
    )


def _users(directory: GuildDirectory) -> Any:
    async def run(context: Context, args: Mapping[str, Any]) -> Result:
        if context.guild_id is None:
            return _no_guild()
        cards = await directory.members(context.guild_id, str(args.get("search") or ""))
        return Result(ok=True, data={"members": [_member_data(card) for card in cards]})

    return run


def _member(directory: GuildDirectory) -> Any:
    async def run(context: Context, args: Mapping[str, Any]) -> Result:
        if context.guild_id is None:
            return _no_guild()
        user_id = _integer(args.get("user_id"))
        username = str(args.get("username") or "").strip()
        if user_id is None and not username:
            return Result(ok=False, data={}, error="Il faut un id ou un pseudo.")
        card = await directory.member(context.guild_id, user_id, username)
        if card is None:
            return Result(ok=False, data={}, error="Membre introuvable.")
        return Result(ok=True, data=_member_data(card))

    return run


def _channel(directory: GuildDirectory) -> Any:
    async def run(context: Context, args: Mapping[str, Any]) -> Result:
        channel_id = _integer(args.get("channel_id")) or context.channel_id
        card = await directory.channel(channel_id)
        if card is None:
            return Result(ok=False, data={}, error="Salon introuvable.")
        return Result(
            ok=True,
            data={"id": card.channel_id, "name": card.name, "topic": card.topic, "kind": card.kind},
        )

    return run


def _member_data(card: MemberCard) -> dict[str, Any]:
    return {
        "id": card.user_id,
        "name": card.name,
        "roles": list(card.roles),
        "joined_at": card.joined_at,
    }


def _integer(raw: object) -> int | None:
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw if raw > 0 else None
    if isinstance(raw, str) and raw.strip().isdigit():
        return int(raw.strip())
    return None


def _no_guild() -> Result:
    return Result(ok=False, data={}, error="Disponible uniquement sur un serveur.")
