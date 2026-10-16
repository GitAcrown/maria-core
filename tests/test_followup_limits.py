"""Un suivi : bref et expéditif, une fois après une réponse, sauf nouvel appel direct."""

from datetime import timedelta
from pathlib import Path

from maria_core.llm.types import Completion
from tests.fakes import ScriptedClient
from tests.test_automatic_replies import _service
from tests.test_service import _message
from tests.test_social import _NOW, _Engine, _social
from tests.test_social import _message as _social_message


async def test_only_one_followup_is_answered_after_a_reply(tmp_path: Path) -> None:
    engine = _Engine({"followup": "respond"})
    clock = [_NOW]
    social, database = _social(tmp_path, engine, clock)
    social.note_reply(_social_message(), "voilà", explicit=True)  # la réponse à un appel direct
    clock[0] += timedelta(seconds=5)
    assert await social.wants_followup(_social_message(message_id=12, text="et donc")) == "respond"
    social.note_reply(_social_message(), "bref", explicit=False)  # ce suivi a reçu sa réponse
    clock[0] += timedelta(seconds=5)
    assert await social.wants_followup(_social_message(message_id=13, text="et encore")) == "ignore"
    database.close()


async def test_calling_her_again_starts_a_new_exchange(tmp_path: Path) -> None:
    engine = _Engine({"followup": "respond"})
    clock = [_NOW]
    social, database = _social(tmp_path, engine, clock)
    social.note_reply(_social_message(), "un", explicit=True)
    social.note_reply(_social_message(), "deux", explicit=False)
    clock[0] += timedelta(seconds=5)
    assert await social.wants_followup(_social_message(text="et ?")) == "ignore"
    social.note_reply(_social_message(), "trois", explicit=True)  # nouvelle mention : on repart
    clock[0] += timedelta(seconds=5)
    assert await social.wants_followup(_social_message(text="et ?")) == "respond"
    database.close()


async def test_a_followup_turn_asks_for_a_short_answer_and_a_direct_call_does_not(
    tmp_path: Path,
) -> None:
    client = ScriptedClient(
        [Completion(text="Oui.", model="fake"), Completion(text="Bonjour.", model="fake")]
    )
    service, social, database = _service(tmp_path, client)
    social.followup = "respond"
    await service.handle(_message(mentioned=False, text="et pour demain ?", message_id=20))
    system = " ".join(str(m["content"]) for m in client.seen[0] if m["role"] == "system")
    assert "SUIVI :" in system and "Reste bref" in system and "[[REACT]]" in system
    await service.handle(_message(mentioned=True, text="Maria bonjour", message_id=21))
    direct = " ".join(str(m["content"]) for m in client.seen[1] if m["role"] == "system")
    assert "SUIVI :" not in direct
    database.close()
