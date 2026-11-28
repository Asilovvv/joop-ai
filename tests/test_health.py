import dataclasses
from datetime import timedelta

from fastapi.testclient import TestClient

from joop import db, health, recovery
from joop.agent.engine import ERROR_REPLY, handle_incoming
from joop.agent.llm import AgentReply, BadOutput, LLMError
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


class _Alerts:
    def __init__(self, posted):
        self.posted = posted

    def _items(self):
        return [x for x in self.posted if not x[1].get("text", "").startswith("Joop AI, неделя")]

    def __len__(self):
        return len(self._items())

    def __getitem__(self, i):
        return self._items()[i]

    def __bool__(self):
        return bool(self._items())


def test_founder_gets_one_telegram_alert_and_a_console_banner(business, settings, rt, llm):
    health.reset()
    llm.replies = [credit_error] * 10  # the server's own call (health.probe) meets the same empty balance
    fail(business.id, 2)
    rt.settings = dataclasses.replace(settings, founder_bot_token="999:FOUNDER", founder_chat_id="42")
    posted = []
    rt.http = type("H", (), {"post": lambda self, url, json, timeout: posted.append((url, json)) or
                             type("R", (), {"json": lambda self: {"ok": True, "result": {}}})()})()
    sent = _Alerts(posted)  # the Monday digest (joop/founder_digest.py) also goes to the founder: not an alert
    sched = Scheduler(rt, 300)
    with db.new_session() as s:
        assert not health.status(s, NOW_UTC).down  # two failed calls are not an outage yet
    sched.tick(NOW_UTC)  # the server tries the two customers again (joop/recovery.py): the third failed call in a row
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


def test_founder_hears_once_when_the_ai_is_back(business, settings, rt, llm):
    from joop import recovery
    from joop.agent.llm import AgentReply

    health.reset()
    recovery.reset()
    rt.settings = dataclasses.replace(settings, founder_bot_token="999:FOUNDER", founder_chat_id="42")
    posted = []
    rt.http = type("H", (), {"post": lambda self, url, json, timeout: posted.append((url, json)) or
                             type("R", (), {"json": lambda self: {"ok": True, "result": {}}})()})()
    sent = _Alerts(posted)  # the Monday digest (joop/founder_digest.py) also goes to the founder: not an alert
    fail(business.id, 3)
    sched = Scheduler(rt, 300)
    llm.replies = [credit_error]  # still down at the first round: the waiting customers are tried and stay waiting
    sched.tick(NOW_UTC + timedelta(minutes=1))
    assert len(sent) == 1 and "ИИ не отвечает клиентам" in sent[0][1]["text"]

    llm.replies = [AgentReply("Чистка — 3 000 сом.")] * 3  # balance topped up
    sched.tick(NOW_UTC + timedelta(minutes=10))
    assert len(sent) == 2
    back = sent[1][1]["text"]
    assert "ИИ снова отвечает" in back and "остались 3 сообщений: на 3 ИИ ответил сам" in back and "0 заявок ещё ждут" in back
    with db.new_session() as s:
        st = health.status(s, NOW_UTC + timedelta(minutes=10))
        assert st.failures == 3 and st.recovered and not st.down  # the console shows "back", not "down"
    saved = rt.settings
    rt.settings = dataclasses.replace(saved, owner_password="owner-pass-123")
    with TestClient(create_app(rt.settings, rt, init=False)) as c:
        c.post("/owner/login", data={"password": "owner-pass-123", "csrf": csrf_of(c.get("/owner/login").text)})
        page = c.get("/owner").text
    assert "ИИ снова отвечает" in page and "ИИ не отвечает клиентам" not in page
    assert "с 04.11.2026 23:24)" in page  # Bishkek time (17:24 UTC), not the server's UTC
    rt.settings = saved
    sched.tick(NOW_UTC + timedelta(minutes=15))
    assert len(sent) == 2  # said once

    fail(business.id, 3, now=NOW_UTC + timedelta(minutes=20), tag="c")  # a new outage gets its own alert at once
    llm.replies = [credit_error]
    sched.tick(NOW_UTC + timedelta(minutes=21))
    assert len(sent) == 3 and "ИИ не отвечает клиентам" in sent[2][1]["text"]


def founder_inbox(rt, settings) -> "_Alerts":
    rt.settings = dataclasses.replace(settings, founder_bot_token="999:FOUNDER", founder_chat_id="42")
    posted = []
    rt.http = type("H", (), {"post": lambda self, url, json, timeout: posted.append((url, json)) or
                             type("R", (), {"json": lambda self: {"ok": True, "result": {}}})()})()
    return _Alerts(posted)


def probes(llm) -> int:
    return sum(1 for call in llm.calls if call["system"] == health.PING)


