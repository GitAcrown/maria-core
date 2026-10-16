"""Un média en réponse à un rappel n'appelle pas de commentaire sur le rappel."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from maria_core.capabilities import CapabilityRegistry
from maria_core.config import Settings
from maria_core.conversation.context import focus_note
from maria_core.conversation.model import Quote
from maria_core.conversation.service import ConversationService
from maria_core.db import Database
from maria_core.llm.prompt import PromptSections
from maria_core.llm.types import Completion
from tests.fakes import ScriptedClient
from tests.test_service import _message


def _quote(identifier: int = 77) -> Quote:
    return Quote(
        message_id=identifier,
        author_id=1,
        author_name="MARIA",
        text="Il reste 15 jours avant Halloween 2026.",
        from_bot_self=True,
        from_bot=True,
    )


class _Social:
    def __init__(self) -> None:
        self.reacted: list[int] = []
        self.followup = "ignore"
        self.recent = False
        self.room = SimpleNamespace(from_author=lambda *_a: 0, volume=lambda *_a: 0)

    async def note(self, _message: Any) -> None: ...

    def note_addressed(self, _message: Any) -> None: ...

    def note_reply(self, _message: Any, _text: str, **_options: Any) -> None: ...

    def prefers_emoji(self, _message: Any) -> bool:
        return False

    def recently_reacted(self, _message: Any) -> bool:
        return self.recent

    async def wants_followup(self, _message: Any) -> str:
        return self.followup

    async def consider(self, _message: Any, **_options: Any) -> str:
        return ""

    async def react_now(self, message: Any, _target: int, **_options: Any) -> None:
        self.reacted.append(message.message_id)


def _service(tmp_path: Path, client: ScriptedClient) -> tuple[ConversationService, Any, Database]:
    database = Database(tmp_path / "maria.db")
    database.migrate()
    prompt = PromptSections()
    prompt.register_section("personality", lambda: "Tu es MARIA.", order=0)
    social = _Social()
    service = ConversationService(
        database=database,
        client=client,
        capabilities=CapabilityRegistry(),
        prompt=prompt,
        settings=Settings.for_tests(tmp_path / "data"),
        debounce_seconds=0,
        social=social,  # type: ignore[arg-type]
    )
    return service, social, database


def test_a_media_only_reply_to_her_message_is_not_a_question_about_it() -> None:
    video = _message(reply_to_bot=True, text="", has_media=True, quote=_quote())
    hint = str(focus_note(video)["content"])
    assert "commente le média, pas ton message cité" in hint
    assert "la demande porte sur le message cité" not in hint
    someone = _quote()
    other = Quote(someone.message_id, 2, "Léa", "salut", False, False)
    empty = str(focus_note(_message(text="", quote=other))["content"])
    assert "la demande porte sur le message cité" in empty  # un message d'un tiers : inchangé


async def test_a_video_answering_a_reminder_gets_an_emoji_not_a_comment(tmp_path: Path) -> None:
    client = ScriptedClient([Completion(text="Je ne peux pas voir la vidéo.", model="fake")])
    service, social, database = _service(tmp_path, client)
    service.note_posted(3, "Il reste 15 jours avant Halloween 2026.", message_id=77)
    reply = await service.handle(
        _message(mentioned=True, reply_to_bot=True, text="", has_media=True, quote=_quote(77))
    )
    assert reply is None and social.reacted == [10] and client.seen == []
    database.close()


async def test_other_replies_still_get_an_answer(tmp_path: Path) -> None:
    client = ScriptedClient(
        [Completion(text="Avec plaisir.", model="fake"), Completion(text="Merci.", model="fake")]
    )
    service, social, database = _service(tmp_path, client)
    service.note_posted(3, "Il reste 15 jours avant Halloween 2026.", message_id=77)
    # du texte en réponse au rappel : une vraie réponse
    texte = await service.handle(
        _message(mentioned=True, reply_to_bot=True, text="merci du rappel", quote=_quote(77))
    )
    assert texte is not None and social.reacted == []
    # un média en réponse à une vraie réponse de MARIA (pas un rappel) : elle le regarde
    media = await service.handle(
        _message(
            mentioned=True,
            reply_to_bot=True,
            text="",
            has_media=True,
            quote=_quote(88),
            message_id=11,
        )
    )
    assert media is not None and social.reacted == []
    database.close()
