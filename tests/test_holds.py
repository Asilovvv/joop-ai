"""Pharmacy reservations expire by themselves (joop/holds.py): goods back on the shelf, the customer told."""

from datetime import datetime, time, timedelta

from sqlmodel import select

from joop import db, holds
from joop.models import Business, Conversation, Message, Order, Service
from joop.niches import get_pack
from joop.scheduler import run_due_jobs
from joop.timeutil import local_to_utc, utc_to_local

from .conftest import NOW_UTC
from .test_pharmacy import item, order, pharmacy


def reserve(business_id, mode="pickup", chat="h1"):
    para = item(business_id, "Парацетамол 500 мг, 20 таблеток")
    out, _ = order(business_id, [{"item_id": para.id, "quantity": 7, "note": ""}], mode, f"h-{chat}-{mode}", chat=chat)
    assert out.order_id
    return out.order_id


def stock_of(business_id):
    return item(business_id, "Парацетамол 500 мг, 20 таблеток").stock


def end_of_next_day(business):
    placed = utc_to_local(NOW_UTC, business.timezone).date()
    return local_to_utc(datetime.combine(placed + timedelta(days=2), time.min), business.timezone)


def with_bot(business_id):
    with db.new_session() as s:
        b = s.get(Business, business_id)
        b.telegram_bot_token, b.admin_chat_ids = "123:TEST", "999"
        s.add(b)
        s.commit()


def test_a_reservation_is_released_after_the_next_day_and_the_goods_return(engine, rt):
    assert get_pack("pharmacy").hold_days == 1 and get_pack("shop").hold_days == 0
    b = pharmacy()
    with_bot(b.id)
    before = stock_of(b.id)
    order_id = reserve(b.id)
    assert stock_of(b.id) == before - 7
    with db.new_session() as s:
        biz = s.get(Business, b.id)
        deadline = end_of_next_day(biz)
        assert holds.expires_at(biz, s.get(Order, order_id), 1) == deadline
        assert holds.release_expired(s, rt, biz, deadline - timedelta(minutes=1)) == []  # still the next day
        s.commit()
    with db.new_session() as s:
        report = run_due_jobs(s, rt, s.get(Business, b.id), deadline + timedelta(minutes=5))
    assert report["released_holds"] == [order_id]
    with db.new_session() as s:
        assert s.get(Order, order_id).status == "cancelled"
    assert stock_of(b.id) == before
    told = [t for chat, t in rt.tg.sent if chat == "h1"]
    assert told[-1] == f"Срок хранения заказа №{order_id} истёк, товар вернулся в продажу. Если ещё нужно — напишите, отложим снова."
    assert ("999", f"Снят резерв (срок хранения истёк, товар вернулся на склад): №{order_id}.") in rt.tg.sent
    with db.new_session() as s:  # the next round finds nothing more to release
        assert holds.release_expired(s, rt, s.get(Business, b.id), deadline + timedelta(days=3)) == []


def test_delivery_orders_and_other_niches_are_never_released(engine, rt):
    b = pharmacy()
    delivery = reserve(b.id, mode="delivery", chat="h2")
    shop = pharmacy("shop", "butik")
    with db.new_session() as s:
        dress = s.exec(select(Service).where(Service.business_id == shop.id)).first()
    from .test_pharmacy import order as place

    out, _ = place(shop.id, [{"item_id": dress.id, "quantity": 1, "note": ""}], "pickup", "s-hold", chat="h3")
    later = NOW_UTC + timedelta(days=10)
    with db.new_session() as s:
        assert holds.release_expired(s, rt, s.get(Business, b.id), later) == []
        assert holds.release_expired(s, rt, s.get(Business, shop.id), later) == []
        assert s.get(Order, delivery).status == "new" and s.get(Order, out.order_id).status == "new"


def test_the_owners_test_chat_sees_it_and_staff_are_not_told_about_tests(engine, rt):
    from joop.agent.engine import handle_incoming
    from joop.agent.llm import AgentReply
    from joop.channels.base import IncomingMessage
    from joop.web.saas import TRY_CHAT_ID

    from .conftest import FakeLLM

    b = pharmacy()
    with_bot(b.id)
    para = item(b.id, "Парацетамол 500 мг, 20 таблеток")
    llm = FakeLLM([AgentReply("Отложила.", order={"lines": [{"item_id": para.id, "quantity": 7, "note": ""}], "mode": "pickup",
                                                  "address": "", "time": "", "name": "Владелец", "phone": "0555000111", "comment": ""})])
    with db.new_session() as s:
        out = handle_incoming(s, s.get(Business, b.id), IncomingMessage("console", TRY_CHAT_ID, "text", "Отложите, 0555 000 111", "", "t1"), lambda: llm, NOW_UTC)
        s.commit()
    sent_before = len(rt.tg.sent)
    with db.new_session() as s:
        assert holds.release_expired(s, rt, s.get(Business, b.id), NOW_UTC + timedelta(days=3)) == [out.order_id]
        s.commit()
        conv = s.exec(select(Conversation).where(Conversation.business_id == b.id, Conversation.chat_id == TRY_CHAT_ID)).one()
        texts = s.exec(select(Message.text).where(Message.conversation_id == conv.id, Message.role == "ai")).all()
    assert any("Срок хранения заказа" in t for t in texts)
    assert len(rt.tg.sent) == sent_before  # no message to Telegram, no staff note about a test