def test_customers_far_apart_are_still_an_outage(business):
    """Review of #321–#327: at a quiet hour failures never fell three into one half hour, so the model was never
    called down while every customer got the fallback."""
    for i in range(3):
        when = NOW_UTC + timedelta(minutes=31 * i)
        fail(business.id, 1, now=when, tag=f"q{i}")
        with db.new_session() as s:
            assert health.status(s, when).down == (i == 2), i


def test_the_server_asks_the_model_itself_after_one_unanswered_customer(business, settings, rt, llm):
    """One customer at night, nobody else writes: the server asks the model each tick and alerts the founder within
    a few ticks; it keeps knowing the model is down past half an hour; one tick after the balance is topped up the
    founder hears the AI is back. A model that answers is never asked."""
    recovery.reset()
    sent = founder_inbox(rt, settings)
    sched = Scheduler(rt, 300)
    for minute in (0, 5, 10):
        sched.tick(NOW_UTC + timedelta(minutes=minute))
    assert probes(llm) == 0 and not sent  # nothing failed: the model is not asked

    llm.replies = [credit_error] * 100
    fail(business.id, 1, now=NOW_UTC + timedelta(minutes=12))
    for minute in range(12, 30, 5):
        sched.tick(NOW_UTC + timedelta(minutes=minute))
    assert len(sent) == 1 and "ИИ не отвечает клиентам" in sent[0][1]["text"] and "закончился баланс" in sent[0][1]["text"]
    for minute in range(32, 130, 5):  # two hours on, nobody writes, the balance is still empty
        sched.tick(NOW_UTC + timedelta(minutes=minute))
        with db.new_session() as s:
            assert health.status(s, NOW_UTC + timedelta(minutes=minute)).down, minute
    asked = len(llm.calls)
    assert asked <= (130 - 12) // 5 + 2  # one call a tick at most: the late answer to the customer, or the probe

    llm.replies = []  # topped up: the fake model answers again
    sched.tick(NOW_UTC + timedelta(minutes=132))
    with db.new_session() as s:
        assert not health.status(s, NOW_UTC + timedelta(minutes=132)).down
    assert len(sent) == 2 and "ИИ снова отвечает" in sent[1][1]["text"]
    calls = len(llm.calls)
    for minute in (137, 142):
        sched.tick(NOW_UTC + timedelta(minutes=minute))
    assert len(llm.calls) == calls  # answering again: no more probes


def test_an_answer_that_could_not_be_read_is_one_chats_failure(business, settings, rt, llm):
    """Review of #321–#327: three unreadable answers in one chat called the model down for every business. They do
    not count; the server asks the model once, and its answer settles it. Unreadable for everyone is still found."""
    recovery.reset()
    sent = founder_inbox(rt, settings)
    unreadable = BadOutput("model output is not JSON")
    llm.replies = [unreadable] * 3
    for i in range(3):
        with db.new_session() as s:
            out = handle_incoming(s, s.get(Business, business.id), IncomingMessage("telegram", "same-chat", "text",
                                  f"Вопрос {i}", "", f"same-{i}"), lambda: llm, NOW_UTC)
            s.commit()
            assert out.reply == ERROR_REPLY
    with db.new_session() as s:
        st = health.status(s, NOW_UTC)
    assert st.failures == 3 and not st.down and "ответ модели не удалось разобрать" == st.reason

    sched = Scheduler(rt, 300)
    sched.tick(NOW_UTC + timedelta(minutes=5))  # the late answer to that chat succeeds: the model answers
    with db.new_session() as s:
        assert not health.status(s, NOW_UTC + timedelta(minutes=5)).down
    assert not sent

    health.reset()
    recovery.reset()
    llm.replies = [unreadable] * 100  # now every answer is unreadable, the server's own too
    with db.new_session() as s:
        handle_incoming(s, s.get(Business, business.id), IncomingMessage("telegram", "other-chat", "text", "Ещё вопрос",
                        "", "other-1"), lambda: llm, NOW_UTC + timedelta(minutes=40))
        s.commit()
    for minute in range(40, 70, 5):
        sched.tick(NOW_UTC + timedelta(minutes=minute))
    with db.new_session() as s:
        assert health.status(s, NOW_UTC + timedelta(minutes=65)).down
    assert len(sent) == 1 and "ответ модели не удалось разобрать" in sent[0][1]["text"]



def test_the_server_asks_at_most_once_in_five_minutes(rt, llm):
    """Each probe is a paid call when the model answers: while it fails, at most one in PROBE_EVERY, however often
    the scheduler ticks."""
    llm.replies = [credit_error] * 20
    for minute in range(13):
        health.probe(rt, NOW_UTC + timedelta(minutes=minute), down=True)
    assert probes(llm) == 3  # minutes 0, 5 and 10


def test_the_founder_reads_what_the_server_saw():
    assert health.Status(2, "x", None).seen == "За последние 30 минут не удалось ответить 2 раза"
    assert health.Status(0, "x", None, in_a_row=True).seen == (
        "За последние 30 минут клиенты не писали, но на проверочный вызов сервера модель не отвечает")

