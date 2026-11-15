"""The owner sees what reminders brought: «повторили заказ», «купили после «снова в наличии»», with the money."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlmodel import select

from joop import db, reorders, restock
from joop.models import Business, Conversation, Message, Order, OrderLine, Service
from joop.scheduler import weekly_report_text
from joop.web.app import create_app

from .conftest import NOW_UTC
from .test_holds import with_bot
from .test_pharmacy import pharmacy
from .test_reorders import run, turn_on
from .test_restock import ask, masks, restock_masks
from .test_restock import run as notify
from .test_water import company, first_order
from .test_web import csrf_of


def add_order(business_id, chat, when, item_id, qty, total, status="new"):
    with db.new_session() as s:
        conv = s.exec(select(Conversation).where(Conversation.business_id == business_id, Conversation.chat_id == chat)).one()
        s.add(Message(business_id=business_id, conversation_id=conv.id, role="customer", text="да", created_at=when))
        order = Order(business_id=business_id, conversation_id=conv.id, mode="delivery", status=status, total=total, created_at=when)
        s.add(order)
        s.flush()
        s.add(OrderLine(order_id=order.id, item_id=item_id, name="x", quantity=qty, unit_price=total // qty))
        s.commit()


def test_reorders_count_new_orders_within_a_week(engine, rt):
    b = company()
    turn_on(b.id)
    first_order(b.id)
    reminded = NOW_UTC + timedelta(days=14)
    run(rt, b.id, reminded)
    with db.new_session() as s:
        water = s.exec(select(Service).where(Service.business_id == b.id, Service.name == "Вода питьевая, бутыль 19 л")).one().id
    add_order(b.id, "w1", reminded + timedelta(hours=2), water, 2, 360)
    add_order(b.id, "w1", reminded + timedelta(hours=3), water, 1, 180, status="cancelled")  # not counted
    with db.new_session() as s:
        assert reorders.results(s, b.id, reminded - timedelta(days=1)) == (1, 1, 360)
        text = weekly_report_text(s, s.get(Business, b.id), reminded + timedelta(days=2))
    assert "Напомнили повторить заказ: 1, заказали снова: 1 на 360 сом." in text


def test_restock_counts_orders_of_that_item_and_the_page_shows_both(settings, rt, engine):
    b = pharmacy()
    with_bot(b.id)
    ask(b.id, "Маски есть?", "a")
    restock_masks(b.id)
    told = NOW_UTC + timedelta(days=2, hours=16)
    notify(rt, b.id, told)
    with db.new_session() as s:
        para = s.exec(select(Service).where(Service.business_id == b.id, Service.name.startswith("Парацетамол"))).one().id
    add_order(b.id, "c1", told + timedelta(hours=1), para, 7, 315)  # another item: not brought by the message
    add_order(b.id, "c1", told + timedelta(hours=2), masks(b.id).id, 2, 500)
    with db.new_session() as s:
        assert restock.results(s, b.id, NOW_UTC) == (1, 1, 500)
    with TestClient(create_app(settings, rt, init=False)) as c:
        token = csrf_of(c.get("/login").text)
        c.post("/login", data={"slug": "dary", "password": "dary-pass-123", "csrf": token})
        page = c.get("/panel/followups").text
    assert "<b>1 из 1</b><span>купили после «снова в наличии», 500 сом</span>" in page
    assert "повторили заказ после напоминания" not in page  # a pharmacy does not remind to reorder
