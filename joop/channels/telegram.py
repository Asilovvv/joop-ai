"""Telegram Bot API: parsing updates and calling the API."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from .base import MAX_MEDIA_BYTES, TELEGRAM_MAX, IncomingMessage, clip

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


BUSINESS_PREFIX = "bc:"  # chat_id of a chat in the owner's personal account: bc:<business_connection_id>:<chat id>
ALLOWED_UPDATES = ["message", "business_message"]


def business_chat_id(connection_id: str, chat_id: str) -> str:
    return f"{BUSINESS_PREFIX}{connection_id}:{chat_id}"


def split_chat_id(chat_id: str) -> tuple[str, str]:
    """(business_connection_id or "", Telegram chat id). Replies to a personal-account chat go through the connection."""
    if chat_id.startswith(BUSINESS_PREFIX):
        connection, _, chat = chat_id[len(BUSINESS_PREFIX):].rpartition(":")
        if connection and chat:
            return connection, chat
    return "", chat_id


def _sender_name(sender: dict[str, Any]) -> str:
    return " ".join(x for x in (sender.get("first_name"), sender.get("last_name")) if x).strip()


def _body(msg: dict[str, Any], chat_id: str, name: str, external_id: str) -> IncomingMessage | None:
    """Text, a shared phone number or media of a private message."""
    text = (msg.get("text") or "").strip()
    if text:
        return IncomingMessage("telegram", chat_id, "text", text, name, external_id)
    contact = msg.get("contact")
    if isinstance(contact, dict) and contact.get("phone_number"):
        return IncomingMessage("telegram", chat_id, "text", f"Мой телефон: {contact['phone_number']}", name, external_id)
    for key, label in MEDIA_LABELS.items():
        if key in msg:
            caption = (msg.get("caption") or "").strip()
            ref = str((msg.get(key) or {}).get("file_id") or "") if key in {"voice", "audio"} and isinstance(msg.get(key), dict) else ""
            return IncomingMessage("telegram", chat_id, "media", caption, name, external_id, label, ref)
    return None


def _parse_business(msg: dict[str, Any]) -> IncomingMessage | None:
    """A message in the owner's personal Telegram, which the bot answers through Telegram Business.

    Both sides of the chat arrive here. The chat is the customer, so a sender other than the chat is the owner
    typing by hand (an echo: the AI pauses); what the bot itself sent carries sender_business_bot and is dropped.
    """
    chat = msg.get("chat") or {}
    sender = msg.get("from") or {}
    connection = str(msg.get("business_connection_id") or "")
    if not connection or chat.get("id") is None or chat.get("type") != "private" or msg.get("sender_business_bot"):
        return None
    chat_id = business_chat_id(connection, str(chat["id"]))
    external_id = f"tg:{chat_id}:{msg.get('message_id', '')}"
    if str(sender.get("id", "")) != str(chat["id"]):
        body = _body(msg, chat_id, "", external_id)
        text = body.text if body and body.kind == "text" else ""
        return IncomingMessage("telegram", chat_id, "echo", text, "", external_id)
    if sender.get("is_bot"):
        return None
    return _body(msg, chat_id, _sender_name(sender), external_id)  # a «/start» here is plain text, not a bot command


def parse_update(update: dict[str, Any]) -> IncomingMessage | None:
    """Turn a Telegram update into an IncomingMessage. Groups: only commands (e.g. /admin) count."""
    business = update.get("business_message")
    if isinstance(business, dict):
        return _parse_business(business)
    msg = update.get("message")
    if not isinstance(msg, dict):
        return None
    chat = msg.get("chat") or {}
    sender = msg.get("from") or {}
    if chat.get("id") is None or sender.get("is_bot"):
        return None
    chat_id = str(chat["id"])
    name = _sender_name(sender)
    external_id = f"tg:{chat_id}:{msg.get('message_id', update.get('update_id', ''))}"
    text = (msg.get("text") or "").strip()
    private = chat.get("type") == "private"

    if text.startswith("/"):
        return IncomingMessage("telegram", chat_id, "command", text, name, external_id)
    if not private:
        return None
    return _body(msg, chat_id, name, external_id)


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
        connection, chat = split_chat_id(chat_id)
        payload: dict[str, Any] = {"chat_id": chat, "text": clip(text, TELEGRAM_MAX)}
        if connection:  # sent as the owner, from their personal account
            payload["business_connection_id"] = connection
        return self._call("sendMessage", payload) is not None

    def download(self, file_id: str) -> bytes | None:
        """A file the customer sent (a voice message), at most MAX_MEDIA_BYTES."""
        info = self._call("getFile", {"file_id": file_id})
        path = (info or {}).get("file_path")
        if not path or int((info or {}).get("file_size") or 0) > MAX_MEDIA_BYTES:
            return None
        try:
            response = self.http.get(self._base.replace("/bot", "/file/bot", 1) + "/" + path, timeout=30.0)
        except httpx.HTTPError as exc:
            log.warning("Telegram file download failed: %s", type(exc).__name__)  # the URL holds the token
            return None
        if response.status_code >= 400 or len(response.content) > MAX_MEDIA_BYTES:
            return None
        return response.content

    def get_me(self) -> dict[str, Any] | None:
        return self._call("getMe")

    def set_webhook(self, url: str, secret: str) -> bool:
        payload = {"url": url, "secret_token": secret, "allowed_updates": ALLOWED_UPDATES}
        return self._call("setWebhook", payload) is not None

    def delete_webhook(self) -> bool:
        return self._call("deleteWebhook", {"drop_pending_updates": False}) is not None

    def get_updates(self, offset: int | None, timeout: int = 25) -> list[dict[str, Any]] | None:
        """Long polling. None means the call failed (caller should back off), [] means no news."""
        payload: dict[str, Any] = {"timeout": timeout, "allowed_updates": ALLOWED_UPDATES}
        if offset is not None:
            payload["offset"] = offset
        return self._call("getUpdates", payload, timeout=timeout + 10)
