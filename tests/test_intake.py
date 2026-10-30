from datetime import timedelta

from fastapi.testclient import TestClient
from sqlmodel import select

from joop import db
from joop.agent.engine import handle_incoming
from joop.agent.llm import AgentReply
from joop.channels.base import IncomingMessage
from joop.models import Booking, Business, Slot
from joop.web.app import create_app

from .conftest import NOW_UTC, FakeLLM, first_free_slot
from .test_web import csrf_of, login


def setup(business_id, **values):
    with db.new_session() as s:
        b = s.get(Business, business_id)
        for k, v in values.items():
            setattr(b, k, v)
        s.add(b)
        s.commit()


def say(business_id, text, llm, ext, chat="i1", when=NOW_UTC):
    with db.new_session() as s:
        out = handle_incoming(s, s.get(Business, business_id), IncomingMessage("telegram", chat, "text", text, "", ext), lambda: llm, when)
        s.commit()
        return out


def book(slot_id, name="Айбек", phone="0555123456"):
    return AgentReply("Вы записаны.", booking={"slot_id": slot_id, "name": name, "phone": phone, "service": "осмотр", "preferred_time": "", "party_size": 0})


def test_questions_after_booking_and_answers_saved(business):
    setup(business.id, intake_questions="Что беспокоит?\nКогда последний раз были у стоматолога?")
    slot = first_free_slot(business.id)
    out = say(business.id, "Айбек, 0555 123 456, запишите", FakeLLM([book(slot.id)]), "i1")
    assert out.booking_id and out.reply.endswith("ответьте, пожалуйста, одним сообщением:\n1. Что беспокоит?\n2. Когда последний раз были у стоматолога?")
    llm = FakeLLM()
    out = say(business.id, "Болит нижний зуб слева, был год назад. А парковка есть?", llm, "i2")
    assert "Ответы перед визитом: Айбек" in out.admin_notes[0] and "Болит нижний зуб" in out.admin_notes[0]
    assert "только что ответил на вопросы" in llm.calls[0]["system"]  # the message still goes to the AI
    with db.new_session() as s:
        b = s.exec(select(Booking).where(Booking.business_id == business.id, Booking.chat_id == "i1")).one()
        assert b.intake_status == "answered" and b.intake_answers.startswith("Болит")
    out = say(business.id, "Спасибо", FakeLLM(), "i3")
    assert not out.admin_notes  # answers are taken once


def test_no_questions_configured(business):
    slot = first_free_slot(business.id)
    out = say(business.id, "Айбек, 0555 123 456", FakeLLM([book(slot.id)]), "i4")
    assert out.reply == "Вы записаны."


def test_every_third_visit_gets_the_reward(business):
    setup(business.id, loyalty_every=3, loyalty_reward="скидка 20%")
    with db.new_session() as s:
        slots = s.exec(select(Slot).where(Slot.business_id == business.id, Slot.status == "free").order_by(Slot.start)).all()
        for slot in slots[:2]:  # two earlier visits by the same phone
            s.add(Booking(business_id=business.id, start=slot.start - timedelta(days=30), customer_phone="+996555123456"))
        s.commit()
        target = slots[5]
    out = say(business.id, "Айбек, 0555 123 456", FakeLLM([book(target.id)]), "i5", chat="i5")
    assert out.reply.endswith("Это будет ваш 3-й визит — скидка 20%.")
    assert any("3-й визит" in n for n in out.admin_notes)
    out = say(business.id, "Айгуль, 0700 000 111", FakeLLM([book(slots[6].id, "Айгуль", "0700000111")]), "i6", chat="i6")
    assert "визит —" not in out.reply


def test_panel_saves_and_shows(settings, rt, business):
    with TestClient(create_app(settings, rt, init=False)) as c:
        token = login(c)
        c.post("/panel/followups", data={"intake_questions": "Что беспокоит?\n\n  Аллергия на лекарства?  ", "loyalty_every": "5",
                                         "loyalty_reward": "чистка бесплатно", "csrf": token})
        with db.new_session() as s:
            b = s.get(Business, business.id)
            assert b.intake_questions == "Что беспокоит?\nАллергия на лекарства?" and b.loyalty_every == 5
        assert "Вопросы перед визитом" in c.get("/panel/followups").text
