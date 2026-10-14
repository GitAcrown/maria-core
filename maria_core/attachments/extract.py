"""Texte d'un fichier : brut, Word ou PDF. Rien n'est exécuté, tout est borné."""

import html
import io
import re
import zipfile

try:
    import pypdf
except ImportError:  # dépendance facultative : sans elle, un PDF est annoncé non lisible
    pypdf = None  # type: ignore[assignment]

MAX_PDF_PAGES = 40
_DOCX_PART = "word/document.xml"
_DOCX_LIMIT = 8_000_000
_PARAGRAPH = re.compile(r"</w:p>")
_RUN = re.compile(r"<w:t(?:\s[^>]*)?>(.*?)</w:t>", re.DOTALL)
_TAB = re.compile(r"<w:tab\s*/>")
_BREAK = re.compile(r"<w:br\s*/>")


class Unreadable(Exception):
    """Le fichier existe mais on ne peut pas en tirer de texte ; le message dit pourquoi."""


def decode_text(raw: bytes) -> str:
    for encoding in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return ""


def docx_text(raw: bytes) -> str:
    """Les paragraphes d'un .docx, sans analyseur XML (un fichier piégé n'a rien à exploiter)."""
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            info = archive.getinfo(_DOCX_PART)
            if info.file_size > _DOCX_LIMIT:
                raise Unreadable("document Word trop volumineux")
            xml = archive.read(_DOCX_PART).decode("utf-8", errors="replace")
    except (zipfile.BadZipFile, KeyError) as exc:
        raise Unreadable("document Word illisible ou abîmé") from exc
    xml = _TAB.sub("<w:t>\t</w:t>", _BREAK.sub("<w:t>\n</w:t>", xml))
    paragraphs = []
    for block in _PARAGRAPH.split(xml):
        line = "".join(html.unescape(part) for part in _RUN.findall(block)).strip()
        if line:
            paragraphs.append(line)
    text = "\n".join(paragraphs)
    if not text:
        raise Unreadable("document Word sans texte")
    return text


def pdf_text(raw: bytes) -> tuple[str, int]:
    """(texte, nombre de pages). Les PDF scannés ou protégés sont annoncés non lisibles."""
    if pypdf is None:
        raise Unreadable("lecture des PDF indisponible sur ce serveur")
    try:
        reader = pypdf.PdfReader(io.BytesIO(raw))
        if reader.is_encrypted:
            raise Unreadable("PDF protégé par un mot de passe")
        pages = list(reader.pages)
        parts = [(page.extract_text() or "").strip() for page in pages[:MAX_PDF_PAGES]]
    except Unreadable:
        raise
    except Exception as exc:
        raise Unreadable("PDF illisible ou abîmé") from exc
    text = "\n\n".join(part for part in parts if part)
    if not text:
        raise Unreadable("PDF sans texte (probablement un scan)")
    return text, len(pages)
