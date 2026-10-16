"""Une correction d'orthographe ne relance pas la réponse ; un vrai changement, si."""

from pathlib import Path

import pytest

from maria_core.conversation.edits import is_minor_edit
from maria_core.llm.types import Completion
from tests.fakes import ScriptedClient
from tests.test_service import _message, _open


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("Maria quel temp fait il", "Maria quel temps fait-il"),
        ("tu peux m'expliquer ca", "Tu peux m'expliquer ça !"),
        ("maria dis moi la capitale de la frnace", "Maria, dis-moi la capitale de la France"),
        ("bonjour maria", "Bonjour Maria."),
        ("il y a un probleme avec le bot", "il y a un problème avec le bot"),
    ],
)
def test_spelling_accents_case_and_punctuation_are_minor(old: str, new: str) -> None:
    assert is_minor_edit(old, new)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("météo à Lyon", "météo à Paris"),
        ("oui", "non"),
        ("Maria il est 5h", "Maria il est 6h"),
        ("bonjour", "bonjour comment ça va"),
        ("salut", "salut Maria"),
        ("tu viens ce soir", "tu viens demain soir"),
        ("cherche la recette de crêpes", "cherche la recette de pizza"),
    ],
)
def test_a_changed_meaning_is_not_minor(old: str, new: str) -> None:
    assert not is_minor_edit(old, new)


async def test_a_corrected_typo_keeps_the_reply_and_updates_the_thread(tmp_path: Path) -> None:
    client = ScriptedClient(
        [Completion(text="Il fait beau.", model="fake"), Completion(text="NE DOIT PAS SORTIR")]
    )
    service, database = _open(tmp_path, client)
    first = await service.handle(_message(mentioned=True, message_id=4, text="Maria quel temp ?"))
    assert first is not None
    service.remember_reply(4, 99)
    fixed = await service.handle(
        _message(mentioned=True, message_id=4, text="Maria quel temps ?", edited=True)
    )
    assert fixed is None and len(client.seen) == 1  # pas de nouvel appel au modèle
    transcript = "\n".join(service.transcript(1))
    assert "quel temps ?" in transcript and "quel temp ?" not in transcript
    assert "Il fait beau." in transcript  # la réponse déjà donnée reste dans le fil
    database.close()


async def test_a_real_change_still_gets_a_new_answer(tmp_path: Path) -> None:
    client = ScriptedClient(
        [Completion(text="À Lyon.", model="fake"), Completion(text="À Paris.", model="fake")]
    )
    service, database = _open(tmp_path, client)
    assert await service.handle(_message(mentioned=True, message_id=4, text="Maria météo à Lyon"))
    service.remember_reply(4, 99)
    again = await service.handle(
        _message(mentioned=True, message_id=4, text="Maria météo à Paris", edited=True)
    )
    assert again is not None and again.chunks == ("À Paris.",)
    database.close()
