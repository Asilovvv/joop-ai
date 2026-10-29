"""Telegram Bot API: parsing updates and calling the API."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from .base import TELEGRAM_MAX, IncomingMessage, clip

log = logging.getLogger(__name__)

MEDIA_LABELS = {
    "voice": "голосовое сообщение",
    "audio": "аудио",
    "video_note": "видеосообщение",
    "video": "видео",
    "photo": "фото",
    "document": "файл",
    "sticker": "стикер",
    "location": "геолокация",
}


def parse_update(update: dict[str, Any]) -> IncomingMessage | None:
    """Turn a Telegram update into an IncomingMessage. Groups: only commands (e.g. /admin) count."""
    msg = update.get("message")
    if not isinstance(msg, dict):
        return None
    chat = msg.get("chat") or {}
    sender = msg.get("from") or {}
    if chat.get("id") is None or sender.get("is_bot"):
        return None
    chat_id = str(chat["id"])
    name = " ".join(x for x in (sender.get("first_name"), sender.get("last_name")) if x).strip()
    external_id = f"tg:{chat_id}:{msg.get('message_id', update.get('update_id', ''))}"
    text = (msg.get("text") or "").strip()
    private = chat.get("type") == "private"

    if text.startswith("/"):
        return IncomingMessage("telegram", chat_id, "command", text, name, external_id)
    if not private:
        return None
    if text:
        return IncomingMessage("telegram", chat_id, "text", text, name, external_id)
    contact = msg.get("contact")
    if isinstance(contact, dict) and contact.get("phone_number"):
        return IncomingMessage("telegram", chat_id, "text", f"Мой телефон: {contact['phone_number']}", name, external_id)
    for key, label in MEDIA_LABELS.items():
        if key in msg:
            caption = (msg.get("caption") or "").strip()
            return IncomingMessage("telegram", chat_id, "media", caption, name, external_id, label)
    return None


class TelegramClient:
    def __init__(self, http: httpx.Client, base_url: str, token: str) -> None:
        self.http = http
        self._base = f"{base_url.rstrip('/')}/bot{token}"

    def _call(self, method: str, payload: dict[str, Any] | None = None, timeout: float = 20.0) -> Any:
        try:
            response = self.http.post(f"{self._base}/{method}", json=payload or {}, timeout=timeout)
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            # The request URL contains the bot token, so only the error type is logged.
            log.warning("Telegram %s failed: %s", method, type(exc).__name__)
            return None
        if not data.get("ok"):
            log.warning("Telegram %s error: %s", method, data.get("description", "unknown"))
            return None
        return data.get("result")

    def send_text(self, chat_id: str, text: str) -> bool:
        return self._call("sendMessage", {"chat_id": chat_id, "text": clip(text, TELEGRAM_MAX)}) is not None

    def get_me(self) -> dict[str, Any] | None:
        return self._call("getMe")

    def set_webhook(self, url: str, secret: str) -> bool:
        payload = {"url": url, "secret_token": secret, "allowed_updates": ["message"]}
        return self._call("setWebhook", payload) is not None

    def delete_webhook(self) -> bool:
        return self._call("deleteWebhook", {"drop_pending_updates": False}) is not None

    def get_updates(self, offset: int | None, timeout: int = 25) -> list[dict[str, Any]] | None:
        """Long polling. None means the call failed (caller should back off), [] means no news."""
        payload: dict[str, Any] = {"timeout": timeout, "allowed_updates": ["message"]}
        if offset is not None:
            payload["offset"] = offset
        return self._call("getUpdates", payload, timeout=timeout + 10)
