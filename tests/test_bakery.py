"""Cakes to order (joop/niches/bakery): sold by weight, the date in the order, the inscription in the comment."""

from sqlmodel import select

from joop import db
from joop.agent.engine import handle_incoming
from joop.agent.llm import AgentReply
from joop.channels.base import IncomingMessage
from joop.models import Business, Order, Service
from joop.niches import get_pack
from joop.presets import create_business

from .conftest import NOW_UTC, FakeLLM


def test_cake_by_weight_with_date_and_inscription(engine):
    assert get_pack("bakery").orders_first and get_pack("bakery").online_label == "Каталог онлайн"
    with db.new_session() as s:
        b = create_business(s, slug="tort", name="Торты", password="tort-pass-12", niche="bakery", demo=True, now_utc=NOW_UTC)
        b.example_ok = True  # its menu is its own
        s.commit()
        cake = s.exec(select(Service).where(Service.business_id == b.id, Service.name == "Торт «Красный бархат», за 1 кг")).one()
    llm = FakeLLM([AgentReply("Оформила, кондитер подтвердит.", order={
        "lines": [{"item_id": cake.id, "quantity": 3, "note": ""}], "mode": "pickup", "address": "",
        "time": "суббота 14.11, 15:00", "name": "Айгуль", "phone": "0555212323", "comment": "надпись «С днём рождения, Айым»"})])
    with db.new_session() as s:
        out = handle_incoming(s, s.get(Business, b.id), IncomingMessage("telegram", "c1", "text", "Красный бархат 3 кг. Айгуль, 0555 212 323",
                                                                        "", "c1"), lambda: llm, NOW_UTC)
        s.commit()
        order = s.get(Order, out.order_id)
    assert out.reply.endswith("Сумма заказа: 6 000 сом.") and order.total == 6000
    assert order.wanted_time == "суббота 14.11, 15:00" and order.comment == "надпись «С днём рождения, Айым»"
    assert "у позиции «за 1 кг» количество в заказе — это килограммы" in llm.calls[0]["system"]
