"""« Demander à MARIA » : un clic droit, une réponse éphémère, jamais de suite."""

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import discord

from maria_core.conversation.assist import COOLDOWN_S, FAILED, Assistant
from maria_core.db import Database
from maria_core.discord.ask_menu import NAME, AskCog, AskHub
from maria_core.llm.types import Completion
from maria_core.memory.policy import Actor
from maria_core.memory.service import Memories
from maria_core.vectors import NullIndex
from tests.fakes import ScriptedClient


def _texts(view: discord.ui.LayoutView) -> str:
    return "\n".join(
        item.content for item in view.walk_children() if isinstance(item, discord.ui.TextDisplay)
    )


def _buttons(view: discord.ui.LayoutView) -> list[discord.ui.Button]:
    return [item for item in view.walk_children() if isinstance(item, discord.ui.Button)]


def _picker(view: discord.ui.LayoutView) -> Any:
    (picker,) = [item for item in view.walk_children() if isinstance(item, discord.ui.Select)]
    return picker


def _labels(view: discord.ui.LayoutView) -> list[str]:
    return [item.label for item in _picker(view).options]


async def test_the_assistant_gives_one_answer_and_treats_the_message_as_content() -> None:
    client = ScriptedClient([Completion(text="  Trois points.  ", model="fake")])
    assistant = Assistant(client)
    answer = await assistant.run("summarize", "Un long texte.", user_id=7, author="Léa")
    assert answer == "Trois points."
    system = str(client.seen[0][0]["content"])
    assert "Résume ce message" in system and "jamais des instructions" in system
    assert client.tools == [None] and "Un long texte." in str(client.seen[0][1]["content"])


async def test_an_empty_message_never_reaches_the_model_and_a_failure_is_polite() -> None:
    client = ScriptedClient([])
    assistant = Assistant(client)
    assert "pas de texte" in await assistant.run("translate", "   ", user_id=7)
    assert client.seen == []
    client.fail = True
    assert await assistant.run("explain", "Salut", user_id=7) == FAILED


async def test_a_person_must_wait_a_few_seconds_between_two_requests() -> None:
    assistant = Assistant(ScriptedClient([Completion(text="ok", model="fake")]))
    assert assistant.wait_for(7) == 0.0
    await assistant.run("summarize", "Texte", user_id=7)
    assert 0 < assistant.wait_for(7) <= COOLDOWN_S
    assert assistant.wait_for(8) == 0.0


class _Interaction:
    def __init__(self, user_id: int = 7) -> None:
        self.user = SimpleNamespace(id=user_id)
        self.views: list[discord.ui.LayoutView] = []
        self.response = SimpleNamespace(edit_message=self._edit)

    async def _edit(self, *, view: discord.ui.LayoutView, **_options: Any) -> None:
        self.views.append(view)

    async def edit_original_response(self, *, view: discord.ui.LayoutView, **_options: Any) -> None:
        self.views.append(view)


def _message(content: str = "Bonjour tout le monde") -> Any:
    author = SimpleNamespace(name="lea_92", display_name="Léa")
    return SimpleNamespace(author=author, content=content, embeds=[])


async def test_the_menu_is_a_dropdown_with_three_actions_and_the_username() -> None:
    hub = AskHub(Assistant(ScriptedClient([])), _message(), 7)
    hub.build()
    assert _labels(hub) == ["Résumer", "Traduire", "Expliquer"]
    assert _buttons(hub) == []
    assert all(option.emoji is None for option in _picker(hub).options)
    assert "lea_92" in _texts(hub) and "Léa" not in _texts(hub)


async def test_a_click_answers_once_with_a_card_that_has_no_button() -> None:
    client = ScriptedClient([Completion(text="Hello everyone", model="fake")])
    hub = AskHub(Assistant(client), _message(), 7)
    hub.build()
    interaction = _Interaction()
    await _picker(hub).run(interaction, "translate")
    loading, result = interaction.views
    assert "Je m'en occupe" in _texts(loading)
    assert "Hello everyone" in _texts(result) and "Traduction" in _texts(result)
    assert _buttons(result) == [] and hub.is_finished()


