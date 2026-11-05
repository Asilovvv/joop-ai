"""Customer cards assembled by the AI from bookings, orders and dialogues (joop/customers.py)."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlmodel import select

from joop import customers, db
from joop.models import Booking, Business, Conversation, Customer, Message, Order
from joop.web.app import create_app

from .conftest import NOW_UTC
from .test_web import csrf_of, login


def _seed(business_id):
    with db.new_session() as s:
        b = s.get(Business, business_id)
        conv = Conversation(business_id=b.id, channel="telegram", chat_id="1001", customer_name="Айбек", customer_phone="+996555123456",
                            last_customer_at=NOW_UTC - timedelta(hours=2))
        nameless = Conversation(business_id=b.id, channel="instagram", chat_id="ig-9", display_name="aigerim_nails", last_customer_at=NOW_UTC)
        test = Conversation(business_id=b.id, channel="console", chat_id="panel", customer_phone="+996555000999")
        visitor = Conversation(business_id=b.id, channel="web", chat_id="web-abc", display_name="Посетитель сайта", last_customer_at=NOW_UTC)
        s.add_all([conv, nameless, test, visitor])
        s.flush()
        s.add(Message(business_id=b.id, conversation_id=conv.id, role="customer", text="?", created_at=NOW_UTC))
        s.add(Booking(business_id=b.id, conversation_id=conv.id, customer_name="Айбек", customer_phone="+996555123456", service="Профессиональная чистка",
                      staff_name="Айгерим", start=NOW_UTC - timedelta(days=10), channel="telegram", rating=5))
        s.add(Booking(business_id=b.id, customer_name="Айбек", customer_phone="0555 123 456", service="Профессиональная чистка",  # typed by staff, same phone
                      start=NOW_UTC - timedelta(days=40), channel="panel", source="panel"))
        s.add(Booking(business_id=b.id, customer_name="Айбек", customer_phone="+996555123456", service="Профессиональная чистка",
                      start=NOW_UTC - timedelta(days=1), channel="telegram", status="cancelled"))
        s.add(Booking(business_id=b.id, customer_name="Тест", customer_phone="+996555000999", service="Профессиональная чистка",
                      start=NOW_UTC, channel="console"))
        s.add(Order(business_id=b.id, customer_phone="+996555123456", channel="telegram", total=1500))
        s.commit()


def test_cards_merge_by_phone_and_skip_the_test_chat(business):
    _seed(business.id)
    with db.new_session() as s:
        b = s.get(Business, business.id)
        rows = customers.cards(s, b)
    assert set(rows) == {"555123456", "instagram:ig-9", "web:web-abc"}
    c = rows["555123456"]
    assert c.name == "Айбек" and c.channels == {"telegram"} and c.visits == 2 and len(c.bookings) == 3
    assert c.spend_som == 3000 * 2 + 1500 and c.rating == 5.0 and c.last_visit == NOW_UTC - timedelta(days=10)
    assert rows["instagram:ig-9"].name == "aigerim_nails" and rows["instagram:ig-9"].visits == 0


def test_listing_search_tags_and_csv(business):
    _seed(business.id)
    with db.new_session() as s:
        b = s.get(Business, business.id)
        customers.save_note(s, b, "555123456", "  Боится уколов ", "VIP, VIP, аллергия ")
        s.commit()
        assert [c.key for c in customers.listing(s, b)] == ["instagram:ig-9", "555123456"]  # by last contact; the anonymous site visitor is not listed
        assert [c.key for c in customers.listing(s, b, "555 123")] == ["555123456"]
        assert [c.key for c in customers.listing(s, b, "айб")] == ["555123456"]
        assert [c.key for c in customers.listing(s, b, tag="VIP")] == ["555123456"]
        assert s.exec(select(Customer)).one().tags == "VIP, аллергия"
        text = customers.export_csv(customers.listing(s, b), b.timezone)
        assert text.startswith("﻿Имя;Телефон") and "Айбек;+996555123456;telegram;2;" in text and "Боится уколов" in text


def test_customers_pages(business, rt, settings):
    _seed(business.id)
    with TestClient(create_app(settings, rt, init=False)) as c:
        login(c)
        page = c.get("/panel/customers").text
        assert "2 клиента" in page and "/panel/customers/555123456" in page and 'href="/panel/customers"' in page
        card = c.get("/panel/customers/555123456").text
        assert "Айбек" in card and "Профессиональная чистка" in card and "отменено" in card and "заказ на 1500 сом" in card
        token = csrf_of(card)
        c.post("/panel/customers/555123456", data={"csrf": token, "note": "Любит кофе", "tags": "VIP"})
        assert "Любит кофе" in c.get("/panel/customers/555123456").text
        assert c.get("/panel/customers/nobody").status_code == 404
        csv_text = c.get("/panel/customers.csv")
        assert csv_text.headers["content-type"].startswith("text/csv") and "Любит кофе" in csv_text.text
