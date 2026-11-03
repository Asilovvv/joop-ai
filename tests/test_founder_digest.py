"""The founder's Monday line in Telegram: paying businesses and bookings through the AI (joop/founder_digest.py)."""

import dataclasses
from datetime import datetime, timedelta

from sqlmodel import select

from joop import billing, db, founder_digest, health
from joop.models import Booking, FounderDigest, Lead, Payment, Subscription
from joop.presets import create_business
from joop.scheduler import Scheduler

from .conftest import NOW_UTC
from .test_pilot import activity
from .test_saas import app_client, owner_login, saas_settings  # noqa: F401  (fixtures)

MONDAY_9 = datetime(2026, 11, 9, 3, 30)  # Monday 09:30 in Bishkek


def seed():
    with db.new_session() as s:
        salon = create_business(s, slug="salon1", name="Салон Гүл", password="secret-pass", niche="beauty", now_utc=NOW_UTC)
        cafe = create_business(s, slug="cafe1", name="Кафе Нур", password="secret-pass", niche="restaurant", now_utc=NOW_UTC)
        solo = create_business(s, slug="solo1", name="Мастер Айпери", password="secret-pass", now_utc=NOW_UTC)
        gone = create_business(s, slug="gone1", name="Ушедшая", password="secret-pass", now_utc=NOW_UTC)
        demo = create_business(s, slug="site-demo-salon", name="Витрина", password="secret-pass", now_utc=NOW_UTC)
        s.flush()
        sub = billing.start_trial(s, salon, 14, MONDAY_9 - timedelta(days=40))
        sub.paid_until = MONDAY_9 + timedelta(days=20)
        s.add(Payment(business_id=salon.id, amount_som=3000, status="paid", paid_at=MONDAY_9 - timedelta(days=2)))
        trial = billing.start_trial(s, cafe, 14, MONDAY_9 - timedelta(days=3))  # new this week, in trial
        free = billing.start_trial(s, solo, 14, MONDAY_9 - timedelta(days=30))
        free.plan = "free"
        old = billing.start_trial(s, gone, 14, MONDAY_9 - timedelta(days=60))
        billing.cancel(old, MONDAY_9 - timedelta(days=1), "дорого")
        for row, days in ((sub, 40), (trial, 3), (free, 30), (old, 60)):
            row.created_at = MONDAY_9 - timedelta(days=days)  # start_trial stamps the real clock
            s.add(row)
        c = activity(s, salon, "a", 0)
        activity(s, salon, "b", 0)
        activity(s, cafe, "c", 0)
        activity(s, demo, "d", 0)
        for conv in (c, c, None):
            s.add(Booking(business_id=salon.id, conversation_id=conv.id if conv else None, start=MONDAY_9, source="ai",
                          created_at=MONDAY_9 - timedelta(days=1)))
        s.add(Booking(business_id=salon.id, start=MONDAY_9, source="panel", created_at=MONDAY_9 - timedelta(days=1)))
        s.add(Booking(business_id=demo.id, start=MONDAY_9, source="ai", created_at=MONDAY_9 - timedelta(days=1)))
        s.add(Lead(business_id=salon.id, kind="handoff", created_at=MONDAY_9 - timedelta(days=2)))
        s.add(Lead(business_id=cafe.id, kind="error", created_at=MONDAY_9 - timedelta(days=2)))
        s.commit()


def test_text_is_one_line_of_the_numbers_the_strategy_asks_for(engine, saas_settings):
    seed()
    with db.new_session() as s:
        text = founder_digest.text(s, MONDAY_9, saas_settings.price_som)
    assert text == ("Joop AI, неделя 02.11–08.11. Платящих 1 (3 000 сом/мес), бесплатных 1, в пробном 1. "
                    "Записей через ИИ 3, диалогов 3, передано людям 1, сбоев 1. Новых регистраций 1, отмен 1. "
                    "Удержание через 90 дней: — (некого судить).")


def test_sent_once_on_monday_morning_and_kept_as_the_journal(engine, rt, saas_settings, monkeypatch):
    seed()
    rt.settings = dataclasses.replace(saas_settings, founder_bot_token="F:TOKEN", founder_chat_id="42")
    monkeypatch.setattr(health, "_send", lambda rt_, text: rt.tg.send_text("42", text))
    sched = Scheduler(rt, interval=60)
    sched.tick(MONDAY_9 - timedelta(hours=2))  # Monday 07:30: too early
    sched.tick(MONDAY_9 - timedelta(days=1))  # Sunday
    assert not [t for _, t in rt.tg.sent if t.startswith("Joop AI, неделя")]
    sched.tick(MONDAY_9)
    sched.tick(MONDAY_9 + timedelta(hours=3))  # the same Monday again: nothing more
    sent = [t for _, t in rt.tg.sent if t.startswith("Joop AI, неделя")]
    assert len(sent) == 1 and "Платящих 1" in sent[0]
    with db.new_session() as s:
        [row] = s.exec(select(FounderDigest)).all()
        assert row.week_start == datetime(2026, 11, 2).date() and row.text == sent[0]
    sched.tick(MONDAY_9 + timedelta(days=7))  # next Monday: the next line
    with db.new_session() as s:
        assert len(s.exec(select(FounderDigest)).all()) == 2


def test_without_the_founder_bot_the_journal_still_fills(engine, rt, saas_settings):
    seed()
    rt.settings = saas_settings  # no founder bot
    Scheduler(rt, interval=60).tick(MONDAY_9)
    with db.new_session() as s:
        [row] = s.exec(select(FounderDigest)).all()
        assert row.sent is False and row.text.startswith("Joop AI, неделя 02.11–08.11.")


def test_pilot_page_lists_the_weekly_lines(engine, app_client, rt):
    seed()
    Scheduler(rt, interval=60).tick(MONDAY_9)
    owner_login(app_client)
    page = app_client.get("/owner/pilot").text
    assert "Одна цифра в неделю" in page and "неделя 02.11–08.11" in page
