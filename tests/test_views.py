import discord

from maria_core.capabilities.builtin.layout import card_from_spec, clip, render_draft
from maria_core.discord import layout
from maria_core.discord.voice import TRANSCRIPT_LABEL, transcript_footer
from maria_core.ui import emojis as icons
from maria_core.ui.emojis import FALLBACKS, FOOTBALL, MOVIE, downgrade, emoji_id
from maria_core.ui.widgets import card, gallery, separator, text


def test_every_custom_emoji_from_maria_r_has_a_fallback() -> None:
    tags = [
        value
        for name, value in vars(icons).items()
        if name.isupper() and isinstance(value, str) and value.startswith("<:")
    ]
    assert len(tags) == 23
    assert set(tags) <= set(FALLBACKS)


def test_custom_emojis_fall_back_to_unicode_only_when_missing() -> None:
    line = f"{FOOTBALL} Ligue 1 · {MOVIE} Dune"
    assert downgrade(line, None) == line
    shown = downgrade(line, frozenset({emoji_id(MOVIE)}))
    assert shown == f"{FALLBACKS[FOOTBALL]} Ligue 1 · {MOVIE} Dune"


def test_free_widget_has_no_accent_and_a_rule_under_the_title() -> None:
    built = card_from_spec({"title": "Carbonara", "blocks": [{"type": "text", "content": "x"}]})
    assert built.accent is None
    assert [block.kind for block in built.blocks] == ["text", "separator", "text"]
    asked = card_from_spec({"title": "T", "accent": "#ff0000", "blocks": [{"type": "text"}]})
    assert asked.accent == 0xFF0000


def test_clip_cuts_on_a_sentence() -> None:
    assert clip("Une phrase. " * 300, 100).endswith("phrase…")
    assert clip("court", 100) == "court"


def test_layout_wide_rules_bare_galleries_and_quiet_links() -> None:
    views = layout.build_views(
        intro="Voilà https://exemple.fr",
        cards=(
            card(text("## Titre"), separator(wide=True), text("[lien](https://a.fr)")),
            card(gallery(["https://a.fr/1.png"], {"https://a.fr/1.png": "légende"}), bare=True),
        ),
    )
    items = views[0].children
    assert isinstance(items[0], discord.ui.TextDisplay)
    assert items[0].content == "Voilà <https://exemple.fr>"
    assert isinstance(items[1], discord.ui.Separator)
    container = items[2]
    assert isinstance(container, discord.ui.Container)
    assert container.accent_colour is None
    rule = container.children[1]
    assert isinstance(rule, discord.ui.Separator)
    assert rule.spacing is discord.SeparatorSpacing.large
    assert container.children[2].content == "[lien](<https://a.fr>)"
    assert isinstance(items[3], discord.ui.MediaGallery)
    assert items[3].items[0].description == "légende"


def test_a_draft_is_a_small_card_under_the_comment_with_a_line_between() -> None:
    data = {
        "id": 14,
        "kind": "Écoute",
        "when": "quand on parle de « corset »",
        "if": "",
        "say": "Quelqu'un parle du film Le Corset",
    }
    rendered = render_draft(data)
    views = layout.build_views(intro="Je te préviens si on en parle.", cards=rendered.cards)
    kinds = [type(item).__name__ for item in views[0].children]
    assert kinds == ["TextDisplay", "Separator", "Container"]
    inside = views[0].children[2].children
    assert [type(item).__name__ for item in inside] == ["TextDisplay", "TextDisplay"]
    assert "**Quand** · quand on parle de « corset »" in inside[0].content
    assert "**Message** · Quelqu'un parle du film Le Corset" in inside[0].content
    assert inside[1].content == "-# Écoute · brouillon n°14 · réponds « oui » ou « non »"
    assert not any(isinstance(item, discord.ui.Button) for item in views[0].walk_children())


def test_a_requested_transcript_says_who_asked() -> None:
    assert transcript_footer() == TRANSCRIPT_LABEL
    assert transcript_footer("Léa") == f"{TRANSCRIPT_LABEL} · demandé par Léa"
