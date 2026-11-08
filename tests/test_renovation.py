"""Renovation and builders (joop/niches/renovation): prices «от» per m², a free measurement visit, a lead with budget."""

from fastapi.testclient import TestClient
from sqlmodel import select

from joop import db
from joop.agent.engine import handle_incoming
from joop.agent.llm import AgentReply
from joop.channels.base import IncomingMessage
from joop.models import Booking, Business, Slot, Staff
from joop.niches import get_pack
from joop.presets import create_business
from joop.web.app import create_app

from .conftest import NOW_UTC, FakeLLM
from .test_web import csrf_of


def company(niche="renovation", slug="remont"):
    with db.new_session() as s:
        b = create_business(s, slug=slug, name="Ремонт", password="remont-pass-1", niche=niche, demo=True, now_utc=NOW_UTC)
        b.example_ok = True  # its price list and measurers are its own
        s.commit()
        return b


def login(c, slug="remont"):
    token = csrf_of(c.get("/login").text)
    c.post("/login", data={"slug": slug, "password": "remont-pass-1", "csrf": token})


def test_measurement_visit_is_booked_with_the_address(engine):
    pack = get_pack("renovation")
    assert pack.has("booking") and pack.has("lead") and "площадь" in pack.lead_fields
    b = company()
    with db.new_session() as s:
        slot = s.exec(select(Slot).join(Staff).where(Staff.business_id == b.id, Staff.name == "Азамат").order_by(Slot.start)).first()
    llm = FakeLLM([AgentReply("Записала замерщика.", booking={
        "slot_id": slot.id, "name": "Нурлан", "phone": "0555778899", "service": "капитальный ремонт, 60 м², Ахунбаева 100",
        "preferred_time": "", "party_size": 0})])
    with db.new_session() as s:
        out = handle_incoming(s, s.get(Business, b.id), IncomingMessage("telegram", "r1", "text", "Замер завтра, Нурлан 0555 778 899", "", "r1"),
                              lambda: llm, NOW_UTC)
        s.commit()
        booking = s.get(Booking, out.booking_id)
    assert booking.service == "капитальный ремонт, 60 м², Ахунбаева 100" and booking.staff_name == "Азамат"
    system = llm.calls[0]["system"]
    assert "Итоговую стоимость ремонта не считай" in system and "- Ремонт под ключ (по-кыргызски: Ачкычка чейин оңдоо) — от 12 000 за м² (с дизайн-проектом; без материалов)" in system
    assert "что ремонтируем (квартира, дом, офис), площадь" in system


def test_panel_words_follow_the_niche(settings, rt, engine):
    b = company()
    company("hotel", "hotel")
    with db.new_session() as s:
        slot = s.exec(select(Slot).join(Staff).where(Staff.business_id == b.id).order_by(Slot.start)).first()
        s.add(Booking(business_id=b.id, slot_id=slot.id, staff_name="Азамат", start=slot.start, customer_name="Нурлан",
                      customer_phone="+996555778899", service="замер", channel="telegram", created_at=NOW_UTC))
        s.commit()
    with TestClient(create_app(settings, rt, init=False)) as c:
        login(c)
        slots = c.get("/panel/slots").text
        assert '<label for="g-staff">Замерщик' in slots and "Специалист" not in slots
        assert "<th>Замерщик</th>" in c.get("/panel/bookings").text
        page = c.get("/panel/menu").text
        assert "Ссылку ставьте в шапку Instagram, QR-код — на табличку и визитки." in page and "кнопка заказа" not in page
        c.get("/logout")
        login(c, "hotel")
        assert "кнопка вопроса в мессенджер" in c.get("/panel/menu").text  # a hotel's button asks, it does not order
