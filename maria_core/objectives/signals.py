"""Événement publié par Discord. Le moteur ne connaît pas les messages Discord."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ObjectiveSignal:
    """`kind` : message, reaction, voice_join, voice_leave, voice_stream ou join."""

    kind: str
    key: str
    channel_id: int
    guild_id: int | None
    user_id: int
    text: str = ""
    reply_to_bot: bool = False
    author_name: str = ""
    url: str = ""
    place: str = ""
    message_id: int | None = None
    author_is_bot: bool = False
    mentioned_ids: tuple[int, ...] = ()
    has_link: bool = False
    media: tuple[str, ...] = ()
    emoji: str = ""
    emoji_name: str = ""

    def fact(self) -> str:
        """Phrase courte qui décrit l'événement, pour le message envoyé et le juge."""
        who = self.author_name or "quelqu'un"
        place = self.place or "un vocal"
        facts = {
            "voice_join": f"{who} a rejoint {place}",
            "voice_leave": f"{who} a quitté {place}",
            "voice_stream": f"{who} a lancé un stream dans {place}",
            "join": f"{who} a rejoint le serveur",
            "reaction": f"{who} a réagi avec {self.emoji} à un message",
        }
        if self.kind in facts:
            return facts[self.kind]
        return f"Message de {who} : « {self.text[:300]} »"
