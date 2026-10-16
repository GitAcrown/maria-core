"""Niveau de spontanéité. `off` ne décide rien."""

from dataclasses import dataclass

from maria_core.db import Database


@dataclass(frozen=True, slots=True)
class Level:
    name: str
    threshold: float
    per_hour: int
    followup_s: float
    followup_depth: int


LEVELS = {
    "off": Level("off", 99.0, 0, 0.0, 0),
    "quiet": Level("quiet", 0.55, 1, 0.0, 0),
    "normal": Level("normal", 0.35, 3, 24.0, 3),
    "chatty": Level("chatty", 0.25, 6, 40.0, 3),
}


def room_budget(per_hour: int, humans: int) -> int:
    """Le niveau est le rythme d'un salon calme. Plus de monde, plus de réactions."""
    if per_hour <= 0:
        return 0
    return per_hour * max(humans, 1)


def parse_level(name: str | None) -> Level:
    if not name:
        return LEVELS["normal"]
    return LEVELS.get(name, LEVELS["normal"])


def level_for(database: Database, guild_id: int, user_id: int) -> Level:
    member = database.fetchone(
        """
        SELECT spontaneity FROM member_settings
        WHERE user_id = ? AND guild_id = ?
        """,
        (user_id, guild_id),
    )
    if member is not None and member["spontaneity"]:
        return parse_level(str(member["spontaneity"]))
    guild = database.fetchone(
        "SELECT spontaneity FROM guild_settings WHERE guild_id = ?",
        (guild_id,),
    )
    if guild is None:
        return LEVELS["normal"]
    return parse_level(str(guild["spontaneity"] or ""))


def set_member_level(database: Database, guild_id: int, user_id: int, name: str | None) -> None:
    """Niveau propre à un membre ; `None` revient à celui du serveur."""
    if name is not None and name not in LEVELS:
        raise ValueError("Niveau inconnu : off, quiet, normal, chatty.")
    database.execute(
        """
        INSERT INTO member_settings (user_id, guild_id, spontaneity)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id, guild_id) DO UPDATE SET spontaneity = excluded.spontaneity
        """,
        (user_id, guild_id, name),
    )


def set_level(database: Database, guild_id: int, name: str, now: str) -> Level:
    level = LEVELS.get(name)
    if level is None:
        raise ValueError("Niveau inconnu : off, quiet, normal, chatty.")
    database.execute(
        """
        INSERT INTO guild_settings (guild_id, spontaneity, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(guild_id) DO UPDATE SET
            spontaneity = excluded.spontaneity,
            updated_at = excluded.updated_at
        """,
        (guild_id, level.name, now),
    )
    return level
