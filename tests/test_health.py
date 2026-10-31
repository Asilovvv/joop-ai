import dataclasses
from datetime import timedelta

from fastapi.testclient import TestClient

from joop import db, health
from joop.agent.engine import ERROR_REPLY, handle_incoming
from joop.agent.llm import LLMError
from joop.channels.base import IncomingMessage
from joop.models import Business
from joop.scheduler import Scheduler
from joop.web.app import create_app

from .conftest import NOW_UTC, FakeLLM
from .test_web import csrf_of


def credit_error(system, messages):
    try:
        raise RuntimeError("Error code: 400 - Your credit balance is too low to access the Anthropic API.")
    except RuntimeError as exc:
        raise LLMError("Claude API call failed: BadRequestError") from exc


def fail(business_id, n, now=NOW_UTC, tag="a"):
    llm = FakeLLM([credit_error] * n)
    for i in range(n):
        with db.new_session() as s:
            out = handle_incoming(s, s.get(Business, business_id), IncomingMessage("telegram", f"{tag}{i}", "text", "Сколько стоит?", "", f"{tag}-h{i}"),
                                  lambda: llm, now)
            s.commit()
            assert out.reply == ERROR_REPLY


def test_reasons():
    for text, expected in [("Your credit balance is too low", "баланс"), ("invalid x-api-key", "ключ"),
                           ("rate_limit_error", "лимит"), ("Overloaded", "перегружен"), ("Something odd", "RuntimeError")]:
        try:
            try:
                raise RuntimeError(text)
            except RuntimeError as cause:
                raise LLMError("Claude API call failed") from cause
        except LLMError as exc:
            assert expected in health.reason_of(exc), text


def test_founder_gets_one_telegram_alert_and_a_console_banner(business, settings, rt):
    health.reset()
    fail(business.id, 2)
    rt.settings = dataclasses.replace(settings, founder_bot_token="999:FOUNDER", founder_chat_id="42")
    sent = []
    rt.http = type("H", (), {"post": lambda self, url, json, timeout: sent.append((url, json)) or
                             type("R", (), {"json": lambda self: {"ok": True, "result": {}}})()})()
    sched = Scheduler(rt, 300)
    sched.tick(NOW_UTC)
    assert not sent  # two failures are not an outage yet
    fail(business.id, 1, tag="b")
    sched.tick(NOW_UTC)
    sched.tick(NOW_UTC + timedelta(minutes=5))  # still down: no repeat within two hours
    assert len(sent) == 1 and sent[0][0].endswith("/bot999:FOUNDER/sendMessage")
    assert sent[0][1]["chat_id"] == "42" and "закончился баланс" in sent[0][1]["text"]

    owner = dataclasses.replace(rt.settings, owner_password="owner-pass-123")
    rt.settings = owner
    with TestClient(create_app(owner, rt, init=False)) as c:
        token = csrf_of(c.get("/owner/login").text)
        c.post("/owner/login", data={"password": "owner-pass-123", "csrf": token})
        page = c.get("/owner").text
    assert "ИИ не отвечает клиентам" in page and "закончился баланс" in page


def test_no_alert_without_settings_or_failures(business, settings, rt):
    health.reset()
    with db.new_session() as s:
        assert health.maybe_alert(s, rt, NOW_UTC) is False
        assert not health.status(s, NOW_UTC).down
