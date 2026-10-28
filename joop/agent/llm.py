"""Language model client. The model answers with a JSON object: reply, booking, handoff."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Protocol

log = logging.getLogger(__name__)

RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "reply": {"type": "string"},
        "booking": {
            "anyOf": [
                {"type": "null"},
                {
                    "type": "object",
                    "properties": {
                        "slot_id": {"type": "integer"},
                        "name": {"type": "string"},
                        "phone": {"type": "string"},
                        "service": {"type": "string"},
                    },
                    "required": ["slot_id", "name", "phone", "service"],
                    "additionalProperties": False,
                },
            ]
        },
        "handoff": {"anyOf": [{"type": "null"}, {"type": "string"}]},
    },
    "required": ["reply", "booking", "handoff"],
    "additionalProperties": False,
}


THINKING_MAX_TOKENS = 8000


class LLMError(Exception):
    """The model could not produce a usable answer."""


@dataclass
class AgentReply:
    reply: str
    booking: dict | None = None
    handoff: str | None = None


class LLMClient(Protocol):
    def respond(self, system: str, messages: list[dict]) -> AgentReply: ...


def _extract_json(text: str) -> Any:
    text = (text or "").strip()
    if not text:
        raise LLMError("empty model output")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        try:
            return json.loads(fence.group(1))
        except json.JSONDecodeError:
            pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    raise LLMError("model output is not JSON")


def coerce_reply(data: Any) -> AgentReply:
    if not isinstance(data, dict):
        raise LLMError("model output is not a JSON object")
    reply = str(data.get("reply") or "").strip()

    booking = data.get("booking")
    if isinstance(booking, dict):
        try:
            slot_id: int | None = int(booking.get("slot_id"))
        except (TypeError, ValueError):
            slot_id = None
        booking = {
            "slot_id": slot_id,
            "name": str(booking.get("name") or "").strip(),
            "phone": str(booking.get("phone") or "").strip(),
            "service": str(booking.get("service") or "").strip(),
        }
    else:
        booking = None

    handoff = data.get("handoff")
    handoff = str(handoff).strip() if isinstance(handoff, (str, int, float)) and str(handoff).strip() else None

    if not reply:
        raise LLMError("model returned an empty reply")
    return AgentReply(reply=reply, booking=booking, handoff=handoff)


def parse_reply(text: str) -> AgentReply:
    return coerce_reply(_extract_json(text))


class AnthropicLLM:
    """Claude via the Messages API with structured JSON output.

    If the API rejects an optional feature (structured output, thinking or effort settings), the
    client drops it and retries, so a wrong setting degrades quality instead of breaking replies.
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        thinking: str = "disabled",
        effort: str = "",
        max_tokens: int = 800,
        client: Any = None,
    ) -> None:
        if client is None:
            import anthropic

            client = anthropic.Anthropic(api_key=api_key, timeout=40.0, max_retries=2)
        self.client = client
        self.model = model
        self.thinking = thinking if thinking in {"disabled", "adaptive"} else ""
        self.effort = effort if effort in {"low", "medium", "high"} else ""
        self.max_tokens = max_tokens
        self.structured = True

    def _request(self, system: str, messages: list[dict]) -> dict[str, Any]:
        # With thinking on (explicitly, or by model default when the setting is dropped), thinking
        # tokens count against max_tokens and can leave no room for the reply. Only output actually
        # generated is billed, so a high ceiling costs nothing extra.
        max_tokens = self.max_tokens if self.thinking == "disabled" else max(self.max_tokens, THINKING_MAX_TOKENS)
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": messages,
        }
        if self.thinking:
            kwargs["thinking"] = {"type": self.thinking}
        output_config: dict[str, Any] = {}
        if self.effort:
            output_config["effort"] = self.effort
        if self.structured:
            output_config["format"] = {"type": "json_schema", "schema": RESPONSE_SCHEMA}
        if output_config:
            kwargs["output_config"] = output_config
        return kwargs

    def _degrade(self) -> bool:
        if self.structured:
            self.structured = False
            return True
        if self.thinking or self.effort:
            self.thinking = ""
            self.effort = ""
            return True
        return False

    def respond(self, system: str, messages: list[dict]) -> AgentReply:
        while True:
            try:
                response = self.client.messages.create(**self._request(system, messages))
            except Exception as exc:  # the SDK raises typed errors; status 400 means a bad parameter
                if getattr(exc, "status_code", None) == 400 and self._degrade():
                    log.warning("Claude API rejected a request option (%s); retrying without it", type(exc).__name__)
                    continue
                raise LLMError(f"Claude API call failed: {type(exc).__name__}") from exc
            text = "".join(
                getattr(block, "text", "") for block in response.content if getattr(block, "type", "") == "text"
            )
            return parse_reply(text)
