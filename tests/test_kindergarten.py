"""Private kindergartens (joop/niches/kindergarten): places by group, a tour for parents, a waitlist lead."""

from sqlmodel import select

from joop import db
from joop.agent.engine import handle_incoming
from joop.agent.llm import AgentReply
from joop.channels.base import IncomingMessage
from joop.models import Booking, Business, Lead, Slot, Staff
from joop.presets import create_business

from .conftest import NOW_UTC, FakeLLM


def kindergarten():
    with db.new_session() as s:
        b = create_business(s, slug="sad", name="Сад", password="sad-pass-123", niche="kindergarten", demo=True, now_utc=NOW_UTC)
        b.example_ok = True  # its groups and tours are its own
        s.commit()
        return b


def say(business_id, text, reply, ext):
    llm = FakeLLM([reply])
    with db.new_session() as s:
        out = handle_incoming(s, s.get(Business, business_id), IncomingMessage("telegram", ext, "text", text, "", ext), lambda: llm, NOW_UTC)
        s.commit()
    return out, llm.calls[0]["system"]


def test_tour_booking_and_waitlist_lead(engine):
    b = kindergarten()
    with db.new_session() as s:
        slot = s.exec(select(Slot).join(Staff).where(Staff.business_id == b.id).order_by(Slot.start)).first()
    tour = AgentReply("Записала на экскурсию.", booking={"slot_id": slot.id, "name": "Алия", "phone": "0555404505",
                                                         "service": "экскурсия, ребёнку 4 года, старшая группа",
                                                         "preferred_time": "", "party_size": 0})
    out, system = say(b.id, "Экскурсия завтра вечером, ребёнку 4 года. Алия, 0555 404 505", tour, "k1")
    assert "- Ясельная группа (1,5–2,5 года) (по-кыргызски: Наристелер тобу (1,5–2,5 жаш)) — 20 000 в месяц (свободных мест нет)" in system
    assert "О здоровье ребёнка, диагнозах и особых потребностях не расспрашивай" in system
    with db.new_session() as s:
        assert s.get(Booking, out.booking_id).service == "экскурсия, ребёнку 4 года, старшая группа"
    waitlist = AgentReply("Записала в лист ожидания, заведующая свяжется.", lead={
        "name": "Камила", "phone": "0555818919",
        "details": "возраст ребёнка — 2 года; с какого месяца нужен сад — сентябрь; полный или неполный день — полный; район — Джал"})
    out, _ = say(b.id, "Сыну 2 года, с сентября, полный день, Джал. Камила, 0555 818 919", waitlist, "k2")
    with db.new_session() as s:
        lead = s.exec(select(Lead).where(Lead.business_id == b.id, Lead.kind == "lead")).one()
    assert "возраст ребёнка — 2 года" in lead.details and "сентябрь" in lead.details
