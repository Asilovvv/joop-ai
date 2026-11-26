"""Fixes from the independent review of #292–#302 (26 November 2026), each with the case the reviewer reproduced."""

import dataclasses
import time
from datetime import datetime, timedelta

from sqlmodel import select

from joop import billing, db, dispatch, health, period_end, timeutil
from joop.agent.engine import handle_incoming
from joop.channels.base import IncomingMessage
from joop.models import Business, Payment
from joop.web import saas

from .conftest import FakeLLM
from .test_saas import _callback, app_client, owner_login, saas_settings, signup  # noqa: F401
from .test_trial_end import TRIAL_ENDS, morning, setup
from .test_web import csrf_of


def test_paying_when_asked_keeps_the_rest_of_the_trial(business, rt):
    """The notice asks to pay three days before the trial ends; paying then counted 30 days from the payment."""
    setup(business.id)
    with db.new_session() as s:
        assert period_end.notice(s, s.get(Business, business.id), morning(14), "https://joop.test", 3000)
        pay = Payment(business_id=business.id, amount_som=3000, method="manual")
        s.add(pay)
        s.flush()
        sub = billing.mark_paid(s, pay, morning(14))
        assert sub.paid_until == TRIAL_ENDS + timedelta(days=30)  # before: 2 days 3.5 hours short


def lapsed_then_trial(business_id):
    """Paid once, lapsed in October; the founder resumed it and gave a trial to 10.11 (console «resume», «extend»)."""
    setup(business_id)
    with db.new_session() as s:
        sub = billing.get_subscription(s, business_id)
        sub.paid_until, sub.status, sub.trial_ends_at = datetime(2026, 10, 1, 6, 0), "trial", datetime(2026, 11, 10, 6, 0)
        s.commit()


def test_a_trial_after_a_lapsed_paid_month_is_a_trial_with_its_own_waiting_days(business, rt):
    lapsed_then_trial(business.id)
    with db.new_session() as s:
        b, sub = s.get(Business, business.id), billing.get_subscription(s, business.id)
        assert period_end.notice(s, b, morning(9), "https://joop.test", 3000).startswith(
            "Пробный период «Ак-Тиш Дент» заканчивается 10.11 в 12:00")  # before: «Оплаченный период»
        s.commit()
        assert billing.state(sub, morning(11)).code == "grace" and billing.access_ok(s, b.id, morning(11))  # before: stopped
        assert period_end.banner(s, b, morning(11)).text.startswith("Пробный период закончился 10.11. ИИ отвечает клиентам до 13.11")
        assert period_end.banner(s, b, morning(14)).text.startswith("ИИ не отвечает клиентам с 13.11")  # before: «с 04.10»


def test_the_founders_extend_works_for_a_lapsed_paid_business(app_client):
    signup(app_client)
    with db.new_session() as s:
        b = s.exec(select(Business)).one()
        sub = billing.get_subscription(s, b.id)
        sub.status, sub.paid_until = "active", datetime(2026, 10, 1)
        s.commit()
        bid = b.id
    token = owner_login(app_client)
    app_client.post(f"/owner/business/{bid}", data={"action": "extend", "days": 7, "csrf": token})
    with db.new_session() as s:
        sub = billing.get_subscription(s, bid)
        assert billing.state(sub, timeutil.utcnow()).code == "trial" and billing.access_ok(s, bid, timeutil.utcnow())


def test_a_second_click_reuses_the_transfer_request(app_client, rt, monkeypatch):
    told = []
    rt.settings = dataclasses.replace(rt.settings, founder_bot_token="F:T", founder_chat_id="42")
    monkeypatch.setattr(health, "_send", lambda rt_, text: told.append(text) or True)
    signup(app_client)
    for _ in range(3):
        token = csrf_of(app_client.get("/panel/billing").text)
        page = app_client.post("/panel/billing/pay", data={"method": "manual", "csrf": token}).text
    with db.new_session() as s:
        (pay,) = s.exec(select(Payment)).all()
    assert len(told) == 1 and f"Заявка на оплату №{pay.id} уже создана" in page


def note_at(business_id, when, chat="700"):
    with db.new_session() as s:
        out = handle_incoming(s, s.get(Business, business_id), IncomingMessage("telegram", chat, "text", "Здравствуйте", "Айбек", f"x{chat}{when}"),
                              lambda: FakeLLM(), when, base_url="https://joop.test")
        s.commit()
        return out.admin_notes[0]


def test_the_staff_note_asks_to_pay_only_when_paying_is_the_answer(business):
    setup(business.id)
    assert note_at(business.id, morning(20)).endswith("Оплатить: https://joop.test/panel/billing")
    with db.new_session() as s:
        s.add(Payment(business_id=business.id, amount_som=3000, method="manual", created_at=morning(20)))
        s.commit()
    waiting = note_at(business.id, morning(20) + timedelta(hours=1), chat="701")
    assert "ждёт подтверждения перевода" in waiting and "Оплатить" not in waiting
    with db.new_session() as s:
        billing.get_subscription(s, business.id).status = "suspended"
        s.commit()
    suspended = note_at(business.id, morning(20) + timedelta(hours=2), chat="702")
    assert "доступ приостановлен" in suspended and "Оплатить" not in suspended


def test_freedompay_gets_its_answer_before_the_owner_is_told(app_client, rt, monkeypatch):
    """The note waited inside the bank's callback (each staff send up to 20 s); an error in it gave the bank a 500,
    and its retry found the payment paid, so nobody was told."""
    signup(app_client)
    with db.new_session() as s:
        bid = s.exec(select(Business)).one().id
        pay = Payment(business_id=bid, amount_som=3000, method="freedompay")
        s.add(pay)
        s.commit()
        pid = pay.id
    order = []
    monkeypatch.setattr(saas.billing, "fp_reply", (lambda real: lambda *a, **k: order.append("reply") or real(*a, **k))(billing.fp_reply))

    def broken(*args, **kwargs):
        order.append("tell")
        raise RuntimeError("Telegram is down")

    monkeypatch.setattr(dispatch, "notify_admins", broken)
    started = time.perf_counter()
    r = _callback(app_client, pid, 3000)
    assert r.status_code == 200 and "<pg_status>ok</pg_status>" in r.text  # before: a 500
    assert order == ["reply", "tell"] and time.perf_counter() - started < 5
    with db.new_session() as s:
        assert s.get(Payment, pid).status == "paid"
