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
    assert "sans emoji dans ton texte" in system and "SILENCE :" not in system
    await service.handle(_message(mentioned=True, text="Maria bonjour", message_id=21))
    direct = " ".join(str(m["content"]) for m in client.seen[1] if m["role"] == "system")
    assert "SUIVI :" not in direct
    database.close()


async def test_she_keeps_listening_while_the_person_keeps_writing_up_to_two_minutes(
    tmp_path: Path,
) -> None:
    engine = _Engine({"followup": "ignore"})  # le suivi n'est jamais retenu : seule l'écoute compte
    clock = [_NOW]
    social, database = _social(tmp_path, engine, clock)
    social.note_reply(_social_message(), "voilà", explicit=True)
    for second in (20, 40, 60, 80, 100, 115):
        clock[0] = _NOW + timedelta(seconds=second)
        await social.wants_followup(_social_message(text="et sinon"))
    assert social.room.followup(3, 7) is not None
    engine.answers["followup"] = "respond"
    clock[0] = _NOW + timedelta(seconds=118)
    assert await social.wants_followup(_social_message(text="et donc")) == "respond"
    clock[0] = _NOW + timedelta(seconds=125)  # au-delà de 2 min : fini, même en continuant
    assert await social.wants_followup(_social_message(text="et donc")) == "ignore"
    database.close()


async def test_a_pause_closes_the_listening_and_typing_reopens_it(tmp_path: Path) -> None:
    engine = _Engine({"followup": "respond"})
    clock = [_NOW]
    social, database = _social(tmp_path, engine, clock)
    social.note_reply(_social_message(), "voilà", explicit=True)
    clock[0] = _NOW + timedelta(seconds=40)  # 40 s de silence : trop tard (fenêtre de 24 s)
    assert await social.wants_followup(_social_message(text="et donc")) == "ignore"
    social.typing(3, 7)  # elle se remet à écrire
    clock[0] = _NOW + timedelta(seconds=55)
    assert await social.wants_followup(_social_message(text="et donc")) == "respond"
    database.close()


async def test_a_followup_reaction_is_refused_right_after_another_one(tmp_path: Path) -> None:
    engine = _Engine({"followup": "react"})
    clock = [_NOW]
    social, database = _social(tmp_path, engine, clock)
    social.note_reply(_social_message(), "voilà", explicit=True)
    clock[0] += timedelta(seconds=5)
    assert await social.wants_followup(_social_message(text="merci")) == "react"
    social.room.mark_react(3)  # MARIA vient de poser un emoji
    clock[0] += timedelta(seconds=10)
    assert await social.wants_followup(_social_message(text="merci")) == "ignore"
    clock[0] += timedelta(seconds=100)  # le délai est passé : une nouvelle réaction est permise
    social.note_reply(_social_message(), "ok", explicit=True)
    clock[0] += timedelta(seconds=5)
    assert await social.wants_followup(_social_message(text="merci")) == "react"
    database.close()


async def test_the_model_reaction_on_a_followup_is_dropped_when_one_just_happened(
    tmp_path: Path,
) -> None:
    client = ScriptedClient(
        [Completion(text="[[REACT]]", model="fake"), Completion(text="[[REACT]]", model="fake")]
    )
    service, social, database = _service(tmp_path, client)
    social.followup = "respond"
    await service.handle(_message(mentioned=False, text="merci", message_id=30))
    assert social.reacted == [30]
    social.recent = True
    await service.handle(_message(mentioned=False, text="top", message_id=31))
    assert social.reacted == [30]  # pas d'emoji de plus : MARIA vient d'en poser un
    database.close()
