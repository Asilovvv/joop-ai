"""Pilot report (joop/pilot.py) and its founder-console page."""

import csv
import io
from datetime import timedelta

from sqlmodel import select

from joop import billing, db, pilot
from joop.models import Booking, Business, Conversation, Lead, Message, Order, Payment
from joop.presets import create_business

from .conftest import NOW_UTC
from .test_saas import app_client, owner_login, saas_settings  # noqa: F401  (fixtures)


def activity(s, b, chat, days_ago, off=False, reply_cost=0.0005):
    at = NOW_UTC - timedelta(days=days_ago)
    conv = s.exec(select(Conversation).where(Conversation.business_id == b.id, Conversation.chat_id == chat)).first()
    if conv is None:
        conv = Conversation(business_id=b.id, channel="telegram", chat_id=chat, created_at=at)
        s.add(conv)
        s.flush()
    s.add(Message(business_id=b.id, conversation_id=conv.id, role="customer", text="?", created_at=at, off_hours=off))
    s.add(Message(business_id=b.id, conversation_id=conv.id, role="ai", text="!", created_at=at, cost_usd=reply_cost))
    return conv


def seed():
    with db.new_session() as s:
        salon = create_business(s, slug="salon1", name="Салон Гүл", password="secret-pass", niche="beauty", now_utc=NOW_UTC)
        cafe = create_business(s, slug="cafe1", name="Кафе Нур", password="secret-pass", niche="restaurant", now_utc=NOW_UTC)
        demo = create_business(s, slug="site-demo-salon", name="Витрина сайта", password="secret-pass", now_utc=NOW_UTC)
        quiet = create_business(s, slug="quiet1", name="Тихая", password="secret-pass", now_utc=NOW_UTC)  # noqa: F841
        s.flush()
        c1 = activity(s, salon, "a", 1, off=True)
        activity(s, salon, "a", 1)
        activity(s, salon, "b", 3, off=True)
        activity(s, salon, "c", 30)  # before the period
        s.add(Booking(business_id=salon.id, conversation_id=c1.id, start=NOW_UTC, source="ai", created_at=NOW_UTC - timedelta(days=1)))
        s.add(Booking(business_id=salon.id, start=NOW_UTC, source="panel", created_at=NOW_UTC - timedelta(days=1)))  # staff, not AI
        s.add(Lead(business_id=salon.id, kind="handoff", created_at=NOW_UTC - timedelta(days=2)))
        s.add(Lead(business_id=salon.id, kind="error", created_at=NOW_UTC - timedelta(days=2)))
        s.add(Lead(business_id=salon.id, kind="request", created_at=NOW_UTC - timedelta(days=2)))
        billing.start_trial(s, salon, 14, NOW_UTC - timedelta(days=20))
        sub = billing.start_trial(s, cafe, 14, NOW_UTC - timedelta(days=5))
        sub.paid_until = NOW_UTC + timedelta(days=25)
        s.add(Payment(business_id=cafe.id, amount_som=3000, status="paid", paid_at=NOW_UTC))
        activity(s, cafe, "x", 2)
        s.add(Order(business_id=cafe.id, created_at=NOW_UTC - timedelta(days=2)))
        activity(s, demo, "d", 1)
        s.commit()


def test_report_counts_what_the_ai_did_per_business(engine):
    seed()
    with db.new_session() as s:
        rows, total = pilot.report(s, NOW_UTC - timedelta(days=14), NOW_UTC + timedelta(hours=1), NOW_UTC)
    assert [r.business for r in rows] == ["Салон Гүл", "Кафе Нур"]  # busiest first; demo and silent ones left out
    salon, cafe = rows
    assert (salon.conversations, salon.customer_messages, salon.off_hours_messages, salon.off_hours_pct, salon.active_days) == (2, 3, 2, 67, 2)
    assert (salon.bookings, salon.requests, salon.completed, salon.handoffs, salon.failures) == (1, 1, 2, 1, 1)
    assert round(salon.cost_usd, 6) == 0.0015 and round(salon.cost_per_reply, 6) == 0.0005
    assert salon.status == "Не оплачено" and not salon.paying
    assert cafe.orders == 1 and cafe.paying and cafe.status == "Оплачено"
    assert (total.conversations, total.customer_messages, total.completed) == (3, 4, 3) and total.status == "платят: 1"


def test_csv_has_one_row_per_business_and_a_total(engine):
    seed()
    with db.new_session() as s:
        rows, total = pilot.report(s, NOW_UTC - timedelta(days=14), NOW_UTC + timedelta(hours=1), NOW_UTC)
    table = list(csv.DictReader(io.StringIO(pilot.to_csv(rows, total))))
    assert [r["business"] for r in table] == ["Салон Гүл", "Кафе Нур", "Итого: 2"]
    assert table[0]["off_hours_pct"] == "67" and table[0]["completed_by_ai"] == "2" and table[0]["cost_per_reply_usd"] == "0.000500"


def test_owner_page_and_download(app_client):  # noqa: F811
    seed()
    assert app_client.get("/owner/pilot", follow_redirects=False).headers["location"] == "/owner/login"
    owner_login(app_client)
    since = (NOW_UTC - timedelta(days=14)).date().isoformat()
    until = (NOW_UTC + timedelta(days=1)).date().isoformat()
    page = app_client.get(f"/owner/pilot?since={since}&until={until}").text
    assert "Пилот: что сделал ИИ" in page and "Салон Гүл" in page and "Кафе Нур" in page and "Витрина сайта" not in page
    assert "2 (67%)" in page and "Итого: 2" in page
    r = app_client.get(f"/owner/pilot.csv?since={since}&until={until}")
    assert r.headers["content-type"].startswith("text/csv") and f"joop-pilot-{since}-{until}.csv" in r.headers["content-disposition"]
    assert r.text.splitlines()[0].startswith("business,niche,active_days,conversations")
    # A period with no activity, given in the wrong order: swapped, and an empty note instead of a table.
    page = app_client.get("/owner/pilot?since=2020-01-31&until=2020-01-01").text
    assert "клиенты не писали" in page and 'value="2020-01-01"' in page
