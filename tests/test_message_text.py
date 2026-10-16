"""Le texte d'un message, même sans `content` : cartes en composants, aperçus, transferts."""

from types import SimpleNamespace as Box
from typing import Any

from maria_core.conversation.assist import Assistant
from maria_core.discord.ask_menu import AskHub
from maria_core.discord.message_text import text_of
from maria_core.llm.types import Completion
from tests.fakes import ScriptedClient


def _card(*lines: str) -> Any:
    """Comme une carte de MARIA : un conteneur, des blocs de texte, un séparateur, des boutons."""
    texts = [Box(content=line, children=()) for line in lines]
    section = Box(children=[Box(content="Dans une section", children=()), Box(url="https://x")])
    buttons = Box(children=[Box(label="Retour")])
    return Box(children=[*texts, Box(children=()), section, buttons])


def test_a_card_without_content_gives_the_text_of_its_blocks() -> None:
    message = Box(content="", embeds=[], components=[_card("## Traduction", "Hello everyone")])
    text = text_of(message)
    assert text == "## Traduction\n\nHello everyone\n\nDans une section"
    assert "Retour" not in text


def test_embeds_forwarded_copies_and_plain_content_are_all_read_once() -> None:
    embed = Box(title="Titre", description="Description", fields=[Box(name="Prix", value="12 €")])
    snapshot = Box(content="Message transféré", embeds=[], components=[])
    message = Box(
        content="Bonjour",
        embeds=[embed, embed],
        components=[],
        message_snapshots=[snapshot],
    )
    assert text_of(message) == "Bonjour\n\nTitre\n\nDescription\n\nPrix : 12 €\n\nMessage transféré"
    assert text_of(Box(content=None, embeds=[], components=[])) == ""


async def test_the_menu_works_on_a_card_posted_by_a_bot() -> None:
    client = ScriptedClient([Completion(text="Bonjour à tous", model="fake")])
    author = Box(name="maria", display_name="MARIA")
    message = Box(author=author, content="", embeds=[], components=[_card("Hello everyone")])
    hub = AskHub(Assistant(client), message, 7)
    hub.build()

    class _Interaction:
        user = Box(id=7)

        def __init__(self) -> None:
            self.response = Box(edit_message=self._edit)

        async def _edit(self, **_options: Any) -> None: ...

        async def edit_original_response(self, **_options: Any) -> None: ...

    (picker,) = [i for i in hub.walk_children() if hasattr(i, "options")]
    await picker.run(_Interaction(), "translate")
    assert "Hello everyone" in str(client.seen[0][1]["content"])
