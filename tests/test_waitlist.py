from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from joop import db
from joop.agent.engine import handle_incoming
from joop.agent.llm import AgentReply
from joop.channels.base import IncomingMessage
from joop.models import Booking, Business, Slot, Staff, WaitlistEntry
from joop.presets import create_business
from joop.timeutil import utc_to_local
from joop.web.app import create_app

from .conftest import NOW_UTC, FakeLLM
from .test_web import csrf_of, login

TOMORROW = utc_to_local(NOW_UTC, "Asia/Bishkek").date() + timedelta(days=1)


def say(business_id, text, llm, ext, chat="w1", when=NOW_UTC):
    with db.new_session() as s:
        b = s.get(Business, business_id)
        out = handle_incoming(s, b, IncomingMessage("telegram", chat, "text", text, "", ext), lambda: llm, when)
        s.commit()
        return out


def request(name, phone, when="завтра в 10:00"):
    return AgentReply("Записала заявку, администратор перезвонит.",
                      booking={"slot_id": None, "name": name, "phone": phone, "service": "чистка", "preferred_time": when, "party_size": 0})


@pytest.fixture
def client(settings, rt, business):
    with TestClient(create_app(settings, rt, init=False)) as c:
        yield c


def booked_slot(business_id, day, chat="other"):
    """A booking on `day` made by someone else, so it can be cancelled."""
    with db.new_session() as s:
        slot = s.exec(select(Slot).where(Slot.business_id == business_id, Slot.status == "free")
                      .order_by(Slot.start)).all()
        slot = next(x for x in slot if x.start.date() == day)
        slot.status, slot.taken = "booked", 1
        member = s.get(Staff, slot.staff_id)
        b = Booking(business_id=business_id, slot_id=slot.id, staff_id=member.id, staff_name=member.name, start=slot.start,
                    customer_name="Другой", customer_phone="0555999999", channel="telegram", chat_id=chat)
        s.add(slot)
        s.add(b)
        s.commit()
        return b.id, slot.start


def test_request_goes_to_waitlist_and_freed_slot_is_offered(client, business, rt):
    out = say(business.id, "Завтра в 10 можно? Если нет — запишите в лист ожидания. Айбек, 0555 123 456", FakeLLM([request("Айбек", "0555123456")]), "w1")
    assert out.request_id and out.reply.endswith("Если на этот день освободится время, я сразу напишу.")
    with db.new_session() as s:
        entry = s.exec(select(WaitlistEntry)).one()
        assert (entry.day, entry.status, entry.customer_name) == (TOMORROW, "waiting", "Айбек")

    other_day, _ = booked_slot(business.id, TOMORROW + timedelta(days=1), chat="x2")
    same_day, start = booked_slot(business.id, TOMORROW, chat="x1")
    token = login(client)
    client.post(f"/panel/bookings/{other_day}/cancel", data={"csrf": token})
    assert not rt.tg.sent  # a different day: nobody is told
    r = client.post(f"/panel/bookings/{same_day}/cancel", data={"csrf": token})
    assert "листа ожидания: 1" in r.text
    assert rt.tg.sent[-1][0] == "w1" and "освободилось время" in rt.tg.sent[-1][1] and start.strftime("%H:%M") in rt.tg.sent[-1][1]
    assert "время предложено" in client.get("/panel/bookings").text

    # The customer answers and the AI books as usual: the entry is closed.
    with db.new_session() as s:
        slot = s.exec(select(Slot).where(Slot.business_id == business.id, Slot.start == start, Slot.status == "free")).first()
    llm = FakeLLM([AgentReply("Записала.", booking={"slot_id": slot.id, "name": "Айбек", "phone": "0555123456", "service": "чистка", "preferred_time": "", "party_size": 0})])
    assert say(business.id, "Да, записывайте", llm, "w2").booking_id
    with db.new_session() as s:
        assert s.exec(select(WaitlistEntry)).one().status == "booked"


def test_kyrgyz_customer_and_reopened_slot(client, business, rt):
    out = say(business.id, "Эртең саат 10го жазып коюңузчу, атым Айгүл, 0700 111 222", FakeLLM([request("Айгүл", "0700111222", "")]), "k1", chat="k1")
    assert out.reply.endswith("Ошол күнү убакыт бошоп калса, дароо жазам.")
    with db.new_session() as s:
        slot = next(x for x in s.exec(select(Slot).where(Slot.business_id == business.id, Slot.status == "free")
                                      .order_by(Slot.start)).all() if x.start.date() == TOMORROW)
        slot.status = "booked"  # closed by staff
        s.add(slot)
        s.commit()
    token = login(client)
    client.post(f"/panel/slots/{slot.id}/toggle", data={"csrf": token})  # reopened
    assert rt.tg.sent[-1][0] == "k1" and "убакыт бошоду" in rt.tg.sent[-1][1]


def test_request_only_niches_have_no_waitlist(engine):
    with db.new_session() as s:
        b = create_business(s, slug="hotel", name="Гостевой дом", password="hotel-pass", niche="hotel", demo=True, now_utc=NOW_UTC)
        s.commit()
    out = say(b.id, "Номер на 10–12 июля, Алмаз, 0555 667 788", FakeLLM([request("Алмаз", "0555667788", "10–12 июля")]), "h1")
    assert out.request_id and "освободится" not in out.reply
    with db.new_session() as s:
        assert not s.exec(select(WaitlistEntry)).all()
