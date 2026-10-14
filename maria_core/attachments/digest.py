"""Ce que MARIA lit d'office dans un message qui lui est adressé : fichiers joints et liens.

Tout ce qu'elle ne peut pas lire est annoncé NON LISIBLE, avec la raison, pour qu'elle le dise
franchement au lieu d'inventer.
"""

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from maria_core.attachments.extract import Unreadable, decode_text, docx_text, pdf_text
from maria_core.attachments.kinds import classify_file, classify_link
from maria_core.capabilities.net import html_to_text
from maria_core.capabilities.page import Fetched
from maria_core.conversation.model import FileRef, Inbound

logger = logging.getLogger(__name__)

type LinkFetcher = Callable[[str], Awaitable[Fetched]]

MAX_TEXT_BYTES = 1_000_000
MAX_DOC_BYTES = 10_000_000
_URL = re.compile(r"https?://[^\s<>\"']+")
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_TRAILING = ".,;:!?)]}»"
_HEAD = "[PIÈCES JOINTES ET LIENS DU MESSAGE]"
_RULE = (
    "Ce qui est NON LISIBLE n'a PAS été vu : dis-le simplement à la personne (ce que tu ne peux "
    "pas faire, et si utile une alternative : coller le texte, une capture d'écran). N'invente "
    "rien sur son contenu."
)


@dataclass(slots=True)
class _Found:
    read: list[str]
    unread: list[str]


class Digester:
    def __init__(
        self,
        fetch: LinkFetcher | None = None,
        *,
        file_chars: int = 6000,
        link_chars: int = 1800,
        max_links: int = 3,
        max_files: int = 5,
        timeout: float = 8.0,
    ) -> None:
        self._fetch = fetch
        self._file_chars = file_chars
        self._link_chars = link_chars
        self._max_links = max_links
        self._max_files = max_files
        self._timeout = timeout

    async def build(self, message: Inbound) -> str:
        found = _Found([], [])
        await self._files(message, found)
        if message.audio is not None:
            found.unread.append(f"{message.audio.filename} : audio, pas écouté")
        await self._links(message.text, found)
        if not found.read and not found.unread:
            return ""
        lines = [_HEAD, *found.read]
        if found.unread:
            lines.append("NON LISIBLE :")
            lines.extend(f"- {item}" for item in found.unread)
            lines.append(_RULE)
        return "\n".join(lines)

    async def _files(self, message: Inbound, found: _Found) -> None:
        for item in message.files[: self._max_files]:
            await self._file(item, found)
        extra = len(message.files) - self._max_files
        if extra > 0:
            found.unread.append(f"{extra} fichier(s) en plus : au-delà de {self._max_files}")

    async def _file(self, item: FileRef, found: _Found) -> None:
        kind = classify_file(item.filename, item.content_type)
        if kind.how == "none":
            found.unread.append(f"{item.filename} : {kind.label}")
            return
        limit = MAX_TEXT_BYTES if kind.how == "text" else MAX_DOC_BYTES
        if item.size > limit:
            found.unread.append(f"{item.filename} : {kind.label} trop volumineux")
            return
        try:
            raw = await item.load()
            block = await asyncio.to_thread(self._extract, item.filename, kind.how, raw)
        except Unreadable as exc:
            found.unread.append(f"{item.filename} : {exc}")
        except Exception:
            logger.warning("Fichier %s illisible", item.filename, exc_info=True)
            found.unread.append(f"{item.filename} : lecture impossible")
        else:
            found.read.append(block)

    def _extract(self, name: str, how: str, raw: bytes) -> str:
        if how == "docx":
            return (
                f"[Fichier {name} — document Word]\n{self._clip(docx_text(raw), self._file_chars)}"
            )
        if how == "pdf":
            text, pages = pdf_text(raw)
            return f"[Fichier {name} — PDF, {pages} page(s)]\n{self._clip(text, self._file_chars)}"
        text = decode_text(raw)
        if not text.strip():
            raise Unreadable("fichier vide ou illisible")
        extension = name.rsplit(".", 1)[-1] if "." in name else "txt"
        return f"[Fichier {name}]\n```{extension}\n{self._clip(text, self._file_chars)}\n```"

    async def _links(self, text: str, found: _Found) -> None:
        urls = links_of(text)
        if not urls:
            return
        shown = urls[: self._max_links]
        if len(urls) > len(shown):
            found.unread.append(f"{len(urls) - len(shown)} lien(s) en plus : au-delà de 3")
        await asyncio.gather(*(self._link(url, found) for url in shown))

    async def _link(self, url: str, found: _Found) -> None:
        kind = classify_link(url)
        if kind.how == "skip":
            return
        if kind.how == "youtube":
            found.read.append(
                f"[Lien {url}] vidéo YouTube, pas encore lue : appelle read_youtube pour en "
                "voir la transcription."
            )
            return
        if kind.how == "none" or self._fetch is None:
            found.unread.append(f"{url} : {kind.label or 'lien non lisible'}")
            return
        try:
            page = await asyncio.wait_for(self._fetch(url), self._timeout)
            block = await asyncio.to_thread(self._page, url, page)
        except TimeoutError:
            found.unread.append(f"{url} : délai dépassé")
        except Unreadable as exc:
            found.unread.append(f"{url} : {exc}")
        except ValueError as exc:
            found.unread.append(f"{url} : {str(exc).rstrip('.').lower() or 'illisible'}")
        else:
            found.read.append(block)

    def _page(self, url: str, page: Fetched) -> str:
        kind = page.content_type
        if "pdf" in kind or page.url.lower().split("?", 1)[0].endswith(".pdf"):
            text, pages = pdf_text(page.body)
            return f"[Lien {url} — PDF, {pages} page(s)]\n{self._clip(text, self._link_chars)}"
        if kind.startswith(("video/", "audio/", "image/")):
            raise Unreadable(f"contenu {kind.split('/', 1)[0]}, pas une page")
        if "html" in kind or not kind:
            raw = page.body.decode(page.charset, errors="replace")
            title = _title(raw)
            text = html_to_text(raw)
            if title and text.startswith(title):
                text = text[len(title) :].lstrip()
            head = f"[Lien {url} — « {title} »]" if title else f"[Lien {url}]"
        elif kind.startswith("text/") or "json" in kind or "xml" in kind:
            text = decode_text(page.body)
            head = f"[Lien {url}]"
        else:
            raise Unreadable(f"contenu de type {kind.split(';', 1)[0] or 'inconnu'}")
        if not text.strip():
            raise Unreadable("page sans texte (probablement chargée par JavaScript)")
        return f"{head}\n{self._clip(text, self._link_chars)}"

    @staticmethod
    def _clip(text: str, limit: int) -> str:
        flat = text.strip()
        return flat if len(flat) <= limit else flat[:limit].rstrip() + "\n… [tronqué]"


def links_of(text: str) -> list[str]:
    """Adresses du message, sans doublon, sans ponctuation collée à la fin."""
    found: dict[str, None] = {}
    for match in _URL.finditer(text or ""):
        found[match.group(0).rstrip(_TRAILING)] = None
    return list(found)


def _title(raw: str) -> str:
    found = _TITLE.search(raw[:20000])
    if found is None:
        return ""
    return " ".join(re.sub(r"<[^>]+>", " ", found.group(1)).split())[:120]
