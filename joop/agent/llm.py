"""Language model client. The model answers with a JSON object: reply, booking, handoff."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..pricing import add_usage, empty_usage

log = logging.getLogger(__name__)

def _nullable(schema: dict[str, Any]) -> dict[str, Any]:
    return {"anyOf": [{"type": "null"}, schema]}


def _obj(props: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


_STR = {"type": "string"}
BOOKING_SCHEMA = _obj(
    {
        "slot_id": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
        "name": _STR,
        "phone": _STR,
        "service": _STR,
        "preferred_time": _STR,
        "party_size": {"type": "integer"},
    }
)
ORDER_SCHEMA = _obj(
    {
        "lines": {"type": "array", "items": _obj({"item_id": {"type": "integer"}, "quantity": {"type": "integer"}, "note": _STR})},
        "mode": _STR,
        "address": _STR,
        "time": _STR,
        "name": _STR,
        "phone": _STR,
        "comment": _STR,
    }
)
LEAD_SCHEMA = _obj({"name": _STR, "phone": _STR, "details": _STR})


def response_schema(outcomes: frozenset[str] | set[str] | None = None) -> dict[str, Any]:
    """JSON schema of the model's answer for the outcomes a niche enables."""
    outcomes = outcomes if outcomes is not None else {"booking", "request", "handoff"}
    props: dict[str, Any] = {"reply": _STR}
    if "booking" in outcomes or "request" in outcomes:
        props["booking"] = _nullable(BOOKING_SCHEMA)
    if "order" in outcomes:
        props["order"] = _nullable(ORDER_SCHEMA)
    if "lead" in outcomes:
        props["lead"] = _nullable(LEAD_SCHEMA)
    props["handoff"] = {"anyOf": [{"type": "null"}, _STR]}
    return _obj(props)


RESPONSE_SCHEMA: dict[str, Any] = response_schema()


THINKING_MAX_TOKENS = 8000


class LLMError(Exception):
    """The model could not produce a usable answer."""


TRANSLATE_TO_KYRGYZ = """You rewrite one customer-service message into Kyrgyz.
The customer wrote in Kyrgyz, but the draft you receive is in Russian. Translate the
whole draft into natural, polite Kyrgyz in Cyrillic script. Keep every number, price,
currency, time, date, phone number, name and address exactly as in the draft. Use only
Kyrgyz Cyrillic letters: no Latin letters and no Kazakh letters such as і, ә, ғ, қ.
Plain text, no markdown. Output only the translated message, nothing else."""


@dataclass
class AgentReply:
    reply: str
    booking: dict | None = None
    handoff: str | None = None
    usage: dict = field(default_factory=empty_usage)
    order: dict | None = None
    lead: dict | None = None


class LLMClient(Protocol):
    model: str

    def respond(self, system: str, messages: list[dict], schema: dict | None = None) -> AgentReply: ...

    def rewrite_in_kyrgyz(self, text: str, usage: dict) -> str | None:
        """Translate a reply into Kyrgyz; add the call's tokens to `usage`. None if it failed."""
        ...

    def remove_false_confirmation(self, text: str, usage: dict) -> str | None:
        """Rewrite a reply that claims a booking or order was made when it was not."""
        ...


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
            "preferred_time": str(booking.get("preferred_time") or "").strip(),
            "party_size": _int(booking.get("party_size")),
        }
    else:
        booking = None

    order = data.get("order")
    if isinstance(order, dict):
        lines = []
        for line in order.get("lines") or []:
            if isinstance(line, dict):
                lines.append({"item_id": _int(line.get("item_id")), "quantity": _int(line.get("quantity")), "note": _s(line.get("note"))})
        order = {"lines": lines, **{k: _s(order.get(k)) for k in ("mode", "address", "time", "name", "phone", "comment")}}
    else:
        order = None

    lead = data.get("lead")
    lead = {k: _s(lead.get(k)) for k in ("name", "phone", "details")} if isinstance(lead, dict) else None

    handoff = data.get("handoff")
    handoff = str(handoff).strip() if isinstance(handoff, (str, int, float)) and str(handoff).strip() else None

    if not reply:
        raise LLMError("model returned an empty reply")
    return AgentReply(reply=reply, booking=booking, handoff=handoff, order=order, lead=lead)


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _s(value: Any) -> str:
    return str(value or "").strip()


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

    def _request(self, system: str, messages: list[dict], schema: dict | None = None) -> dict[str, Any]:
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
            output_config["format"] = {"type": "json_schema", "schema": schema or RESPONSE_SCHEMA}
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

    def respond(self, system: str, messages: list[dict], schema: dict | None = None) -> AgentReply:
        usage = empty_usage()
        while True:
            try:
                response = self.client.messages.create(**self._request(system, messages, schema))
            except Exception as exc:  # the SDK raises typed errors; status 400 means a bad parameter
                if getattr(exc, "status_code", None) == 400 and self._degrade():
                    log.warning("Claude API rejected a request option (%s); retrying without it", type(exc).__name__)
                    continue
                raise LLMError(f"Claude API call failed: {type(exc).__name__}") from exc
            add_usage(usage, getattr(response, "usage", None))
            if getattr(response, "stop_reason", "") == "max_tokens":
                log.warning("Reply hit the max_tokens ceiling (%s)", self.max_tokens)
            result = parse_reply(_text_of(response))
            result.usage = usage
            return result

    def rewrite_in_kyrgyz(self, text: str, usage: dict) -> str | None:
        """One plain call without tools or JSON: it cannot book or hand off a second time."""
        return self._rewrite(TRANSLATE_TO_KYRGYZ, text, usage)

    def remove_false_confirmation(self, text: str, usage: dict) -> str | None:
        return self._rewrite(UNCONFIRM, text, usage)

    def _rewrite(self, instruction: str, text: str, usage: dict) -> str | None:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": THINKING_MAX_TOKENS,
            "system": instruction,
            "messages": [{"role": "user", "content": text}],
        }
        if self.thinking:
            kwargs["thinking"] = {"type": self.thinking}
        try:
            response = self.client.messages.create(**kwargs)
        except Exception:
            log.warning("Reply rewrite failed; sending the draft")
            return None
        add_usage(usage, getattr(response, "usage", None))
        return _text_of(response).strip() or None


UNCONFIRM = """You edit one message that a business assistant is about to send to a customer.
The message says or implies that a booking, request or order is already accepted, recorded or confirmed,
but it is NOT: the business still needs information or the customer still has to choose.
Rewrite the message so it makes no such claim. Keep every question, option, time, price and name
exactly as they are, keep the same language (Kyrgyz or Russian) and the same polite tone.
Plain text, no markdown. Output only the rewritten message."""


def _text_of(response: Any) -> str:
    return "".join(getattr(b, "text", "") for b in response.content if getattr(b, "type", "") == "text")
