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
    media_ref: str = ""  # where to download a voice message: Telegram file_id, WhatsApp media id, Instagram URL
    transcribed: bool = False  # the text was recognised from a voice message (joop/voice.py)


MAX_MEDIA_BYTES = 10 * 1024 * 1024  # larger voice files are not downloaded: staff answer them by hand


TELEGRAM_MAX = 4000
WHATSAPP_MAX = 4000
INSTAGRAM_MAX_BYTES = 1000  # Instagram counts UTF-8 bytes; a Cyrillic letter is 2 bytes


def clip(text: str, limit: int) -> str:
    text = text or ""
    return text if len(text) <= limit else text[: limit - 1] + "…"


def clip_bytes(text: str, limit: int) -> str:
    """Cut text to at most `limit` UTF-8 bytes without breaking a character."""
    text = text or ""
    raw = text.encode("utf-8")
    if len(raw) <= limit:
        return text
    ellipsis = "…".encode("utf-8")
    cut = raw[: limit - len(ellipsis)].decode("utf-8", errors="ignore")
    return cut + "…"
