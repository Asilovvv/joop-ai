"""Screens name the model provider the server actually uses (a Gemini server is not «Anthropic»)."""

import dataclasses

import pytest

from joop import health
from joop.runtime import Runtime

GEMINI = "https://generativelanguage.googleapis.com/v1beta/openai"


@pytest.fixture(autouse=True)
def _back_to_default():
    yield
    health.use_provider("Anthropic API")


@pytest.mark.parametrize("provider,base,processor,api", [
    ("anthropic", "", "Anthropic (модель Claude, США)", "Anthropic API"),
    ("openai", GEMINI, "Google (модель Gemini, США)", "Gemini API"),
    ("openai", "https://api.openai.com/v1", "OpenAI (США)", "OpenAI API"),
    ("openai", "https://api.groq.com/openai/v1", "Поставщик модели ИИ (api.groq.com)", "API модели"),
])
def test_the_provider_in_use_is_named(settings, provider, base, processor, api):
    s = dataclasses.replace(settings, llm_provider=provider, llm_base_url=base)
    assert s.model_processor == processor and s.model_api_name == api


def test_privacy_page_names_the_provider_in_use(settings, rt, engine):
    from fastapi.testclient import TestClient

    from joop.web.app import create_app

    with TestClient(create_app(settings, rt, init=False)) as c:
        page = c.get("/privacy").text
    assert "Anthropic (модель Claude, США) — текст переписки передаётся для составления ответа, на серверы за пределами" in page
    gemini = dataclasses.replace(settings, llm_provider="openai", llm_base_url=GEMINI, llm_api_key="k")
    with TestClient(create_app(gemini, rt, init=False)) as c:
        page = c.get("/privacy").text
    assert "Google (модель Gemini, США) — текст переписки" in page and "Anthropic" not in page


def test_founder_alerts_name_gemini_on_a_gemini_server(settings):
    Runtime(dataclasses.replace(settings, llm_provider="openai", llm_base_url=GEMINI, llm_api_key="k"))
    exc = RuntimeError("Error code: 401 - invalid api key")
    assert health.reason_of(exc) == "ключ Gemini API неверный или не задан"
    assert "Plans & Billing" not in health.reason_of(RuntimeError("billing: quota"))
    assert health.check_hint() == "проверьте баланс и ключ Gemini API"
