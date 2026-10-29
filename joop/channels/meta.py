"""Meta platform: WhatsApp Cloud API and Instagram API webhooks and send calls."""

from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Any, Iterable

import httpx

from .base import INSTAGRAM_MAX_BYTES, WHATSAPP_MAX, IncomingMessage, clip, clip_bytes

log = logging.getLogger(__name__)

# Since 2026 WhatsApp may hide a user's phone number and send a business-scoped user id (BSUID)
# instead. We keep such chats as "bsuid:<id>" and address replies through the `recipient` field.
BSUID_PREFIX = "bsuid:"

WA_MEDIA_LABELS = {
    "audio": "голосовое сообщение",
    "image": "фото",
    "video": "видео",
    "document": "файл",
    "sticker": "стикер",
    "location": "геолокация",
    "contacts": "контакт",
}
IG_MEDIA_LABELS = {
    "audio": "голосовое сообщение",
    "image": "фото",
    "video": "видео",
    "file": "файл",
    "share": "репост",
    "story_mention": "упоминание в истории",
    "ig_reel": "рилс",
}


def verify_signature(secrets: Iterable[str], raw_body: bytes, header: str) -> bool:
    """Check X-Hub-Signature-256 ('sha256=<hex>') against any of the configured app secrets."""
    if not header or not header.startswith("sha256="):
        return False
    received = header.split("=", 1)[1].strip()
    for secret in secrets:
        if not secret:
            continue
        expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        if hmac.compare_digest(expected, received):
            return True
    return False


def _wa_text(m: dict[str, Any]) -> tuple[str, str, str]:
    """(kind, text, media_label) for one WhatsApp message object."""
    mtype = m.get("type", "")
    if mtype == "text":
        return "text", ((m.get("text") or {}).get("body") or "").strip(), ""
    if mtype == "button":
        return "text", ((m.get("button") or {}).get("text") or "").strip(), ""
    if mtype == "interactive":
        inter = m.get("interactive") or {}
        reply = inter.get("button_reply") or inter.get("list_reply") or {}
        return "text", (reply.get("title") or "").strip(), ""
    if mtype in WA_MEDIA_LABELS:
        caption = ((m.get(mtype) or {}).get("caption") or "") if isinstance(m.get(mtype), dict) else ""
        return "media", caption.strip(), WA_MEDIA_LABELS[mtype]
    return "", "", ""  # reactions, system and unsupported messages are ignored


def _wa_party(m: dict[str, Any], side: str) -> str:
    """Phone number of the customer ("from" or "to"), or their BSUID when the number is hidden."""
    if m.get(side):
        return str(m[side])
    user_id = m.get(f"{side}_user_id")
    return f"{BSUID_PREFIX}{user_id}" if user_id else ""


def parse_whatsapp(payload: dict[str, Any]) -> list[tuple[str, IncomingMessage]]:
    """Return (phone_number_id, message) pairs. Consecutive texts from one sender are merged."""
    out: list[tuple[str, IncomingMessage]] = []
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            field = change.get("field")
            phone_number_id = str((value.get("metadata") or {}).get("phone_number_id") or "")
            if not phone_number_id:
                continue
            if field == "messages":
                names: dict[str, str] = {}
                for contact in value.get("contacts") or []:
                    name = (contact.get("profile") or {}).get("name") or ""
                    for key in (contact.get("wa_id"), contact.get("user_id")):
                        if key:
                            names[str(key)] = name
                for m in value.get("messages") or []:
                    kind, text, label = _wa_text(m)
                    sender = _wa_party(m, "from")
                    if not kind or not sender:
                        continue
                    if kind == "text" and not text:
                        continue
                    previous = out[-1][1] if out else None
                    if (
                        previous is not None
                        and kind == "text"
                        and previous.kind == "text"
                        and previous.channel == "whatsapp"
                        and previous.chat_id == sender
                        and out[-1][0] == phone_number_id
                    ):
                        previous.text += "\n" + text
                        continue
                    out.append(
                        (
                            phone_number_id,
                            IncomingMessage("whatsapp", sender, kind, text, names.get(sender.removeprefix(BSUID_PREFIX), ""), f"wa:{m.get('id', '')}", label),
                        )
                    )
            elif field == "smb_message_echoes":
                # Coexistence: messages the clinic typed in the WhatsApp Business app.
                for m in value.get("message_echoes") or []:
                    customer = _wa_party(m, "to")
                    if not customer:
                        continue
                    _, text, _ = _wa_text(m)
                    out.append((phone_number_id, IncomingMessage("whatsapp", customer, "echo", text, "", f"wa:{m.get('id', '')}")))
    return out


