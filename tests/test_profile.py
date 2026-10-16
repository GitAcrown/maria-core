"""Le profil : champs réglables, style déduit, remplissage des outils, menu visible."""

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import discord
import pytest

from maria_core.capabilities import Capability, CapabilityRegistry, Context, Result, Risk
from maria_core.capabilities.runner import CACHE, invoke
from maria_core.config import Settings
from maria_core.conversation.compose import compose
from maria_core.conversation.model import Inbound
from maria_core.db import Database
from maria_core.discord.profile_menu import ProfileHub
from maria_core.llm.loop import LoopResult, ToolRecord
from maria_core.llm.types import ToolCall
from maria_core.profile import Profiles
from maria_core.profile.birthday import normalize, show
from maria_core.profile.extract import extract, extract_memory
from maria_core.profile.style import verdict
from maria_core.ui.widgets import WidgetRegistry

_NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)


def _profiles(tmp_path: Path) -> tuple[Profiles, Database]:
    database = Database(tmp_path / "maria.db")
    database.migrate()
    return Profiles(database, clock=lambda: _NOW), database


def _context(user_id: int = 7) -> Context:
    return Context(
        user_id=user_id,
        guild_id=5,
        channel_id=3,
        message_id=1,
        is_owner=False,
        is_moderator=False,
        text="",
    )


def test_clear_statements_fill_the_city_and_the_team() -> None:
    assert extract("Salut, j'habite à Lyon depuis 2020") == {"city": "Lyon"}
    assert extract("je vis à Saint-Étienne") == {"city": "Saint-Étienne"}
    assert extract("je supporte l'OM") == {"team": "OM"}
    assert extract("mon équipe c'est le Paris Saint-Germain") == {"team": "PSG"}
    assert extract("j'habite chez ma mère") == {}
    assert extract("on va à Lyon demain") == {}


def test_what_the_person_sets_wins_over_what_is_learned(tmp_path: Path) -> None:
    profiles, database = _profiles(tmp_path)
    assert profiles.store.learn(7, "city", "Lyon", _NOW) is True
    assert profiles.store.learn(7, "city", "Lyon", _NOW) is False
    profiles.store.set(7, "city", "Paris", _NOW)
    assert profiles.store.learn(7, "city", "Lille", _NOW) is False
    assert profiles.store.value(7, "city") == "Paris"
    assert profiles.store.all(7)["city"].source == "user"
    with pytest.raises(ValueError):
        profiles.store.set(7, "length", "gigantesque", _NOW)
    with pytest.raises(ValueError):
        profiles.store.set(7, "inconnu", "x", _NOW)
    database.close()


def test_style_is_deduced_only_after_enough_messages() -> None:
    assert verdict(3, 4.0, 0.9, 0.3, 0.0) == {}
    assert verdict(20, 4.0, 0.9, 0.3, 0.0) == {"length": "short", "tone": "casual"}
    assert verdict(20, 35.0, 0.1, 0.0, 0.4) == {"length": "long", "tone": "polished"}
    assert verdict(20, 15.0, 0.4, 0.0, 0.0) == {}


def _message(text: str, *, author: int = 7, dm: bool = False) -> Inbound:
    return Inbound(
        channel_id=3,
        message_id=10,
        guild_id=None if dm else 5,
        author_id=author,
        author_name="Lea",
        text=text,
        is_dm=dm,
        author_is_bot=False,
        mentioned=True,
        reply_to_bot=False,
        mention_everyone=False,
        edited=False,
        author_is_owner=False,
        author_is_moderator=False,
        bot_names=("maria",),
        created_at=_NOW,
    )


