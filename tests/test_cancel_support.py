"""Cancelling the subscription in one click, and the founder's contacts in the panel for the first month."""

import dataclasses
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlmodel import select

from joop import billing, db
from joop.models import Business, Subscription
from joop.timeutil import utcnow
from joop.web.app import create_app

from .conftest import NOW_UTC
from .test_web import csrf_of, login


def test_cancel_works_to_the_end_then_stops_and_resume_undoes(settings, rt, business, monkeypatch):
    from joop import health

    rt.settings = dataclasses.replace(settings, founder_bot_token="F:TOKEN", founder_chat_id="42", contact_phone="+996 555 000 111")
    monkeypatch.setattr(health, "_send", lambda rt_, text: rt.tg.send_text("42", text))  # the founder bot
    with db.new_session() as s:
        billing.start_trial(s, s.get(Business, business.id), 14, NOW_UTC, "signup", "Айгерим", "0555 123 456")
        s.commit()
    with TestClient(create_app(rt.settings, rt, init=False)) as c:
        token = login(c)
        page = c.get("/panel/billing").text
        assert "Отменить подписку" in page and "Возобновить" not in page
        r = c.post("/panel/billing/cancel", data={"csrf": token, "reason": "Дорого для нас"})
        assert "Подписка отменена. ИИ продолжит отвечать до" in r.text and "Возобновить" in r.text and "Отменить подписку" not in r.text
        assert ("42", "Joop AI: «Ак-Тиш Дент» отменил подписку — Дорого для нас. Телефон: 0555 123 456.") in rt.tg.sent
        with db.new_session() as s:
            sub = s.exec(select(Subscription)).one()
            assert sub.cancelled_at is not None and sub.cancel_reason == "Дорого для нас"
            assert billing.state(sub, NOW_UTC + timedelta(days=13)).active  # to the end of the trial
            after = billing.state(sub, sub.trial_ends_at + timedelta(days=1))
            assert not after.active and after.label == "Отменена"  # no grace period after a cancellation
            assert billing.state(sub, NOW_UTC + timedelta(days=1)).label == "Отменена, пробный период"
        r = c.post("/panel/billing/resume", data={"csrf": token})
        assert "Подписка возобновлена" in r.text and "Отменить подписку" in r.text
        with db.new_session() as s:
            sub = s.exec(select(Subscription)).one()
            assert sub.cancelled_at is None and billing.state(sub, sub.trial_ends_at + timedelta(days=1)).code == "grace"


def test_support_contacts_show_for_the_first_month_only(settings, rt, business):
    rt.settings = dataclasses.replace(settings, contact_phone="+996 555 000 111", contact_telegram="joop_help")
    with TestClient(create_app(rt.settings, rt, init=False)) as c:
        login(c)
        page = c.get("/panel").text
        assert "Первый месяц — помогаем лично" in page and "https://wa.me/996555000111" in page and "https://t.me/joop_help" in page
        with db.new_session() as s:
            b = s.get(Business, business.id)
            b.created_at = utcnow() - timedelta(days=31)
            s.add(b)
            s.commit()
        assert "помогаем лично" not in c.get("/panel").text
    with TestClient(create_app(settings, rt, init=False)) as c:  # no contacts configured: nothing shown
        login(c)
        assert "помогаем лично" not in c.get("/panel").text
