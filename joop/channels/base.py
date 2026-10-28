"""Channel-neutral message shape."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class IncomingMessage:
    channel: str  # telegram | whatsapp | instagram
    chat_id: str  # where replies go on that channel
    kind: str = "text"  # text | media | command | echo (a message the business sent itself)
    text: str = ""
    user_name: str = ""
    external_id: str = ""  # channel message id, used to drop duplicate webhook deliveries
    media_label: str = ""  # e.g. "голосовое сообщение"


TELEGRAM_MAX = 4000
WHATSAPP_MAX = 4000
INSTAGRAM_MAX = 1000


def clip(text: str, limit: int) -> str:
    text = text or ""
    return text if len(text) <= limit else text[: limit - 1] + "…"
