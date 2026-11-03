"""The panel's test chat (channel "console") is the owner writing as a customer: it stays out of every number,
report, staff reminder and CRM push (joop/stats.py), while its messages and bookings stay visible in the panel."""

from datetime import datetime, timedelta

from sqlmodel import select

from joop import crm, db, nudges, pilot
from joop.models import Booking, Business, Conversation, Lead, Message, Order
from joop.presets import create_business
from joop.scheduler import monthly_report_text
from joop.stats import activity, by_hour

NOON_UTC = datetime(2026, 11, 4, 6, 0)  # Wednesday 12:00 in Bishkek: working hours


def seed(at: datetime):
    """One real Telegram customer and the owner's test chat, each with a message, an AI reply, a booking and a request."""
    with db.new_session() as s:
        b = create_business(s, slug="salon", name="Салон", password="secret-pass", niche="beauty", now_utc=at)
        s.flush()
        for channel, chat in (("telegram", "777"), ("console", "try")):
            conv = Conversation(business_id=b.id, channel=channel, chat_id=chat, created_at=at)
            s.add(conv)
            s.flush()
            s.add(Message(business_id=b.id, conversation_id=conv.id, role="customer", text="Маникюр?", created_at=at, off_hours=True))
            s.add(Message(business_id=b.id, conversation_id=conv.id, role="ai", text="1 200 сом", created_at=at, cost_usd=0.001))
            s.add(Booking(business_id=b.id, conversation_id=conv.id, start=at + timedelta(days=1), source="ai", channel=channel,
                          service="Маникюр", customer_name="Айгерим", customer_phone="+996555123456", created_at=at,
                          created_off_hours=True))
            s.add(Lead(business_id=b.id, conversation_id=conv.id, kind="handoff", channel=channel, summary="Вопрос", created_at=at))
            s.add(Order(business_id=b.id, conversation_id=conv.id, channel=channel, total=500, created_at=at))
        s.commit()
        return b.id


def test_dashboard_numbers_and_chart_count_only_real_customers(engine):
    bid = seed(NOON_UTC - timedelta(hours=2))
    with db.new_session() as s:
        st = activity(s, bid, NOON_UTC - timedelta(days=1))
        hours = by_hour(s, bid, NOON_UTC - timedelta(days=1), "Asia/Bishkek")
    assert (st["customer_messages"], st["conversations"], st["off_hours_conversations"]) == (1, 1, 1)
    assert (st["bookings"], st["off_hours_bookings"], st["leads"], st["orders"], st["ai_replies"]) == (1, 1, 1, 1, 1)
    assert round(st["ai_cost_usd"], 6) == 0.001 and hours["total"] == 1


def test_pilot_table_leaves_out_test_chats(engine):
    seed(NOON_UTC - timedelta(hours=2))
    with db.new_session() as s:
        rows, total = pilot.report(s, NOON_UTC - timedelta(days=1), NOON_UTC, NOON_UTC)
    (row,) = rows
    assert (row.conversations, row.customer_messages, row.ai_replies, row.bookings, row.handoffs, row.orders) == (1, 1, 1, 1, 1, 1)
    assert round(row.cost_usd, 6) == 0.001


def test_a_business_that_only_tested_gets_no_monthly_report(engine):
    at = datetime(2026, 10, 14, 6, 0)
    bid = seed(at)
    first = datetime(2026, 11, 1, 3, 0)  # 1 November, 09:00 in Bishkek
    with db.new_session() as s:
        text = monthly_report_text(s, s.get(Business, bid), first)
        assert "Ответил 1 клиенту" in text and "Записал сам 1 клиента" in text and "Оформил заказов: 1" in text
        test = s.exec(select(Conversation).where(Conversation.channel == "telegram")).one()
        for model in (Message, Booking, Lead, Order):  # the real customer goes; the test chat stays
            for row in s.exec(select(model).where(model.conversation_id == test.id)).all():
                s.delete(row)
        s.commit()
        assert monthly_report_text(s, s.get(Business, bid), first) is None


def test_staff_reminders_and_crm_skip_the_test_chat(engine):
    bid = seed(NOON_UTC - timedelta(hours=2))
    with db.new_session() as s:
        b = s.get(Business, bid)
        waiting = nudges.overdue(s, b, NOON_UTC)
        items = crm.due_items(s, b, NOON_UTC)
    assert [x.channel for x in waiting] == ["telegram"]
    assert sorted(type(i.row).__name__ + ":" + i.row.channel for i in items) == ["Booking:telegram", "Lead:telegram",
                                                                                 "Order:telegram"]
