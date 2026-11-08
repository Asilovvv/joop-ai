"""Medical laboratories (joop/niches/lab): prices and preparation, a home visit booking, no reading of results."""

from sqlmodel import select

from joop import db
from joop.agent.engine import handle_incoming
from joop.agent.llm import AgentReply
from joop.channels.base import IncomingMessage
from joop.models import Booking, Business, Slot, Staff
from joop.presets import create_business

from .conftest import NOW_UTC, FakeLLM


def test_home_visit_is_booked_with_tests_and_address(engine):
    with db.new_session() as s:
        b = create_business(s, slug="lab", name="Лаборатория", password="lab-pass-123", niche="lab", demo=True, now_utc=NOW_UTC)
        b.example_ok = True  # its price list is its own
        s.commit()
        slot = s.exec(select(Slot).join(Staff).where(Staff.business_id == b.id, Staff.name == "Выездная медсестра")
                      .order_by(Slot.start)).first()
    llm = FakeLLM([AgentReply("Записала выезд медсестры.", booking={
        "slot_id": slot.id, "name": "Айжан", "phone": "0555616717", "service": "ОАК и глюкоза, Джал 15, кв. 7",
        "preferred_time": "", "party_size": 0})])
    with db.new_session() as s:
        out = handle_incoming(s, s.get(Business, b.id), IncomingMessage("telegram", "l1", "text", "Выезд. Айжан, 0555 616 717", "", "l1"),
                              lambda: llm, NOW_UTC)
        s.commit()
        booking = s.get(Booking, out.booking_id)
    assert booking.staff_name == "Выездная медсестра" and booking.service == "ОАК и глюкоза, Джал 15, кв. 7"
    system = llm.calls[0]["system"]
    assert "Не расшифровывай результаты, не ставь диагнозы" in system
    assert "- Общий анализ крови (ОАК) (по-кыргызски: Кандын жалпы анализи) — 450 (готов на следующий день; натощак)" in system
