"""Voice messages: download the audio, turn it into text, and let the AI answer it like a typed message.

Off until STT_PROVIDER is set. Without it, or when anything fails (download, recognition, empty result),
a voice message stays what it was before: a request for staff to answer by hand. The provider sits behind
a small interface, so another one (Google, Azure, a self-hosted Whisper model for Kyrgyz) is one class.

ElevenLabs Scribe: POST {base}/v1/speech-to-text, header xi-api-key, multipart "file" + "model_id";
the answer's "text" is the transcript. The language is detected by the service (Kyrgyz and Russian
are both on its list), so nothing is passed.
"""

from __future__ import annotations

import dataclasses
import logging
from typing import TYPE_CHECKING, Protocol

import httpx

from .channels.base import MAX_MEDIA_BYTES, IncomingMessage
from .config import Settings
from .models import Business

if TYPE_CHECKING:
    from .runtime import Runtime

log = logging.getLogger(__name__)

VOICE_LABELS = {"голосовое сообщение", "аудио"}
MAX_TEXT = 2000  # a transcript longer than this is a lecture, not a question: cut it
STORED_PREFIX = "[голосовое] "


class Transcriber(Protocol):
    def transcribe(self, audio: bytes) -> str | None: ...


class ElevenLabsTranscriber:
    def __init__(self, http: httpx.Client, api_key: str, model: str, base_url: str) -> None:
        self.http, self._key, self.model, self._url = http, api_key, model, f"{base_url.rstrip('/')}/v1/speech-to-text"

    def transcribe(self, audio: bytes) -> str | None:
        try:
            response = self.http.post(self._url, headers={"xi-api-key": self._key}, data={"model_id": self.model},
                                      files={"file": ("voice.ogg", audio, "application/octet-stream")}, timeout=60.0)
        except httpx.HTTPError as exc:
            log.warning("Speech-to-text failed: %s", type(exc).__name__)
            return None
        if response.status_code >= 400:
            log.warning("Speech-to-text failed: HTTP %s", response.status_code)
            return None
        try:
            text = str(response.json().get("text") or "")
        except ValueError:
            return None
        return " ".join(text.split())[:MAX_TEXT] or None


def make_transcriber(settings: Settings, http: httpx.Client) -> Transcriber | None:
    if settings.stt_provider == "elevenlabs" and settings.stt_api_key:
        return ElevenLabsTranscriber(http, settings.stt_api_key, settings.stt_model, settings.stt_api_base)
    if settings.stt_provider:
        log.warning("STT_PROVIDER=%s is not supported or has no STT_API_KEY: voice messages go to staff", settings.stt_provider)
    return None


def prepare(rt: "Runtime", business: Business, incoming: IncomingMessage) -> IncomingMessage:
    """A voice message becomes a text message with the transcript; anything else is returned unchanged."""
    if incoming.kind != "media" or incoming.media_label not in VOICE_LABELS or not incoming.media_ref:
        return incoming
    try:
        transcriber = rt.transcriber()
        client = rt.channel_client(business, incoming.channel) if transcriber else None
        audio = client.download(incoming.media_ref) if client is not None and hasattr(client, "download") else None
        if not audio or len(audio) > MAX_MEDIA_BYTES:
            return incoming
        text = transcriber.transcribe(audio)
    except Exception:  # recognition is a bonus: never lose the message because of it
        log.exception("Voice message of %s was not recognised", business.slug)
        return incoming
    if not text:
        return incoming
    caption = (incoming.text or "").strip()
    return dataclasses.replace(incoming, kind="text", text=f"{caption}\n{text}" if caption else text, transcribed=True)