def parse_instagram(payload: dict[str, Any]) -> list[tuple[str, IncomingMessage]]:
    """Return (instagram_account_id, message) pairs for Instagram Direct events."""
    out: list[tuple[str, IncomingMessage]] = []
    for entry in payload.get("entry") or []:
        account_id = str(entry.get("id") or "")
        for event in entry.get("messaging") or []:
            msg = event.get("message")
            if not isinstance(msg, dict) or msg.get("is_deleted") or msg.get("is_unsupported"):
                continue
            sender = str((event.get("sender") or {}).get("id") or "")
            recipient = str((event.get("recipient") or {}).get("id") or "")
            external_id = f"ig:{msg.get('mid', '')}"
            text = (msg.get("text") or "").strip()
            if msg.get("is_echo"):
                if recipient:
                    out.append((account_id or sender, IncomingMessage("instagram", recipient, "echo", text, "", external_id)))
                continue
            if not sender:
                continue
            target = account_id or recipient
            if text:
                out.append((target, IncomingMessage("instagram", sender, "text", text, "", external_id)))
                continue
            attachments = msg.get("attachments") or []
            if attachments:
                kind = (attachments[0] or {}).get("type", "")
                label = IG_MEDIA_LABELS.get(kind, "вложение")
                out.append((target, IncomingMessage("instagram", sender, "media", "", "", external_id, label)))
    return out


def parse_meta_payload(payload: dict[str, Any]) -> list[tuple[str, str, IncomingMessage]]:
    """[(channel, account_id, message)] for a webhook body from either product."""
    kind = payload.get("object")
    if kind == "whatsapp_business_account":
        return [("whatsapp", account, m) for account, m in parse_whatsapp(payload)]
    if kind == "instagram":
        return [("instagram", account, m) for account, m in parse_instagram(payload)]
    return []


def _error_text(response: httpx.Response) -> str:
    try:
        return str((response.json().get("error") or {}).get("message", ""))[:300]
    except ValueError:
        return ""


class _GraphClient:
    def __init__(self, http: httpx.Client, base_url: str, version: str, account_id: str, token: str) -> None:
        self.http = http
        self._base = base_url.rstrip("/")
        self._token = token
        self.url = f"{self._base}/{version}/{account_id}/messages"
        self._headers = {"Authorization": f"Bearer {token}"}

    def _post(self, payload: dict[str, Any], what: str) -> bool:
        try:
            response = self.http.post(self.url, json=payload, headers=self._headers, timeout=20.0)
        except httpx.HTTPError as exc:
            log.warning("%s send failed: %s", what, type(exc).__name__)
            return False
        if response.status_code >= 400:
            log.warning("%s send failed: HTTP %s %s", what, response.status_code, _error_text(response))
            return False
        return True


def _addressee(to: str) -> dict[str, str]:
    if to.startswith(BSUID_PREFIX):
        return {"recipient": to[len(BSUID_PREFIX):]}
    return {"to": to}


class WhatsAppClient(_GraphClient):
    def send_text(self, to: str, text: str) -> bool:
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            **_addressee(to),
            "type": "text",
            "text": {"preview_url": False, "body": clip(text, WHATSAPP_MAX)},
        }
        return self._post(payload, "WhatsApp")

    def send_template(self, to: str, name: str, lang: str, params: list[str]) -> bool:
        """Template with positional variables {{1}}, {{2}}, ... in its body."""
        template: dict[str, Any] = {"name": name, "language": {"code": lang or "ru"}}
        if params:
            template["components"] = [
                {"type": "body", "parameters": [{"type": "text", "text": p} for p in params]}
            ]
        payload = {"messaging_product": "whatsapp", **_addressee(to), "type": "template", "template": template}
        return self._post(payload, "WhatsApp template")


class InstagramClient(_GraphClient):
    def send_text(self, recipient_id: str, text: str) -> bool:
        payload = {"recipient": {"id": recipient_id}, "message": {"text": clip_bytes(text, INSTAGRAM_MAX_BYTES)}}
        return self._post(payload, "Instagram")

    def refresh_token(self) -> str | None:
        """Instagram user tokens live 60 days; a token older than 24 hours can be exchanged for a new one."""
        try:
            response = self.http.get(
                f"{self._base}/refresh_access_token",
                params={"grant_type": "ig_refresh_token", "access_token": self._token},
                timeout=20.0,
            )
        except httpx.HTTPError as exc:
            log.warning("Instagram token refresh failed: %s", type(exc).__name__)
            return None
        if response.status_code >= 400:
            log.warning("Instagram token refresh failed: HTTP %s %s", response.status_code, _error_text(response))
            return None
        try:
            token = response.json().get("access_token")
        except ValueError:
            return None
        return str(token) if token else None
