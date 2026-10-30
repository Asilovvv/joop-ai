from datetime import timedelta

from sqlmodel import select

from joop import db
from joop.agent.engine import handle_incoming
from joop.agent.llm import AgentReply
from joop.channels.base import IncomingMessage
from joop.models import Booking, Business, Slot, Staff
from joop.presets import create_business
from joop.slots import claim_slot, generate_slots, release_slot, resize_group
from joop.timeutil import utc_to_local

from .conftest import NOW_UTC, FakeLLM


def gym():
    with db.new_session() as s:
        b = create_business(s, slug="gym", name="Фитнес", password="gym-pass-1", niche="fitness", demo=True, now_utc=NOW_UTC)
        s.commit()
        yoga = s.exec(select(Staff).where(Staff.business_id == b.id, Staff.name == "Групповая йога")).one()
        slot = s.exec(select(Slot).where(Slot.staff_id == yoga.id).order_by(Slot.start)).first()
        return b, yoga, slot


def say(business_id, text, llm, ext, chat="g1"):
    with db.new_session() as s:
        b = s.get(Business, business_id)
        out = handle_incoming(s, b, IncomingMessage("telegram", chat, "text", text, "", ext), lambda: llm, NOW_UTC)
        s.commit()
        return out


def test_group_slots_take_several_bookings(engine):
    b, yoga, slot = gym()
    assert slot.seats == 12 and slot.taken == 0
    with db.new_session() as s:
        assert claim_slot(s, slot.id, 10) and not claim_slot(s, slot.id, 3)
        assert claim_slot(s, slot.id, 2)
        s.commit()
        row = s.get(Slot, slot.id)
        assert (row.taken, row.status) == (12, "booked")
        release_slot(s, slot.id, 2)
        s.commit()
        s.refresh(row)
        assert (row.taken, row.status) == (10, "free")


def test_one_seat_slots_work_as_before(engine, business):
    with db.new_session() as s:
        slot = s.exec(select(Slot).where(Slot.business_id == business.id)).first()
        assert slot.seats == 1
        assert claim_slot(s, slot.id, 3) is False  # a doctor's slot is never split
        assert claim_slot(s, slot.id) and not claim_slot(s, slot.id)
        s.commit()


def test_ai_books_group_class_and_respects_seats(engine):
    b, yoga, slot = gym()
    with db.new_session() as s:
        row = s.get(Slot, slot.id)
        row.seats = 3
        s.add(row)
        s.commit()
    data = lambda n, name, phone: {"slot_id": slot.id, "name": name, "phone": phone, "service": "йога", "preferred_time": "", "party_size": n}  # noqa: E731
    llm = FakeLLM([AgentReply("Записала вас двоих на йогу.", booking=data(2, "Сауле", "0555171819"))])
    out = say(b.id, "Запишите двоих на йогу", llm, "y1")
    assert out.booking_id
    assert "групповое занятие: свободно мест 3 из 3" in llm.calls[0]["system"]
    llm2 = FakeLLM([AgentReply("Записала вас двоих.", booking=data(2, "Айдай", "0555000111"))])
    out = say(b.id, "Нас тоже двое на это же время", llm2, "y2", chat="g2")
    assert out.booking_id is None and "осталось мест: 1" in out.reply
    llm3 = FakeLLM([AgentReply("Записала вас.", booking=data(1, "Нурай", "0555000222"))])
    assert say(b.id, "Запишите одну меня", llm3, "y3", chat="g3").booking_id
    with db.new_session() as s:
        row = s.get(Slot, slot.id)
        assert (row.taken, row.status) == (3, "booked")
        assert len(s.exec(select(Booking).where(Booking.slot_id == slot.id)).all()) == 2


def test_cancel_frees_the_right_number_of_seats(engine, settings, rt):
    from fastapi.testclient import TestClient

    from joop.web.app import create_app

    from .test_web import csrf_of

    b, yoga, slot = gym()
    llm = FakeLLM([AgentReply("Записала.", booking={"slot_id": slot.id, "name": "Сауле", "phone": "0555171819", "service": "йога", "preferred_time": "", "party_size": 2})])
    out = say(b.id, "Двоих на йогу", llm, "c1")
    with TestClient(create_app(settings, rt, init=False)) as c:
        token = csrf_of(c.get("/login").text)
        c.post("/login", data={"slug": "gym", "password": "gym-pass-1", "csrf": token})
        token = csrf_of(c.get("/panel/bookings").text)
        c.post(f"/panel/bookings/{out.booking_id}/cancel", data={"csrf": token})
        assert "0/12" in c.get("/panel/slots").text or "· 0/12" in c.get("/panel/slots").text
    with db.new_session() as s:
        assert s.get(Slot, slot.id).taken == 0


def test_changing_group_size_updates_future_slots(engine):
    b, yoga, slot = gym()
    now_local = utc_to_local(NOW_UTC, b.timezone)
    with db.new_session() as s:
        row = s.get(Slot, slot.id)
        row.taken = 5
        s.add(row)
        s.flush()
        assert resize_group(s, yoga.id, 4, now_local) > 0
        s.commit()
        row = s.get(Slot, slot.id)
        assert (row.seats, row.status) == (5, "booked")  # never fewer seats than already booked
        other = s.exec(select(Slot).where(Slot.staff_id == yoga.id, Slot.id != slot.id)).first()
        assert other.seats == 4
        tr = s.exec(select(Staff).where(Staff.business_id == b.id, Staff.name == "Тренер Азамат")).one()
        n = generate_slots(s, s.get(Business, b.id), tr.id, now_local.date() + timedelta(days=20),
                           now_local.date() + timedelta(days=20), now_local.time().replace(hour=8, minute=0),
                           now_local.time().replace(hour=10, minute=0), 60)
        s.commit()
        assert n == 2 and all(x.seats == 1 for x in s.exec(select(Slot).where(Slot.staff_id == tr.id)).all())
