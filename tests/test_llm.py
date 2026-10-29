import json
from types import SimpleNamespace

import pytest

from joop.agent.llm import AnthropicLLM, LLMError, parse_reply


def test_parse_reply_variants():
    plain = parse_reply('{"reply": "Здравствуйте", "booking": null, "handoff": null}')
    assert plain.reply == "Здравствуйте" and plain.booking is None and plain.handoff is None

    fenced = parse_reply('Вот ответ:\n```json\n{"reply": "Ок", "booking": {"slot_id": "12", "name": " Айбек ", "phone": "0555123456", "service": "чистка"}, "handoff": ""}\n```')
    assert fenced.booking == {"slot_id": 12, "name": "Айбек", "phone": "0555123456", "service": "чистка", "preferred_time": "", "party_size": 0}
    assert fenced.handoff is None

    embedded = parse_reply('Ответ: {"reply": "Передам администратору", "booking": null, "handoff": "перезвонить"} конец')
    assert embedded.handoff == "перезвонить"

    with pytest.raises(LLMError):
        parse_reply("не json")
    with pytest.raises(LLMError):
        parse_reply('{"reply": "", "booking": null, "handoff": null}')


class _ApiError(Exception):
    def __init__(self, status_code):
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


class _FakeMessages:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        item = self.outcomes.pop(0)
        if isinstance(item, Exception):
            raise item
        text = item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=text)],
            usage=SimpleNamespace(input_tokens=100, output_tokens=10),
            stop_reason="end_turn",
        )


def _client(outcomes):
    messages = _FakeMessages(outcomes)
    return SimpleNamespace(messages=messages), messages


def test_anthropic_request_shape():
    client, messages = _client([{"reply": "Привет", "booking": None, "handoff": None}])
    llm = AnthropicLLM(api_key="x", model="claude-haiku-5-5", thinking="disabled", client=client)
    result = llm.respond("system", [{"role": "user", "content": "привет"}])
    assert result.reply == "Привет"
    call = messages.calls[0]
    assert call["model"] == "claude-haiku-5-5"
    assert call["thinking"] == {"type": "disabled"}
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert call["system"] == "system"


def test_anthropic_degrades_on_bad_request():
    client, messages = _client([_ApiError(400), _ApiError(400), {"reply": "Ок", "booking": None, "handoff": None}])
    llm = AnthropicLLM(api_key="x", model="m", thinking="disabled", effort="low", client=client)
    assert llm.respond("s", [{"role": "user", "content": "x"}]).reply == "Ок"
    assert "format" in messages.calls[0]["output_config"]
    assert "output_config" in messages.calls[1] and "format" not in messages.calls[1]["output_config"]
    assert "thinking" not in messages.calls[2] and "output_config" not in messages.calls[2]


def test_anthropic_other_errors_raise():
    client, _ = _client([_ApiError(529)])
    llm = AnthropicLLM(api_key="x", model="m", client=client)
    with pytest.raises(LLMError):
        llm.respond("s", [{"role": "user", "content": "x"}])


def test_token_ceiling_leaves_room_for_reply_when_thinking():
    client, messages = _client([{"reply": "a", "booking": None, "handoff": None}] * 3)
    AnthropicLLM(api_key="x", model="m", thinking="disabled", client=client).respond("s", [{"role": "user", "content": "x"}])
    AnthropicLLM(api_key="x", model="m", thinking="adaptive", client=client).respond("s", [{"role": "user", "content": "x"}])
    AnthropicLLM(api_key="x", model="m", thinking="", client=client).respond("s", [{"role": "user", "content": "x"}])
    assert [c["max_tokens"] for c in messages.calls] == [800, 8000, 8000]


def test_usage_and_kyrgyz_rewrite():
    client, messages = _client([{"reply": "Цена 500 сом", "booking": None, "handoff": None}, "Баасы 500 сом."])
    llm = AnthropicLLM(api_key="x", model="claude-haiku-5-5", client=client)
    result = llm.respond("s", [{"role": "user", "content": "канча турат"}])
    assert result.usage["input_tokens"] == 100 and result.usage["output_tokens"] == 10
    assert llm.rewrite_in_kyrgyz("Цена 500 сом", result.usage) == "Баасы 500 сом."
    assert result.usage["input_tokens"] == 200
    second = messages.calls[1]
    assert "output_config" not in second and "tools" not in second
    assert second["messages"] == [{"role": "user", "content": "Цена 500 сом"}]
