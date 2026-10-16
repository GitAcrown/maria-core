"""« Demander à MARIA » : un clic droit, une réponse éphémère, jamais de suite."""

from types import SimpleNamespace
from typing import Any

import discord

from maria_core.conversation.assist import COOLDOWN_S, FAILED, Assistant
from maria_core.discord.ask_menu import NAME, AskCog, AskHub
from maria_core.llm.types import Completion
from tests.fakes import ScriptedClient


def _texts(view: discord.ui.LayoutView) -> str:
    return "\n".join(
        item.content for item in view.walk_children() if isinstance(item, discord.ui.TextDisplay)
    )


def _buttons(view: discord.ui.LayoutView) -> list[discord.ui.Button]:
    return [item for item in view.walk_children() if isinstance(item, discord.ui.Button)]


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
    return SimpleNamespace(author=SimpleNamespace(display_name="Léa"), content=content, embeds=[])


async def test_the_menu_offers_three_actions_without_icons() -> None:
    hub = AskHub(Assistant(ScriptedClient([])), _message(), 7)
    hub.build()
    buttons = _buttons(hub)
    assert [button.label for button in buttons] == ["Résumer", "Traduire", "Expliquer"]
    assert all(button.emoji is None for button in buttons)


async def test_a_click_answers_once_with_a_card_that_has_no_button() -> None:
    client = ScriptedClient([Completion(text="Hello everyone", model="fake")])
    hub = AskHub(Assistant(client), _message(), 7)
    hub.build()
    interaction = _Interaction()
    await _buttons(hub)[1].callback(interaction)  # type: ignore[arg-type]
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
    await _buttons(hub)[0].callback(interaction)  # type: ignore[arg-type]
    assert "Doucement" in _texts(interaction.views[0]) and len(client.seen) == 1


def test_the_context_menu_is_a_message_command_for_servers() -> None:
    cog = AskCog(SimpleNamespace(), SimpleNamespace(llm=ScriptedClient([])))  # type: ignore[arg-type]
    menu = cog._menu
    assert menu.type == discord.AppCommandType.message and menu.name == NAME == "Demander à MARIA"
    assert menu.guild_only
