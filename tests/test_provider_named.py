"""Screens name the model provider the server actually uses (a Gemini server is not «Anthropic»)."""

import dataclasses

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from joop import db, health
from joop.models import Prospect, StudioRequest
from joop.runtime import Runtime
from joop.web.app import create_app

from .conftest import FakeRuntime
from .test_saas import csrf_of, owner_login, saas_settings  # noqa: F401  (the founder's password)

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


@pytest.fixture
def gemini_console(saas_settings, llm, engine):  # noqa: F811
    """The founder's console of a server that runs on Gemini; the model behind it writes nothing."""
    s = dataclasses.replace(saas_settings, llm_provider="openai", llm_base_url=GEMINI, llm_api_key="k")
    runtime = FakeRuntime(s, llm)
    with TestClient(create_app(s, runtime, init=False)) as c:
        yield c, owner_login(c), runtime


def prospect(client, token) -> int:
    client.post("/owner/prospects", data={"name": "Салон «Айгерим»", "niche": "beauty", "csrf": token})
    with db.new_session() as s:
        return s.exec(select(Prospect.id)).one()


def test_a_failed_sales_draft_points_at_the_provider_in_use(gemini_console):
    client, token, _runtime = gemini_console
    page = client.post(f"/owner/prospects/{prospect(client, token)}", data={"action": "draft", "csrf": token}).text
    assert "ИИ не смог написать черновик. Проверьте баланс и ключ Gemini API." in page and "ANTHROPIC" not in page


def test_a_failed_pitch_demo_points_at_the_provider_in_use(gemini_console):
    client, token, runtime = gemini_console
    runtime._llm, runtime.settings = None, dataclasses.replace(runtime.settings, llm_api_key="")  # the key was lost
    page = client.post(f"/owner/prospects/{prospect(client, token)}",
                       data={"action": "pitch", "source": "Маникюр — 1 200 сом", "csrf": token}).text
    assert "ИИ сейчас недоступен. Проверьте баланс и ключ Gemini API." in page and "ANTHROPIC" not in page


def test_a_failed_site_draft_points_at_the_provider_in_use(gemini_console):
    client, token, _runtime = gemini_console
    form = csrf_of(client.get("/studio").text)
    client.post("/studio", data={"kind": "site", "business_name": "Дент Джал", "contact_name": "Айгуль", "phone": "0555 123 456",
                                 "niche": "dental", "description": "Чистка 2500 сом, лечение кариеса от 2000. Адрес Джал, 9-19.",
                                 "csrf": form})
    with db.new_session() as s:
        rid = s.exec(select(StudioRequest.id)).one()
    page = client.post(f"/owner/studio/{rid}", data={"action": "draft", "csrf": token}).text
    assert "ИИ не смог сделать черновик. Проверьте баланс и ключ Gemini API или дополните описание." in page
    assert "ANTHROPIC" not in page

