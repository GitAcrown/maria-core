"""URLs publiques et texte extrait d'une page. Rien n'est téléchargé ici."""

import ipaddress
import re
import socket
from html.parser import HTMLParser
from urllib.parse import urlparse

_BLOCKED_HOSTS = frozenset({"localhost", "metadata.google.internal"})
_SKIP_TAGS = frozenset({"script", "style", "noscript"})
_BREAK_TAGS = frozenset({"p", "br", "div", "li", "tr", "h1", "h2", "h3", "h4"})


def safe_url(raw: str) -> str:
    """Normalise une URL http(s) publique. Lève ValueError sinon."""
    parsed = urlparse((raw or "").strip())
    if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
        raise ValueError("URL http(s) requise, sans identifiants.")
    host = (parsed.hostname or "").rstrip(".").lower()
    if not host or host in _BLOCKED_HOSTS or host.endswith(".local"):
        raise ValueError("Hôte refusé.")
    if parsed.port not in {None, 80, 443}:
        raise ValueError("Port refusé.")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ValueError("Adresse non publique refusée.")
    return parsed.geturl()


def assert_public_host(host: str) -> None:
    """Résout le nom et refuse toute adresse qui n'est pas publique."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise ValueError("Nom d'hôte introuvable.") from exc
    if not infos:
        raise ValueError("Nom d'hôte introuvable.")
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if not address.is_global:
            raise ValueError("Adresse non publique refusée.")


def html_to_text(raw: str) -> str:
    parser = _TextExtractor()
    parser.feed(raw or "")
    parser.close()
    text = "".join(parser.parts)
    text = re.sub(r"[ \t]*\n[ \t]*", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return re.sub(r"[ \t]{2,}", " ", text).strip()


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            self._skip += 1
        if tag in _BREAK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip:
            self._skip -= 1
        if tag in _BREAK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)
