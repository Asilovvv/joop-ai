"""«Сводка» says whether customers get the AI's answers right now, and names what stops them.

Found on 28 November while checking the screens for the project's show: the first chip of the dashboard said «ИИ
отвечает» whenever the owner's switch was on. It said so after the trial had ended and the AI had stopped (beside
the banner that said it had), and while the model was failing for every business and customers were getting
«Извините, сейчас не получается ответить».
"""

import re
from datetime import timedelta

import pytest
from sqlmodel import select

from joop import db, health, timeutil
from joop.agent.llm import AgentReply, LLMError
from joop.models import Business, Subscription

from .conftest import NOW_UTC
from .test_saas import app_client, csrf_of, saas_settings, signup  # noqa: F401  (the fixtures of the app's client)


@pytest.fixture(autouse=True)
def model_health_starts_clean():
    """What the server remembers of the model's failures and answers lives in memory: no test inherits another's."""
    health.reset()
    yield
    health.reset()


def chip(client) -> tuple[str, str]:
    """(class, words) of the dashboard's first chip."""
    page = client.get("/panel").text
    found = re.search(r'<div class="chips">\s*<span class="chip ([^"]*)">([^<]+)</span>', page)
    assert found, "the dashboard has no chips"
    return found.group(1).strip(), found.group(2).strip()


def ask(client, text="Сколько стоит чистка?") -> None:
    token = csrf_of(client.get("/panel/try").text)
    client.post("/panel/try", data={"text": text, "csrf": token})


def test_a_new_business_is_answered(app_client):
    signup(app_client)
    assert chip(app_client) == ("ok", "ИИ отвечает")
    assert 'id="ai-down"' not in app_client.get("/panel").text


def test_the_owners_switch_is_named(app_client):
    signup(app_client)
    with db.new_session() as s:
        b = s.exec(select(Business)).one()
        b.bot_enabled = False
        s.add(b)
        s.commit()
    assert chip(app_client) == ("warn", "ИИ выключен")


def test_a_stopped_subscription_is_not_called_answering(app_client):
    signup(app_client)
    with db.new_session() as s:
        sub = s.exec(select(Subscription)).one()
        sub.trial_ends_at = NOW_UTC - timedelta(days=10)  # the trial and its days of grace are over
        s.add(sub)
        s.commit()
    assert chip(app_client) == ("warn", "ИИ остановлен")
    page = app_client.get("/panel").text
    assert "ИИ отвечает" not in page  # nothing on the page says the opposite of its banner


def test_a_model_that_keeps_failing_is_not_called_answering(app_client, llm, monkeypatch):
    signup(app_client)
    llm.replies += [LLMError("Your credit balance is too low")] * health.ALERT_AFTER
    for n in range(health.ALERT_AFTER - 1):
        ask(app_client, f"Вопрос {n}")
        assert chip(app_client) == ("ok", "ИИ отвечает")  # one failure, or two, is not an outage yet
    ask(app_client, "Ещё вопрос")
    assert chip(app_client) == ("warn", "ИИ сейчас не отвечает")
    page = app_client.get("/panel").text
    assert 'id="ai-down"' in page and "приходят вам как заявки" in page
    assert "credit balance" not in page  # the provider's words are the founder's, not a business's

    monkeypatch.setattr(timeutil, "clock", lambda: NOW_UTC + timedelta(minutes=5))
    llm.replies.append(AgentReply("Чистка стоит 2500 сом."))
    ask(app_client)  # the model answers again
    assert chip(app_client) == ("ok", "ИИ отвечает")
    assert 'id="ai-down"' not in app_client.get("/panel").text


def test_old_failures_do_not_last(app_client, llm, monkeypatch):
    signup(app_client)
    llm.replies += [LLMError("down")] * health.ALERT_AFTER
    for n in range(health.ALERT_AFTER):
        ask(app_client, f"Вопрос {n}")
    assert chip(app_client)[1] == "ИИ сейчас не отвечает"
    monkeypatch.setattr(timeutil, "clock", lambda: NOW_UTC + health.WINDOW + timedelta(minutes=1))
    assert chip(app_client) == ("ok", "ИИ отвечает")  # nobody wrote for half an hour: nothing says the model is still down
