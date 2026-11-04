"""Findings of the independent review of PRs #80–#85, each closed with a test."""

import dataclasses
from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlmodel import select

from joop import billing, db, founder_digest, free_plan, health
from joop.agent.llm import AgentReply
from joop.models import Business, Conversation, FounderDigest, Payment, Staff, Subscription
from joop.scheduler import Scheduler, first_week_report_text
from joop.web.app import create_app

from .conftest import NOW_UTC, FakeLLM
from .test_free_plan import _one_master, say
from .test_pilot import activity
from .test_saas import app_client, owner_login, saas_settings  # noqa: F401  (fixtures)
from .test_web import login


def test_paying_after_a_cancellation_resumes(business):
    """Finding 1: a payment is the strongest "resume"; the paid month must not run labelled «Отменена»."""
    with db.new_session() as s:
        sub = billing.start_trial(s, s.get(Business, business.id), 14, NOW_UTC)
        billing.cancel(sub, NOW_UTC, "подумаю")
        payment = Payment(business_id=business.id, amount_som=3000, method="manual", period_days=30)
        s.add(payment)
        s.flush()
        billing.mark_paid(s, payment, NOW_UTC + timedelta(days=3))
        s.commit()
        sub = s.exec(select(Subscription)).one()
        assert sub.cancelled_at is None and sub.cancel_reason == ""
        assert billing.state(sub, NOW_UTC + timedelta(days=5)).label == "Оплачено"
        assert billing.state(sub, sub.paid_until + timedelta(days=1)).code == "grace"  # the grace period is back


def test_free_plan_with_more_masters_stops_the_ai_instead_of_bending(business, rt):
    """Finding 2: Altegio sync or a profile import can add masters past the limit; the AI then waits, data stays."""
    _one_master(business.id)
    with db.new_session() as s:
        free_plan.switch(billing.start_trial(s, s.get(Business, business.id), 14, NOW_UTC))
        s.commit()
        assert billing.access_ok(s, business.id, NOW_UTC)
        second = s.exec(select(Staff).where(Staff.business_id == business.id, Staff.active == False)).first()  # noqa: E712
        second.active = True  # what an Altegio sync does
        s.add(second)
        s.commit()
        assert not billing.access_ok(s, business.id, NOW_UTC)
        assert billing.state(billing.get_subscription(s, business.id), NOW_UTC).label == "Бесплатно: один мастер"
    rt._llm = FakeLLM([AgentReply("Чем помочь?")])
    assert say(business.id, rt, "Привет").skipped == "subscription"


def test_billing_page_explains_why_the_free_plan_waits(business, app_client):
    with db.new_session() as s:
        free_plan.switch(billing.start_trial(s, s.get(Business, business.id), 14, NOW_UTC))  # three masters
        s.commit()
    login(app_client)
    page = app_client.get("/panel/billing").text
    assert "На бесплатном тарифе один мастер" in page and "ИИ сейчас не отвечает" in page


def test_digest_is_written_later_in_the_week_when_monday_was_missed(engine, rt, saas_settings):
    """Finding 3: a server down on Monday must not leave a hole in the journal."""
    rt.settings = saas_settings
    tuesday = datetime(2026, 11, 10, 6, 0)  # Tuesday 12:00 Bishkek, nothing written on Monday
    Scheduler(rt, interval=60).tick(tuesday)
    with db.new_session() as s:
        [row] = s.exec(select(FounderDigest)).all()
        assert row.week_start == datetime(2026, 11, 2).date()
    Scheduler(rt, interval=60).tick(tuesday + timedelta(days=1))
    with db.new_session() as s:
        assert len(s.exec(select(FounderDigest)).all()) == 1  # still one line for that week
    with db.new_session() as s:
        assert not founder_digest.due(s, datetime(2026, 11, 16, 2, 0))  # next Monday 08:00: before the hour


def test_checklist_counts_the_free_plan_as_settled(business, app_client):
    """Finding 4: the launch checklist's «Оплата» item is done on the free plan."""
    _one_master(business.id)
    with db.new_session() as s:
        free_plan.switch(billing.start_trial(s, s.get(Business, business.id), 14, NOW_UTC))
        s.commit()
    login(app_client)
    page = app_client.get("/panel/setup").text
    assert "Бесплатный тариф: один мастер, без срока" in page


def test_telegram_start_greeting_carries_the_free_signature(business, rt):
    """Finding 5: on Telegram the first contact is /start, so the greeting is where the signature goes."""
    _one_master(business.id)
    with db.new_session() as s:
        free_plan.switch(billing.start_trial(s, s.get(Business, business.id), 14, NOW_UTC))
        s.commit()
    out = say(business.id, rt, "/start", "telegram", "1001")
    assert out.reply.endswith("\n\n— отвечает Joop AI, ИИ-администратор для бизнеса · https://joop.test")
    rt._llm = FakeLLM([AgentReply("Чем помочь?")])
    assert say(business.id, rt, "Привет", "telegram", "1001").reply == "Чем помочь?"  # not twice


def test_the_founder_looking_in_does_not_count_as_the_owner_reviewing(business, app_client):
    """Finding 6: the week-one metric is about the owner, not the founder helping with setup."""
    with db.new_session() as s:
        conv = activity(s, s.get(Business, business.id), "996555000111", 1)
        s.commit()
        cid = conv.id
    token = owner_login(app_client)
    app_client.post(f"/owner/business/{business.id}", data={"csrf": token, "action": "login"})
    assert app_client.get(f"/panel/conversations/{cid}").status_code == 200
    with db.new_session() as s:
        assert s.get(Conversation, cid).reviewed_at is None


def test_free_plan_refused_while_paid_and_cancel_refused_on_free(business, app_client, rt, monkeypatch):
    """Finding 7: no switching to free with paid days left; nothing to cancel on the free plan."""
    _one_master(business.id)
    with db.new_session() as s:
        sub = billing.start_trial(s, s.get(Business, business.id), 14, NOW_UTC)
        sub.paid_until = NOW_UTC + timedelta(days=20)
        sub.status = "active"
        s.add(sub)
        s.commit()
    token = login(app_client)
    page = app_client.get("/panel/billing").text
    assert "Перейти на бесплатный" not in page and "после оплаченного периода" in page
    r = app_client.post("/panel/billing/free", data={"csrf": token})
    assert "оплаченный период" in r.text
    with db.new_session() as s:
        sub = s.exec(select(Subscription)).one()
        assert sub.plan == "pro"
        sub.paid_until, sub.status = None, "trial"
        free_plan.switch(sub)
        s.add(sub)
        s.commit()
    monkeypatch.setattr(health, "_send", lambda rt_, text: rt.tg.send_text("42", text))
    r = app_client.post("/panel/billing/cancel", data={"csrf": token, "reason": "x"})
    assert "На бесплатном тарифе нечего отменять" in r.text and not rt.tg.sent
    with db.new_session() as s:
        assert s.exec(select(Subscription)).one().cancelled_at is None


def test_day_seven_report_does_not_invite_a_cancelled_owner_to_cancel(business, rt):
    """Finding 8."""
    with db.new_session() as s:
        b = s.get(Business, business.id)
        sub = billing.start_trial(s, b, 14, NOW_UTC - timedelta(days=8))
        billing.cancel(sub, NOW_UTC - timedelta(days=1), "")
        for i, days in enumerate((8, 5, 3)):  # the first real customer wrote eight days ago
            activity(s, b, f"c{i}", days)
        s.commit()
        text = first_week_report_text(s, b, NOW_UTC) or ""
    assert "отменить можно в любой момент" not in text
    assert "Подписка отменена: ИИ остановится" in text
