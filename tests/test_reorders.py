"""«Пора повторить заказ?» (joop/reorders.py): one reminder at the customer's own pace, «стоп» works after it."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlmodel import select

from joop import db, reorders
from joop.agent.engine import handle_incoming
from joop.agent.llm import AgentReply
from joop.channels.base import IncomingMessage
from joop.models import Business, Conversation, Order, OrderLine, Service
from joop.web.app import create_app

from .conftest import NOW_UTC, FakeLLM
from .test_water import company, first_order, item
from .test_web import csrf_of


def turn_on(business_id, token=True):
    with db.new_session() as s:
        b = s.get(Business, business_id)
        b.return_invites = True
        if token:
            b.telegram_bot_token = "123:TEST"
        s.add(b)
        s.commit()


def run(rt, business_id, when):
    with db.new_session() as s:
        out = reorders.send_due(s, rt, s.get(Business, business_id), when)
        s.commit()
        return out


def test_one_reminder_after_the_items_days_naming_the_last_order(engine, rt):
    b = company()
    turn_on(b.id)
    order_id = first_order(b.id)  # 2 bottles + 2 deposits; the bottle is set to 14 days
    assert run(rt, b.id, NOW_UTC + timedelta(days=13)) == {}  # not yet
    assert run(rt, b.id, NOW_UTC + timedelta(days=14)) == {"sent": 1, "failed": 0}
    chat, text = rt.tg.sent[-1]
    assert chat == "w1" and text.startswith(f"Здравствуйте! Ваш прошлый заказ №{order_id} от 04.11: 2 × Вода питьевая, бутыль 19 л")
    assert "Ответьте «да»" in text and "напишите «стоп»" in text
    assert run(rt, b.id, NOW_UTC + timedelta(days=15)) == {}  # once per order


def test_the_customers_own_interval_wins_and_a_newer_order_resets_it(engine, rt):
    b = company()
    turn_on(b.id)
    water = item(b.id, "Вода питьевая, бутыль 19 л")
    first_order(b.id)
    with db.new_session() as s:
        conv = s.exec(select(Conversation).where(Conversation.business_id == b.id)).one()
        for days in (7, 14):  # a weekly customer
            s.add(Order(business_id=b.id, conversation_id=conv.id, mode="delivery", status="done", total=360,
                        customer_name="Айгуль", customer_phone="+996555909090", created_at=NOW_UTC + timedelta(days=days)))
        s.commit()
        last = s.exec(select(Order).where(Order.business_id == b.id).order_by(Order.id.desc())).first()
        s.add(OrderLine(order_id=last.id, item_id=water.id, name=water.name, quantity=3, unit_price=180))
        s.commit()
    assert run(rt, b.id, NOW_UTC + timedelta(days=20)) == {}
    assert run(rt, b.id, NOW_UTC + timedelta(days=21)) == {"sent": 1, "failed": 0}  # 14 + its usual 7 days
    assert "3 × Вода питьевая" in rt.tg.sent[-1][1]


def test_off_by_default_skips_late_and_test_chats_and_stop_unsubscribes(engine, rt):
    b = company()
    first_order(b.id)
    assert run(rt, b.id, NOW_UTC + timedelta(days=14)) == {}  # the owner did not turn it on
    turn_on(b.id)
    assert run(rt, b.id, NOW_UTC + timedelta(days=22)) == {}  # more than a week late: not sent at all
    other = company("water", "suu2")
    turn_on(other.id)
    first_order(other.id, chat="w9")
    run(rt, other.id, NOW_UTC + timedelta(days=14))
    llm = FakeLLM([])
    with db.new_session() as s:
        handle_incoming(s, s.get(Business, other.id), IncomingMessage("telegram", "w9", "text", "стоп", "", "stop-1"),
                        lambda: llm, NOW_UTC + timedelta(days=14, hours=1))
        s.commit()
        conv = s.exec(select(Conversation).where(Conversation.business_id == other.id, Conversation.chat_id == "w9")).one()
        assert conv.broadcast_opt_out and conv.silenced


def test_a_shop_without_repeat_order_gets_none_and_the_settings_page_speaks_of_orders(settings, rt, engine):
    with db.new_session() as s:
        from joop.presets import create_business

        create_business(s, slug="gul", name="Гүл", password="gul-pass-123", niche="florist", demo=True, now_utc=NOW_UTC)
        s.commit()
    b = company()
    with TestClient(create_app(settings, rt, init=False)) as c:
        token = csrf_of(c.get("/login").text)
        c.post("/login", data={"slug": "suu", "password": "suu-pass-123", "csrf": token})
        page = c.get("/panel/followups").text
    assert "Напоминать клиентам повторить заказ" in page and "Приглашать клиентов повторить услугу" not in page
    with db.new_session() as s:
        assert s.exec(select(Service).where(Service.business_id == b.id, Service.name == "Вода питьевая, бутыль 19 л")).one().repeat_days == 14
