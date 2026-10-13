"""Les commandes slash reprennent celles de MARIA_R, sans les signets."""

from pathlib import Path

from maria_core.conversation.model import Inbound, ReplyMode
from maria_core.conversation.persona import default_personality
from maria_core.conversation.policy import load_policy, save_everyone, save_mode
from maria_core.db import Database
from maria_core.discord.commands.public import PublicCommands

_NOW = "2026-10-11T20:00:00+00:00"


def test_the_default_voice_matches_the_old_one() -> None:
    text = default_personality()
    assert "sans emoji" in text
    assert "Directe, concise, factuelle" in text
    assert "objective_create" in text
    assert "n'invente" in text.lower() or "N'invente" in text
    names = sorted(command.name for command in PublicCommands.__cog_app_commands__)
    assert names == ["chatbot", "global", "info", "moi", "preferences", "programmes"]
    group = next(
        command for command in PublicCommands.__cog_app_commands__ if command.name == "chatbot"
    )
    children = sorted(child.name for child in group.commands)
    assert children == [
        "autotranscribe",
        "everyone",
        "forget",
        "mode",
        "python",
        "spontaneite",
    ]


def test_mode_and_everyone_are_saved(tmp_path: Path) -> None:
    database = Database(tmp_path / "maria.db")
    database.migrate()
    assert save_mode(database, 5, "greedy", _NOW) == "greedy"
    save_everyone(database, 9, 5, True)
    policy = load_policy(database, _inbound())
    assert policy.mode is ReplyMode.GREEDY
    assert policy.respond_everyone is True
    database.close()


def _inbound() -> Inbound:
    return Inbound(
        channel_id=9,
        message_id=1,
        guild_id=5,
        author_id=7,
        author_name="Léa",
        text="salut",
        is_dm=False,
        author_is_bot=False,
        mentioned=False,
        reply_to_bot=False,
        mention_everyone=False,
        edited=False,
        author_is_owner=False,
        author_is_moderator=False,
    )
