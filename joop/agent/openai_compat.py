"""A second model provider: any service with an OpenAI-compatible Chat Completions API.

Google Gemini (its OpenAI-compatible endpoint), Groq, OpenRouter and others speak this API, and some of them
have a free tier. It is meant for development and the scripted evaluation on fictional businesses while the
Anthropic balance is empty: free tiers may use what is sent to improve the provider's products, so real
customers' messages should go only to a paid provider whose terms the owner has read (docs/model-providers.md).

The rest of Joop does not change: the model still only proposes a reply and an action as JSON, and the code
checks every booking and order before anything happens. Settings: LLM_PROVIDER=openai, LLM_BASE_URL,
LLM_API_KEY, JOOP_MODEL.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

import httpx

from ..pricing import add_usage, empty_usage
from .llm import RESPONSE_SCHEMA, THINKING_MAX_TOKENS, TRANSLATE_TO_KYRGYZ, UNCONFIRM, AgentReply, LLMError, parse_reply

log = logging.getLogger(__name__)

# Output formats, best first: a JSON schema, then «any JSON object», then plain text that parse_reply reads.
FORMATS = ("json_schema", "json_object", "")


def _usage(data: dict) -> SimpleNamespace:
    u = data.get("usage") or {}
    return SimpleNamespace(input_tokens=u.get("prompt_tokens", 0), output_tokens=u.get("completion_tokens", 0))


def _text(data: dict) -> str:
    choices = data.get("choices") or []
    if not choices:
        return ""
    content = (choices[0].get("message") or {}).get("content") or ""
    if isinstance(content, list):  # some services return content parts
        content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return str(content)


class OpenAICompatLLM:
    def __init__(self, base_url: str, api_key: str, model: str, max_tokens: int = 800, http: httpx.Client | None = None) -> None:
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.api_key = api_key
        self.model = model
        self.max_tokens = max_tokens
        self.http = http or httpx.Client(timeout=40.0)
        self.format = FORMATS[0]

    def _post(self, body: dict) -> dict:
        response = self.http.post(self.url, json=body, headers={"Authorization": f"Bearer {self.api_key}"})
        if response.status_code >= 400:
            # The service's error text carries no key; keep it short for logs and the owner's checks.
            raise LLMError(f"model API returned {response.status_code}: {response.text[:300]}")
        return response.json()

    def _body(self, system: str, messages: list[dict], schema: dict | None, max_tokens: int) -> dict:
        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system}] + list(messages),
        }
        if self.format == "json_schema":
            body["response_format"] = {"type": "json_schema", "json_schema": {"name": "agent_reply", "schema": schema or RESPONSE_SCHEMA}}
        elif self.format == "json_object":
            body["response_format"] = {"type": "json_object"}
        return body

    def respond(self, system: str, messages: list[dict], schema: dict | None = None) -> AgentReply:
        usage = empty_usage()
        while True:
            try:
                data = self._post(self._body(system, messages, schema, self.max_tokens))
            except LLMError as exc:
                if " 400:" in str(exc) and self.format:  # the service does not take this output format
                    self.format = FORMATS[FORMATS.index(self.format) + 1]
                    log.warning("Model API rejected the output format; retrying with %r", self.format or "plain text")
                    continue
                raise
            except httpx.HTTPError as exc:
                raise LLMError(f"model API call failed: {type(exc).__name__}") from exc
            add_usage(usage, _usage(data))
            result = parse_reply(_text(data))
            result.usage = usage
            return result

    def rewrite_in_kyrgyz(self, text: str, usage: dict) -> str | None:
        return self._rewrite(TRANSLATE_TO_KYRGYZ, text, usage)

    def remove_false_confirmation(self, text: str, usage: dict) -> str | None:
        return self._rewrite(UNCONFIRM, text, usage)

    def write(self, instruction: str, text: str, usage: dict) -> str | None:
        return self._rewrite(instruction, text, usage)

    def _rewrite(self, instruction: str, text: str, usage: dict) -> str | None:
        body = {"model": self.model, "max_tokens": THINKING_MAX_TOKENS,
                "messages": [{"role": "system", "content": instruction}, {"role": "user", "content": text}]}
        try:
            data = self._post(body)
        except (LLMError, httpx.HTTPError):
            log.warning("Reply rewrite failed; sending the draft")
            return None
        add_usage(usage, _usage(data))
        return _text(data).strip() or None
