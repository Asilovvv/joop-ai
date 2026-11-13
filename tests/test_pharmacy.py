"""Pharmacies (joop/niches/pharmacy): prescription medicines are reserved for pickup only, decided by code."""

from sqlmodel import select

from joop import db, prescription
from joop.agent.engine import handle_incoming
from joop.agent.llm import AgentReply
from joop.channels.base import IncomingMessage
from joop.models import Business, Order, Service
from joop.niches import get_pack
from joop.presets import create_business

from .conftest import NOW_UTC, FakeLLM


def pharmacy(niche="pharmacy", slug="dary"):
    with db.new_session() as s:
        b = create_business(s, slug=slug, name="Дары", password="dary-pass-123", niche=niche, demo=True, now_utc=NOW_UTC)
        b.example_ok = True  # its catalog is its own
        s.commit()
        return b


def item(business_id, name):
    with db.new_session() as s:
        return s.exec(select(Service).where(Service.business_id == business_id, Service.name == name)).one()


def order(business_id, lines, mode, ext, chat="p1"):
    llm = FakeLLM([AgentReply("Оформила.", order={"lines": lines, "mode": mode, "address": "Ахунбаева 100" if mode == "delivery" else "",
                                                  "time": "", "name": "Марат", "phone": "0555565656", "comment": ""})])
    with db.new_session() as s:
        out = handle_incoming(s, s.get(Business, business_id), IncomingMessage("telegram", chat, "text", "Марат 0555 565 656", "", ext),
                              lambda: llm, NOW_UTC)
        s.commit()
    return out, llm


def test_a_prescription_medicine_is_not_delivered(engine):
    assert get_pack("pharmacy").offers("prescription")
    b = pharmacy()
    amox, para = item(b.id, "Амоксициллин 500 мг, 16 капсул"), item(b.id, "Парацетамол 500 мг, 20 таблеток")
    assert prescription.is_rx(amox) and not prescription.is_rx(para)
    out, _ = order(b.id, [{"item_id": amox.id, "quantity": 1, "note": ""}, {"item_id": para.id, "quantity": 10, "note": ""}], "delivery", "d1")
    assert out.order_id is None
    assert out.reply.startswith("«Амоксициллин 500 мг, 16 капсул» отпускается только по рецепту в аптеке: доставить не можем.")


def test_a_pickup_reservation_reminds_about_the_prescription(engine):
    b = pharmacy()
    amox = item(b.id, "Амоксициллин 500 мг, 16 капсул")
    out, llm = order(b.id, [{"item_id": amox.id, "quantity": 1, "note": ""}], "pickup", "p1")
    assert out.order_id and out.reply.endswith("При получении покажите рецепт на: Амоксициллин 500 мг, 16 капсул.")
    with db.new_session() as s:
        assert "покажите рецепт" in s.get(Order, out.order_id).comment  # the staff see it in the order
    system = llm.calls[0]["system"]
    assert "не называй дозировки" in system and "скорую по номеру 103" in system


def test_over_the_counter_items_are_delivered_and_other_niches_unaffected(engine):
    b = pharmacy()
    para = item(b.id, "Парацетамол 500 мг, 20 таблеток")
    out, _ = order(b.id, [{"item_id": para.id, "quantity": 10, "note": ""}], "delivery", "o1")
    assert out.order_id and "рецепт" not in out.reply
    shop = pharmacy("shop", "butik")
    with db.new_session() as s:
        dress = s.exec(select(Service).where(Service.business_id == shop.id)).first()
        dress.note = "по рецепту"  # the word means nothing outside a pharmacy pack
        s.add(dress)
        s.commit()
    out, _ = order(shop.id, [{"item_id": dress.id, "quantity": 1, "note": ""}], "delivery", "s1")
    assert out.order_id