def test_observing_messages_learns_style_and_slots_then_feeds_the_prompt(tmp_path: Path) -> None:
    profiles, database = _profiles(tmp_path)
    learned = profiles.observe(_message("j'habite à Lyon"))
    assert learned == ["Ville : Lyon"]
    for text in ("mdr ok", "ça marche", "top merci", "yes", "lol", "ok go", "parfait", "cool"):
        profiles.observe(_message(text))
    found = profiles.resolve(7)
    assert found["city"].value == "Lyon" and found["city"].source == "auto"
    assert found["length"].value == "short" and found["length"].source == "style"
    text = profiles.prompt_for(_message("salut"))
    assert "ville : Lyon" in text
    assert "réponses courtes" in text
    assert "@profil" in text
    assert profiles.prompt_for(_message("salut", dm=True)) == ""
    assert profiles.prompt_for(_message("salut", author=9)) == ""
    database.close()


async def test_a_tool_reads_the_profile_when_asked_and_says_so(tmp_path: Path) -> None:
    profiles, database = _profiles(tmp_path)
    profiles.store.set(7, "city", "Lyon", _NOW)
    seen: list[str] = []

    async def run(_context: Context, args: Any) -> Result:
        seen.append(str(args["city"]))
        return Result(ok=True, data={"city": args["city"]})

    registry = CapabilityRegistry()
    registry.register(
        Capability(
            name="probe_weather",
            description="Sonde",
            parameters={
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            },
            risk=Risk.READ,
            run=run,
            profile_args=(("city", "city", True),),
            cache_s=60,
        )
    )
    CACHE.clear()
    settings = Settings.for_tests(tmp_path)

    async def call(city: str, user: int = 7) -> Result:
        return await invoke(
            registry,
            settings,
            _context(user),
            ToolCall(id="1", name="probe_weather", arguments={"city": city}),
            slots=profiles,
        )

    mine = await call("@profil")
    assert mine.ok and seen == ["Lyon"]
    assert mine.data["profile_used"][0] == {"slot": "city", "label": "Ville", "value": "Lyon"}
    empty = await call("")
    assert empty.ok and seen == ["Lyon"]  # même ville : servi par le cache
    other = await call("Paris")
    assert other.ok and "profile_used" not in other.data
    nobody = await call("@profil", user=9)
    assert not nobody.ok and "/moi" in nobody.error
    database.close()


def test_the_answer_shows_which_profile_fields_were_used() -> None:
    mark = {"slot": "city", "label": "Ville", "value": "Lyon"}
    result = Result(ok=True, data={"profile_used": [mark]})
    record = ToolRecord("get_weather", {"city": "@profil"}, result)
    outcome = LoopResult(
        "Il fait beau.", ("get_weather",), 1, 0, 0, "m", 0, True, records=(record,)
    )
    composed = compose(outcome, WidgetRegistry(), ("maria",))
    assert "-# 🏠 Lyon · ville de ton profil" in composed.footer


async def test_the_profile_menu_shows_values_and_where_they_come_from(tmp_path: Path) -> None:
    profiles, database = _profiles(tmp_path)
    profiles.store.set(7, "city", "Lyon", _NOW)
    profiles.store.learn(7, "team", "OM", _NOW)
    app: Any = SimpleNamespace(profiles=profiles)
    hub = ProfileHub(app, 7, "Lea")
    await hub.load()
    hub.build()
    texts = "\n".join(
        item.content for item in hub.walk_children() if isinstance(item, discord.ui.TextDisplay)
    )
    assert "## Profil · Lea" in texts
    assert "**Ville** · Lyon · *réglé par toi*" in texts
    assert "**Équipe de foot** · OM · *appris par MARIA, modifiable*" in texts
    assert "**Ton** · *par défaut*" in texts
    assert len(list(hub.walk_children())) <= 40
    hub.selected, hub.screen = "city", "slot"
    hub.build()
    labels = [
        str(item.label) for item in hub.walk_children() if isinstance(item, discord.ui.Button)
    ]
    assert labels == ["Modifier", "Effacer", "← Retour"]
    hub.selected = "tone"
    hub.build()
    selects = [item for item in hub.walk_children() if isinstance(item, discord.ui.Select)]
    assert selects[0].options[0].label == "Automatique"
    database.close()


