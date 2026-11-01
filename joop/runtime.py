"""Shared runtime objects: settings, HTTP client, language model and channel clients.

Tests replace the factory methods with fakes that record what would be sent.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx

from .agent.llm import AnthropicLLM, LLMClient, LLMError
from .channels.meta import InstagramClient, WhatsAppClient
from .channels.telegram import TelegramClient
from .config import Settings
from .models import Business

if TYPE_CHECKING:
    from .altegio import AltegioClient


class Runtime:
    def __init__(self, settings: Settings, http: httpx.Client | None = None, llm: LLMClient | None = None) -> None:
        self.settings = settings
        self.http = http or httpx.Client(timeout=20.0)
        self._llm = llm

    def get_llm(self) -> LLMClient:
        if self._llm is None:
            if not self.settings.anthropic_api_key:
                raise LLMError("ANTHROPIC_API_KEY is not set")
            self._llm = AnthropicLLM(
                api_key=self.settings.anthropic_api_key,
                model=self.settings.model,
                thinking=self.settings.thinking,
                effort=self.settings.effort,
            )
        return self._llm

    def altegio(self, business: Business) -> "AltegioClient | None":
        """Client for the salon's Altegio location: its own partner token if it set one, else Joop's."""
        from .altegio import AltegioClient

        token = business.altegio_token or self.settings.altegio_partner_token
        if not business.altegio_location_id or not token:
            return None
        return AltegioClient(self.http, token, self.settings.altegio_api_base)

    def transcriber(self):
        """Speech-to-text for voice messages, or None when it is not set up (joop/voice.py)."""
        from .voice import make_transcriber

        return make_transcriber(self.settings, self.http)

    def telegram(self, business: Business) -> TelegramClient | None:
        if not business.telegram_bot_token:
            return None
        return TelegramClient(self.http, self.settings.telegram_api_base, business.telegram_bot_token)

    def whatsapp(self, business: Business) -> WhatsAppClient | None:
        if not (business.wa_phone_number_id and business.wa_access_token):
            return None
        return WhatsAppClient(
            self.http,
            self.settings.whatsapp_api_base,
            self.settings.graph_api_version,
            business.wa_phone_number_id,
            business.wa_access_token,
        )

    def instagram(self, business: Business) -> InstagramClient | None:
        if not (business.ig_account_id and business.ig_access_token):
            return None
        return InstagramClient(
            self.http,
            self.settings.instagram_api_base,
            self.settings.graph_api_version,
            business.ig_account_id,
            business.ig_access_token,
        )

    def channel_client(self, business: Business, channel: str):
        factory = {"telegram": self.telegram, "whatsapp": self.whatsapp, "instagram": self.instagram}.get(channel)
        return factory(business) if factory else None
