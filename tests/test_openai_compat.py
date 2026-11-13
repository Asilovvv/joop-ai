"""A second model provider (joop/agent/openai_compat.py): any OpenAI-compatible API, the code still decides."""

import dataclasses
import json

import httpx
import pytest

from joop import ops
from joop.agent.llm import LLMError
from joop.agent.openai_compat import OpenAICompatLLM
from joop.config import settings_from_env
from joop.runtime import Runtime


def service(answers, seen):
    """A fake Chat Completions endpoint: records each request body, answers from the list (status, body)."""
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append({"url": str(request.url), "auth": request.headers.get("authorization"), "body": json.loads(request.content)})
        status, body = answers.pop(0)
        return httpx.Response(status, json=body) if isinstance(body, dict) else httpx.Response(status, text=body)
    return httpx.Client(transport=httpx.MockTransport(handler))


def completion(content, prompt=120, completion_tokens=30):
    return {"choices": [{"message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": prompt, "completion_tokens": completion_tokens}}


def test_reply_and_action_come_back_as_the_same_json(engine):
    seen = []
    llm = OpenAICompatLLM("https://api.example.test/v1/", "k-123", "some-model", http=service(
        [(200, completion('{"reply": "Записала на 10:00.", "booking": {"slot_id": 7, "name": "Айжан", "phone": "0700112233", '
                          '"service": "чистка", "preferred_time": "", "party_size": 0}, "handoff": null}'))], seen))
    reply = llm.respond("system text", [{"role": "user", "content": "Запишите"}], {"type": "object"})
    assert reply.reply == "Записала на 10:00." and reply.booking["slot_id"] == 7  # the engine still checks the slot
    assert reply.usage["input_tokens"] == 120 and reply.usage["output_tokens"] == 30
    sent = seen[0]
    assert sent["url"] == "https://api.example.test/v1/chat/completions" and sent["auth"] == "Bearer k-123"
    assert sent["body"]["messages"][0] == {"role": "system", "content": "system text"}
    assert sent["body"]["response_format"]["json_schema"]["schema"] == {"type": "object"}


def test_a_service_without_json_schema_falls_back_to_plain_json(engine):
    seen = []
    llm = OpenAICompatLLM("https://api.example.test/v1", "k", "m", http=service([
        (400, "response_format json_schema is not supported"), (400, "json_object not supported"),
        (200, completion('Вот ответ: {"reply": "Здравствуйте!"}'))], seen))
    assert llm.respond("s", [{"role": "user", "content": "Салам"}]).reply == "Здравствуйте!"
    assert [b["body"].get("response_format", {}).get("type") for b in seen] == ["json_schema", "json_object", None]
    assert llm.format == ""  # remembered for the next message


def test_other_errors_are_model_errors_not_retries(engine):
    seen = []
    llm = OpenAICompatLLM("https://api.example.test/v1", "k", "m", http=service([(429, "quota exceeded for free tier")], seen))
    with pytest.raises(LLMError, match="429"):
        llm.respond("s", [{"role": "user", "content": "x"}])
    assert len(seen) == 1
    llm = OpenAICompatLLM("https://api.example.test/v1", "k", "m", http=service([(500, "boom")], []))
    assert llm.rewrite_in_kyrgyz("Здравствуйте", {"input_tokens": 0, "output_tokens": 0}) is None  # the draft is sent


def test_settings_choose_the_provider(monkeypatch, settings, tmp_path):
    for key in ("LLM_PROVIDER", "LLM_BASE_URL", "LLM_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "OpenAI")
    monkeypatch.setenv("LLM_BASE_URL", "https://generativelanguage.example.test/v1beta/openai/")
    monkeypatch.setenv("LLM_API_KEY", "free-key")
    s = settings_from_env()
    assert s.llm_provider == "openai" and s.llm_base_url.endswith("/openai") and s.model_key == "free-key"
    assert isinstance(Runtime(s).get_llm(), OpenAICompatLLM)
    no_url = dataclasses.replace(s, llm_base_url="")
    assert no_url.model_key == "" and no_url.model_key_name == "LLM_API_KEY и LLM_BASE_URL"
    with pytest.raises(LLMError, match="LLM_API_KEY"):
        Runtime(no_url).get_llm()
    assert dataclasses.replace(s, llm_provider="anthropic", anthropic_api_key="").model_key == ""


def test_launch_check_warns_about_real_customers_on_a_second_provider(settings, engine, tmp_path):
    s = dataclasses.replace(settings, llm_provider="openai", llm_base_url="https://api.example.test/v1", llm_api_key="k",
                            public_base_url="https://joop.kg", secure_cookies=True, owner_password="long-owner-password",
                            database_url=f"sqlite:///{tmp_path / 'test.db'}")
    checks = {c.name.split(" (")[0]: c for c in ops.launch_checks(s, {"SESSION_SECRET": "a" * 64, "DOMAIN": "joop.kg"}, live=lambda: None)}
    assert checks["Ключ модели"].ok and checks["Модель отвечает"].ok
    warn = checks["Модель для настоящих клиентов"]
    assert not warn.ok and not warn.required and "бесплатные тарифы могут использовать переписку" in warn.detail