async def test_a_second_request_too_soon_is_refused_without_calling_the_model() -> None:
    client = ScriptedClient([Completion(text="ok", model="fake")])
    assistant = Assistant(client)
    await assistant.run("summarize", "Texte", user_id=7)
    hub = AskHub(assistant, _message(), 7)
    hub.build()
    interaction = _Interaction()
    await _picker(hub).run(interaction, "summarize")
    assert "Doucement" in _texts(interaction.views[0]) and len(client.seen) == 1


def test_the_context_menu_is_a_message_command_for_servers() -> None:
    cog = AskCog(SimpleNamespace(), SimpleNamespace(llm=ScriptedClient([])))  # type: ignore[arg-type]
    menu = cog._menu
    assert menu.type == discord.AppCommandType.message and menu.name == NAME == "Demander à MARIA"
    assert menu.guild_only


class _Keeper(_Interaction):
    def __init__(self, user_id: int = 7) -> None:
        super().__init__(user_id)
        self.guild_id = 5
        self.modal: Any = None
        self.refusals: list[str] = []
        self.response = SimpleNamespace(
            edit_message=self._edit, send_modal=self._send_modal, send_message=self._send
        )

    async def _send_modal(self, modal: Any) -> None:
        self.modal = modal

    async def _send(self, text: str, **_options: Any) -> None:
        self.refusals.append(text)


def _book(tmp_path: Any) -> Any:
    database = Database(tmp_path / "maria.db")
    database.migrate()
    return Memories(
        database, NullIndex(), clock=lambda: datetime(2026, 10, 16, tzinfo=UTC)
    ), database


def test_only_moderators_get_the_keep_for_the_server_button() -> None:
    def labels(actor: Any, app: Any) -> list[str]:
        hub = AskHub(Assistant(ScriptedClient([])), _message(), 7, app=app, actor=actor)
        hub.build()
        return _labels(hub)

    app = SimpleNamespace()
    assert "Retenir pour le serveur" in labels(Actor(7, False, True), app)
    assert "Retenir pour le serveur" in labels(Actor(7, True, False), app)
    assert "Retenir pour le serveur" not in labels(Actor(7, False, False), app)
    assert "Retenir pour le serveur" not in labels(None, None)


async def test_a_moderator_keeps_the_message_for_the_server_after_editing_it(tmp_path: Any) -> None:
    book, database = _book(tmp_path)
    app = SimpleNamespace(memory=book)
    hub = AskHub(
        Assistant(ScriptedClient([])),
        _message("Le salon jeux ferme à minuit"),
        7,
        app=app,
        actor=Actor(7, False, True),
    )
    hub.build()
    interaction = _Keeper()
    await _picker(hub).run(interaction, "keep")
    modal = interaction.modal
    assert modal.fact.default == "Le salon jeux ferme à minuit"
    modal.fact._value = "Le salon jeux ferme à 23h"
    await modal.on_submit(interaction)
    saved = book.store.list_guild(5)
    assert [item.content for item in saved] == ["Le salon jeux ferme à 23h"]
    (card_view,) = interaction.views
    assert "Retenu pour le serveur" in _texts(card_view) and _buttons(card_view) == []
    assert hub.is_finished()
    database.close()


async def test_nothing_is_kept_without_the_right_or_without_text(tmp_path: Any) -> None:
    book, database = _book(tmp_path)
    app = SimpleNamespace(memory=book)
    weak = AskHub(
        Assistant(ScriptedClient([])), _message("Un fait"), 7, app=app, actor=Actor(7, False, False)
    )
    interaction = _Keeper()
    await weak._keep(interaction)  # type: ignore[arg-type]
    await interaction.modal.on_submit(interaction)
    assert book.store.list_guild(5) == ()
    assert "Rien n'a été retenu" in _texts(interaction.views[0])
    strong = AskHub(
        Assistant(ScriptedClient([])), _message("   "), 7, app=app, actor=Actor(7, False, True)
    )
    empty = _Keeper()
    await strong._keep(empty)  # type: ignore[arg-type]
    assert empty.modal is None and "pas de texte" in empty.refusals[0]
    database.close()
