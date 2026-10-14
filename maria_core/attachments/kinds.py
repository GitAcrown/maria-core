"""Ce que MARIA sait lire ou non : fichiers joints et liens. Des règles, aucun appel au modèle."""

from dataclasses import dataclass
from urllib.parse import urlparse

TEXT_EXTENSIONS = (
    ".txt",
    ".md",
    ".py",
    ".js",
    ".ts",
    ".html",
    ".css",
    ".json",
    ".xml",
    ".csv",
    ".log",
    ".yml",
    ".yaml",
    ".toml",
    ".ini",
    ".sql",
    ".srt",
    ".tsv",
)
_VIDEO = (".mp4", ".mov", ".mkv", ".avi", ".m4v", ".wmv", ".flv", ".mpg", ".mpeg")
_AUDIO = (".mp3", ".wav", ".ogg", ".m4a", ".flac", ".aac", ".opus")
_ARCHIVE = (".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz")
_PROGRAM = (".exe", ".msi", ".apk", ".dmg", ".bat", ".sh", ".jar", ".iso")
_OFFICE = (".xlsx", ".xls", ".pptx", ".ppt", ".doc", ".odt", ".ods", ".odp", ".rtf", ".pages")
_IMAGE = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".heic", ".svg", ".tiff")
_WALLED = (
    "tiktok.com",
    "instagram.com",
    "facebook.com",
    "fb.watch",
    "x.com",
    "twitter.com",
    "threads.net",
    "snapchat.com",
    "linkedin.com",
)
_VIDEO_SITES = ("vimeo.com", "dailymotion.com", "streamable.com", "twitch.tv", "clips.twitch.tv")
_YOUTUBE = ("youtube.com", "youtu.be", "m.youtube.com", "music.youtube.com")
_SKIPPED = ("discord.gg", "discord.com", "discordapp.com", "tenor.com", "giphy.com")


@dataclass(frozen=True, slots=True)
class FileKind:
    """`how` : text, docx, pdf (lisibles) ou none ; `label` : ce que c'est, pour le dire."""

    how: str
    label: str


@dataclass(frozen=True, slots=True)
class LinkKind:
    """`how` : page (à lire), youtube, pdf, skip, ou none avec la raison dans `label`."""

    how: str
    label: str


def classify_file(filename: str, content_type: str = "") -> FileKind:
    name = (filename or "").lower()
    kind = (content_type or "").lower()
    if name.endswith(".pdf") or "pdf" in kind:
        return FileKind("pdf", "PDF")
    if name.endswith(".docx"):
        return FileKind("docx", "document Word")
    if name.endswith(TEXT_EXTENSIONS) or kind.startswith("text/"):
        return FileKind("text", "fichier texte")
    return FileKind("none", _unreadable(name, kind))


def _unreadable(name: str, kind: str) -> str:
    if kind.startswith("video/") or name.endswith(_VIDEO):
        return "vidéo"
    if kind.startswith("audio/") or name.endswith(_AUDIO):
        return "audio"
    if kind.startswith("image/") or name.endswith(_IMAGE):
        return "image au-delà de la limite"
    if name.endswith(_ARCHIVE):
        return "archive"
    if name.endswith(_PROGRAM):
        return "programme (jamais ouvert)"
    if name.endswith(_OFFICE):
        return "document Office (seul le .docx est lu)"
    return "type de fichier inconnu"


def classify_link(url: str) -> LinkKind:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    path = parsed.path.lower()
    if _is(host, _SKIPPED):
        return LinkKind("skip", "")
    if _is(host, _YOUTUBE):
        return LinkKind("youtube", "vidéo YouTube")
    if _is(host, _WALLED):
        return LinkKind("none", "réseau social fermé, ni la vidéo ni le texte ne sont lisibles")
    if _is(host, _VIDEO_SITES) or path.endswith(_VIDEO):
        return LinkKind("none", "vidéo en ligne")
    if path.endswith(_AUDIO):
        return LinkKind("none", "fichier audio en ligne")
    if path.endswith(_IMAGE):
        return LinkKind("skip", "")
    if path.endswith(".pdf"):
        return LinkKind("pdf", "PDF en ligne")
    if path.endswith(_ARCHIVE + _PROGRAM + _OFFICE):
        return LinkKind("none", "fichier à télécharger, pas une page")
    return LinkKind("page", "page web")


def _is(host: str, names: tuple[str, ...]) -> bool:
    return any(host == name or host.endswith("." + name) for name in names)
