"""Fichiers et liens lus d'office, et ce qui n'est pas lisible annoncé sans détour."""

import asyncio
import io
import zipfile
from datetime import UTC, datetime

import pytest

from maria_core.attachments import Digester, extract
from maria_core.attachments.digest import links_of
from maria_core.attachments.kinds import classify_file, classify_link
from maria_core.capabilities.page import Fetched
from maria_core.conversation.model import AudioRef, FileRef, Inbound


def _file(name: str, data: bytes = b"", *, size: int | None = None, kind: str = "") -> FileRef:
    async def load() -> bytes:
        return data

    return FileRef(
        filename=name, size=len(data) if size is None else size, load=load, content_type=kind
    )


def _message(
    text: str = "", files: tuple[FileRef, ...] = (), audio: AudioRef | None = None
) -> Inbound:
    return Inbound(
        channel_id=3,
        message_id=10,
        guild_id=5,
        author_id=7,
        author_name="Lea",
        text=text,
        is_dm=False,
        author_is_bot=False,
        mentioned=True,
        reply_to_bot=False,
        mention_everyone=False,
        edited=False,
        author_is_owner=False,
        author_is_moderator=False,
        files=files,
        audio=audio,
        created_at=datetime(2026, 10, 14, tzinfo=UTC),
    )


def _docx(*paragraphs: str) -> bytes:
    body = "".join(f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>" for text in paragraphs)
    xml = f'<w:document xmlns:w="x"><w:body>{body}</w:body></w:document>'
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", xml)
    return buffer.getvalue()


async def _no_fetch(url: str) -> Fetched:
    raise AssertionError(f"aucun lien ne devait être lu : {url}")


async def test_text_and_word_files_are_read_and_the_rest_is_declared_unreadable() -> None:
    files = (
        _file("notes.txt", "Bonjour é".encode()),
        _file("cv.docx", _docx("Léa Martin", "Développeuse &amp; passionnée")),
        _file("clip.mp4", b"\x00" * 10, kind="video/mp4"),
        _file("budget.xlsx", b"PK"),
        _file("gros.txt", b"x", size=5_000_000),
    )
    digest = await Digester(_no_fetch).build(_message(files=files))
    assert "[Fichier notes.txt]\n```txt\nBonjour é\n```" in digest
    assert "[Fichier cv.docx — document Word]\nLéa Martin\nDéveloppeuse & passionnée" in digest
    assert "NON LISIBLE :" in digest
    assert "- clip.mp4 : vidéo" in digest
    assert "- budget.xlsx : document Office (seul le .docx est lu)" in digest
    assert "- gros.txt : fichier texte trop volumineux" in digest
    assert "N'invente rien" in digest


async def test_a_pdf_says_why_it_cannot_be_read_when_the_reader_is_missing(monkeypatch) -> None:
    monkeypatch.setattr(extract, "pypdf", None)
    digest = await Digester(_no_fetch).build(_message(files=(_file("a.pdf", b"%PDF-1.4"),)))
    assert "- a.pdf : lecture des PDF indisponible sur ce serveur" in digest


async def test_a_real_pdf_is_read_when_the_library_is_installed() -> None:
    pypdf = pytest.importorskip("pypdf")
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)
    digest = await Digester(_no_fetch).build(
        _message(files=(_file("vide.pdf", buffer.getvalue()),))
    )
    assert "- vide.pdf : PDF sans texte (probablement un scan)" in digest


async def test_links_are_read_and_the_unreadable_ones_are_named() -> None:
    html = b"<html><head><title>Mon article</title></head><body><p>Contenu utile.</p></body></html>"

    async def fetch(url: str) -> Fetched:
        if "casse" in url:
            raise ValueError("Page illisible (HTTP 403).")
        if "lent" in url:
            await asyncio.sleep(1)
        return Fetched(html, "text/html; charset=utf-8", url)

    text = (
        "regarde https://exemple.fr/article, et https://youtu.be/abc123 "
        "et https://www.tiktok.com/@x/video/1 puis https://exemple.fr/casse"
    )
    digest = await Digester(fetch, timeout=0.2, max_links=4).build(_message(text))
    assert "[Lien https://exemple.fr/article — « Mon article »]" in digest
    assert "Contenu utile." in digest
    assert "[Lien https://youtu.be/abc123] vidéo YouTube, pas encore lue" in digest
    assert "- https://www.tiktok.com/@x/video/1 : réseau social fermé" in digest
    assert "- https://exemple.fr/casse : page illisible (http 403)" in digest


async def test_a_slow_link_and_extra_links_are_reported() -> None:
    async def fetch(url: str) -> Fetched:
        await asyncio.sleep(1)
        return Fetched(b"x", "text/html", url)

    text = " ".join(f"https://site{n}.fr/lent" for n in range(5))
    digest = await Digester(fetch, timeout=0.05).build(_message(text))
    assert digest.count("délai dépassé") == 3
    assert "- 2 lien(s) en plus : au-delà de 3" in digest


async def test_an_audio_that_was_not_listened_to_is_declared() -> None:
    audio = AudioRef(filename="vocal.ogg", size=10, load=lambda: asyncio.sleep(0, b""))
    digest = await Digester(_no_fetch).build(_message(audio=audio))
    assert "- vocal.ogg : audio, pas écouté" in digest


async def test_a_plain_message_costs_nothing() -> None:
    assert await Digester(_no_fetch).build(_message("salut, ça va ?")) == ""
    assert await Digester(_no_fetch).build(_message("voir <https://tenor.com/x> ok")) == ""


def test_kinds_and_links() -> None:
    assert classify_file("a.PDF").how == "pdf"
    assert classify_file("a.docx").how == "docx"
    assert classify_file("a.py").how == "text"
    assert classify_file("a.bin", "text/plain").how == "text"
    assert classify_file("a.bin").label == "type de fichier inconnu"
    assert classify_file("a.zip").label == "archive"
    assert classify_link("https://youtu.be/x").how == "youtube"
    assert classify_link("https://x.com/u/status/1").how == "none"
    assert classify_link("https://a.fr/f.mp4").label == "vidéo en ligne"
    assert classify_link("https://a.fr/doc.pdf").how == "pdf"
    assert classify_link("https://a.fr/page").how == "page"
    assert classify_link("https://discord.com/channels/1/2/3").how == "skip"
    assert links_of("vois (https://a.fr/x). Et https://a.fr/x, https://b.fr!") == [
        "https://a.fr/x",
        "https://b.fr",
    ]


def test_a_broken_word_file_is_unreadable_not_a_crash() -> None:
    with pytest.raises(extract.Unreadable):
        extract.docx_text(b"pas un zip")