def test_a_memory_written_about_the_person_gives_their_city_and_team() -> None:
    assert extract_memory("Tu habites à Saint-Ouen-l'Aumône et tu es né le 22 juillet 1999.") == {
        "city": "Saint-Ouen-l'Aumône",
        "birthday": "22/07",
    }
    assert extract_memory("Le membre habite à Saint-Ouen-L'Aumône (95) et fête le 22/07.") == {
        "city": "Saint-Ouen-L'Aumône"
    }
    assert extract_memory("Tu supportes l'OM") == {"team": "OM"}
    # le souvenir parle de quelqu'un d'autre, ou de personne : rien à retenir
    assert extract_memory("Son pote Enzo habite à Lyon") == {}
    assert extract_memory("Je suis gay") == {}


def test_the_profile_fills_empty_fields_from_memories_without_overriding_the_person(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "maria.db")
    database.migrate()
    souvenirs = ["Tu habites à Lyon", "Le membre habite à Paris"]
    profiles = Profiles(database, clock=lambda: _NOW, memories=lambda _user: souvenirs)
    assert profiles.value(7, "city") == "Lyon"  # le premier souvenir qui le dit
    profiles.store.set(7, "team", "OM", _NOW)
    souvenirs.append("Tu supportes le PSG")
    assert profiles.value(7, "team") == "OM"  # ce que la personne a réglé prime
    profiles.store.set(8, "city", "Nice", _NOW)
    assert profiles.value(8, "city") == "Nice"
    profiles.absorb(7, force=True)
    assert profiles.value(7, "city") == "Lyon"
    database.close()


def test_a_birthday_is_kept_as_day_and_month_and_shown_in_words() -> None:
    assert normalize("22 juillet 1999") == "22/07"
    assert normalize("1er mai") == "01/05"
    assert normalize("3/4") == "03/04"
    assert normalize("22.07.99") == "22/07"
    assert normalize("29 février") == "29/02"
    assert show("22/07") == "22 juillet" and show("01/05") == "1er mai"
    for wrong in ("31/02", "13/13", "demain", "22 juilet", "0/5"):
        with pytest.raises(ValueError, match=r"anniversaire|date"):
            normalize(wrong)


def test_the_birthday_is_understood_when_said_clearly() -> None:
    assert extract("mon anniversaire c'est le 22 juillet") == {"birthday": "22/07"}
    assert extract("Je suis né le 1er mai 1999") == {"birthday": "01/05"}
    assert extract("mon anniv est le 3/4") == {"birthday": "03/04"}
    assert extract("l'anniversaire de Léa est le 5 mars") == {}
    assert extract("je suis née le 31/02") == {}


def test_the_birthday_is_read_from_memories_about_the_person_only() -> None:
    assert extract_memory("Tu es né le 22 juillet 1999") == {"birthday": "22/07"}
    assert extract_memory("Anniversaire le 22 juillet 1999") == {"birthday": "22/07"}
    assert extract_memory("Le membre habite à Lyon et son anniversaire est le 22/07.") == {
        "city": "Lyon",
        "birthday": "22/07",
    }
    assert extract_memory("Son pote Enzo est né le 5 mars") == {}
    assert extract_memory("Son anniversaire est le 5 mars") == {}


def test_the_profile_stores_the_birthday_and_the_prompt_says_it_in_words(tmp_path: Path) -> None:
    profiles, database = _profiles(tmp_path)
    assert profiles.store.set(7, "birthday", "22 juillet 1999", _NOW) == "22/07"
    with pytest.raises(ValueError, match="illisible"):
        profiles.store.set(7, "birthday", "bientôt", _NOW)
    message = Inbound(
        channel_id=1,
        message_id=1,
        guild_id=5,
        author_id=7,
        author_name="Lea",
        text="salut",
        is_dm=False,
        author_is_bot=False,
        mentioned=True,
        reply_to_bot=False,
        mention_everyone=False,
        edited=False,
        author_is_owner=False,
        author_is_moderator=False,
    )
    assert "anniversaire : 22 juillet" in profiles.prompt_for(message)
    database.close()
