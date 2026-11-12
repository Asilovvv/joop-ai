"""Drinking water delivery (joop/niches/water): «как обычно» repeats the last order, the code still checks it."""

from datetime import timedelta

from sqlmodel import select

from joop import db, repeat_order
from joop.agent.engine import handle_incoming
from joop.agent.llm import AgentReply
from joop.channels.base import IncomingMessage
from joop.models import Business, Conversation, Order, OrderLine, Service
from joop.niches import get_pack
from joop.presets import create_business

from .conftest import NOW_UTC, FakeLLM


def company(niche="water", slug="suu"):
    with db.new_session() as s:
        b = create_business(s, slug=slug, name="Суу", password="suu-pass-123", niche=niche, demo=True, now_utc=NOW_UTC)
        b.example_ok = True  # its catalog is its own
        s.commit()
        return b


def item(business_id, name):
    with db.new_session() as s:
        return s.exec(select(Service).where(Service.business_id == business_id, Service.name == name)).one()


def say(business_id, text, llm, ext, chat="w1", now=NOW_UTC):
    with db.new_session() as s:
        out = handle_incoming(s, s.get(Business, business_id), IncomingMessage("telegram", chat, "text", text, "", ext), lambda: llm, now)
        s.commit()
        return out


def first_order(business_id, chat="w1", name="Айгуль", phone="0555909090"):
    water, deposit = item(business_id, "Вода питьевая, бутыль 19 л"), item(business_id, "Залог за бутыль 19 л")
    llm = FakeLLM([AgentReply("Оформила.", order={
        "lines": [{"item_id": water.id, "quantity": 2, "note": ""}, {"item_id": deposit.id, "quantity": 2, "note": ""}],
        "mode": "delivery", "address": "Джал 23, кв. 15", "time": "завтра утром", "name": name, "phone": phone, "comment": "4 этаж"})])
    out = say(business_id, f"2 бутыля, Джал 23, кв. 15. {name}, {phone}", llm, f"first-{chat}", chat=chat)
    assert out.order_id
    return out.order_id


def test_the_last_order_comes_back_with_catalog_numbers(engine):
    pack = get_pack("water")
    assert pack.offers("repeat_order") and pack.has("order") and pack.order_modes == ("delivery",)
    b = company()
    order_id = first_order(b.id)
    with db.new_session() as s:
        assert s.get(Order, order_id).total == 2 * 180 + 2 * 400  # the code adds up the catalog prices
    water = item(b.id, "Вода питьевая, бутыль 19 л")
    later = NOW_UTC + timedelta(days=40)  # past the 30 days «где мой заказ» looks at, well inside 180
    llm = FakeLLM([AgentReply("Как обычно: 2 бутыля на Джал 23?")])
    say(b.id, "Как обычно", llm, "again", now=later)
    system = llm.calls[0]["system"]
    assert f"Прошлый заказ этого клиента №{order_id} от 04.11 (данные из системы):" in system
    assert f"[{water.id}] Вода питьевая, бутыль 19 л × 2" in system and "доставка: Джал 23, кв. 15" in system
    assert "новую сумму считает система" in system and "добавь в заказ залог за бутыль" in system


def test_same_phone_and_name_in_another_chat_but_not_a_strangers(engine):
    b = company()
    first_order(b.id)
    llm = FakeLLM([AgentReply("Повторим?"), AgentReply("Уточните заказ.")])
    with db.new_session() as s:
        for chat, name in (("wa-1", "Айгуль"), ("wa-2", "Марат")):
            s.add(Conversation(business_id=b.id, channel="telegram", chat_id=chat, customer_phone="+996555909090",
                               customer_name=name, created_at=NOW_UTC))
        s.commit()
    say(b.id, "Привет, как обычно", llm, "x1", chat="wa-1")
    say(b.id, "Как у Айгуль, на её адрес", llm, "x2", chat="wa-2")  # her number, another name
    mine, stranger = llm.calls[0]["system"], llm.calls[1]["system"]
    assert "Прошлый заказ этого клиента" in mine and "Прошлый заказ этого клиента" not in stranger
    assert "Джал 23" not in stranger


def test_items_off_sale_are_named_not_offered_and_old_orders_are_forgotten(engine):
    b = company()
    first_order(b.id)
    with db.new_session() as s:
        deposit = s.exec(select(Service).where(Service.business_id == b.id, Service.name == "Залог за бутыль 19 л")).one()
        deposit.available = False
        s.add(deposit)
        s.commit()
        conv = s.exec(select(Conversation).where(Conversation.business_id == b.id)).one()
        hint = repeat_order.prompt_hint(s, s.get(Business, b.id), conv, NOW_UTC)
        assert "- не повторять: Залог за бутыль 19 л (сейчас нет в наличии)" in hint
        assert "Залог за бутыль 19 л ×" not in hint
        assert repeat_order.prompt_hint(s, s.get(Business, b.id), conv, NOW_UTC + timedelta(days=181)) == ""
        order = s.exec(select(Order).where(Order.business_id == b.id)).one()
        order.status = "cancelled"
        s.add(order)
        s.commit()
        assert repeat_order.prompt_hint(s, s.get(Business, b.id), conv, NOW_UTC) == ""


def test_other_order_niches_do_not_get_it(engine):
    b = company("florist", "gul")
    rose = item(b.id, "Букет из 15 красных роз")
    llm = FakeLLM([AgentReply("Оформила.", order={"lines": [{"item_id": rose.id, "quantity": 1, "note": ""}], "mode": "pickup",
                                                  "address": "", "time": "", "name": "Асель", "phone": "0555112233", "comment": ""}),
                   AgentReply("Какой букет?")])
    say(b.id, "15 роз, заберу сама. Асель 0555 112 233", llm, "f1")
    say(b.id, "Как в прошлый раз", llm, "f2")
    assert "Прошлый заказ этого клиента" not in llm.calls[1]["system"]
