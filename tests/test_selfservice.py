"""A customer cancels or moves their own booking in the chat, and the AI does it (joop/selfservice.py)."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlmodel import select

from joop import db
from joop.agent.engine import handle_incoming
from joop.agent.llm import AgentReply, coerce_reply, response_schema
from joop.channels.base import IncomingMessage
from joop.dispatch import process_incoming
from joop.models import Booking, Business, Conversation, Lead, Slot, WaitlistEntry
from joop.timeutil import utc_to_local
from joop.web.app import create_app

from .conftest import NOW_UTC, FakeLLM
from .test_web import csrf_of, login

LOCAL = utc_to_local(NOW_UTC, "Asia/Bishkek")  # Wed 4 Nov 23:14
TOMORROW = LOCAL.date() + timedelta(days=1)


def say(business_id, text, llm, ext, chat="c1", channel="telegram"):
    with db.new_session() as s:
        b = s.get(Business, business_id)
        out = handle_incoming(s, b, IncomingMessage(channel, chat, "text", text, "", ext), lambda: llm, NOW_UTC)
        s.commit()
        return out


def tomorrow(business_id):
    with db.new_session() as s:
        return [x for x in s.exec(select(Slot).where(Slot.business_id == business_id, Slot.status == "free")
                                  .order_by(Slot.start, Slot.id)).all() if x.start.date() == TOMORROW]


def booked(business_id, chat="c1"):
    """The AI booked Айгуль for tomorrow's first time in chat `chat`."""
    slot = tomorrow(business_id)[0]
    reply = AgentReply("Записала вас.", booking={"slot_id": slot.id, "name": "Айгуль", "phone": "0555111222",
                                                 "service": "чистка", "preferred_time": "", "party_size": 0})
    out = say(business_id, "Запишите на завтра в 9, Айгуль, 0555 111 222", FakeLLM([reply]), f"b-{chat}", chat=chat)
    assert out.booking_id
    return out.booking_id, slot


def test_the_customer_moves_their_booking_and_the_ai_does_it(business):
    booking_id, old = booked(business.id)
    new = next(x for x in tomorrow(business.id) if x.start.hour == 15)
    llm = FakeLLM([AgentReply("Перенесла!", change={"booking_id": booking_id, "action": "move", "slot_id": new.id})])
    out = say(business.id, "Не успеваю к 9, можно на 15:00?", llm, "m1")
    system, schema = llm.calls[0]["system"], llm.calls[0]["schema"]
    assert f"- запись {booking_id}: " in system and "сделай это сам" in system and '"change"' in system
    assert "change" in schema["properties"]
    assert out.reply.startswith("Готово: перенесла вашу запись на") and "15:00" in out.reply  # code says what was done
    assert out.changed_booking_id == booking_id and out.freed_slot_ids == [old.id]
    assert any("Клиент сам перенёс запись через ИИ: Айгуль" in n for n in out.admin_notes)
    with db.new_session() as s:
        moved = s.get(Booking, booking_id)
        assert (moved.slot_id, moved.status, moved.start) == (new.id, "booked", new.start)
        assert s.get(Slot, old.id).status == "free" and s.get(Slot, new.id).status == "booked"
        assert len(s.exec(select(Booking).where(Booking.business_id == business.id)).all()) == 1  # moved, not re-booked


def test_the_customer_cancels_and_the_time_is_free_again(business):
    booking_id, old = booked(business.id)
    llm = FakeLLM([AgentReply("Отменила.", change={"booking_id": booking_id, "action": "cancel", "slot_id": None})])
    out = say(business.id, "Отмените, пожалуйста, мою запись, заболела", llm, "c1x")
    assert out.reply.startswith("Отменила вашу запись на") and out.freed_slot_ids == [old.id]
    assert any("Клиент сам отменил запись через ИИ" in n for n in out.admin_notes)
    with db.new_session() as s:
        assert s.get(Booking, booking_id).status == "cancelled" and s.get(Slot, old.id).status == "free"
    llm = FakeLLM([AgentReply("Хорошо")])
    say(business.id, "Спасибо", llm, "c1y")
    assert "Записи клиента из этого чата" not in llm.calls[0]["system"]  # nothing left to change
    assert "change" not in llm.calls[0]["schema"]["properties"]


def test_what_the_ai_does_not_change_goes_to_staff(business):
    booking_id, slot = booked(business.id)
    other_id, _ = booked(business.id, chat="c2")
    # someone else's booking (another chat): nothing changes, staff are told
    out = say(business.id, "Отмените запись", FakeLLM([AgentReply("Ок", change={"booking_id": other_id, "action": "cancel", "slot_id": None})]), "x1")
    assert out.reply == "Передала вашу просьбу администратору, он свяжется с вами." and out.changed_booking_id is None
    # a time that is taken: the customer picks another, no request for staff
    taken = say(business.id, "На 9 у другой врача?", FakeLLM([AgentReply("Ок", change={"booking_id": booking_id, "action": "move", "slot_id": slot.id})]), "x2")
    assert taken.reply.startswith("Это время уже недоступно") and taken.lead_id is None
    # a prepaid visit is not cancelled by the AI
    with db.new_session() as s:
        row = s.get(Booking, booking_id)
        row.deposit_due, row.deposit_status = 500, "paid"
        s.add(row)
        s.commit()
    prepaid = say(business.id, "Отмените", FakeLLM([AgentReply("Ок", change={"booking_id": booking_id, "action": "cancel", "slot_id": None})]), "x3")
    assert prepaid.lead_id and prepaid.changed_booking_id is None
    with db.new_session() as s:
        assert "получена предоплата" in s.get(Lead, prepaid.lead_id).summary
        assert s.get(Booking, booking_id).status == "booked" and s.get(Booking, other_id).status == "booked"
        # a visit in less than two hours goes to staff
        row = s.get(Booking, booking_id)
        row.deposit_status, row.start, row.external_id = "", LOCAL + timedelta(minutes=90), ""
        s.add(row)
        s.commit()
    soon = say(business.id, "Отмените", FakeLLM([AgentReply("Ок", change={"booking_id": booking_id, "action": "cancel", "slot_id": None})]), "x4")
    with db.new_session() as s:
        assert "меньше двух часов" in s.get(Lead, soon.lead_id).summary and s.get(Booking, booking_id).status == "booked"


def test_a_business_that_turned_it_off_and_a_kyrgyz_customer(business):
    booking_id, old = booked(business.id)
    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.self_service = False
        s.add(b)
        s.commit()
    llm = FakeLLM([AgentReply("Передам администратору.", handoff="перенос", change={"booking_id": booking_id, "action": "cancel", "slot_id": None})])
    out = say(business.id, "Отмените запись", llm, "k1")
    assert "Записи клиента" not in llm.calls[0]["system"] and "change" not in llm.calls[0]["schema"]["properties"]
    assert out.changed_booking_id is None and out.lead_id  # as before: staff do it
    with db.new_session() as s:
        assert s.get(Booking, booking_id).status == "booked"
        b = s.get(Business, business.id)
        b.self_service = True
        s.add(b)
        s.commit()
    new = next(x for x in tomorrow(business.id) if x.start.hour == 16)
    ky = say(business.id, "Саат 16га жылдырып коюңузчу", FakeLLM([AgentReply("Макул", change={"booking_id": booking_id, "action": "move", "slot_id": new.id})]), "k2")
    assert ky.reply.startswith("Даяр: жазылууңузду") and "16:00" in ky.reply


def test_the_freed_time_is_offered_to_the_waiting_list_on_delivery(business, rt):
    booking_id, old = booked(business.id)
    with db.new_session() as s:
        conv = Conversation(business_id=business.id, channel="telegram", chat_id="w1", customer_name="Айбек")
        s.add(conv)
        s.flush()
        s.add(WaitlistEntry(business_id=business.id, conversation_id=conv.id, customer_name="Айбек", channel="telegram",
                            chat_id="w1", day=TOMORROW, service="чистка"))
        s.commit()
    rt.get_llm().replies = [AgentReply("Ок", change={"booking_id": booking_id, "action": "cancel", "slot_id": None})]
    out = process_incoming(rt, business.id, IncomingMessage("telegram", "c1", "text", "Отмените мою запись", "", "d1"), NOW_UTC)
    assert out.freed_slot_ids == [old.id]
    sent = dict((chat, text) for chat, text, *_ in rt.tg.sent)
    assert sent["c1"].startswith("Отменила вашу запись")
    assert "освободилось время" in sent["w1"] and old.start.strftime("%H:%M") in sent["w1"]


def test_the_change_field_is_read_and_offered_only_with_a_booking():
    assert coerce_reply({"reply": "Ок", "change": {"booking_id": "12", "action": "move", "slot_id": "40"}}).change == \
        {"booking_id": 12, "action": "move", "slot_id": 40}
    assert coerce_reply({"reply": "Ок", "change": {"booking_id": 12, "action": "delete", "slot_id": None}}).change is None
    assert coerce_reply({"reply": "Ок", "change": {"booking_id": 0, "action": "cancel"}}).change is None
    assert "change" not in response_schema({"booking"})["properties"]
    assert response_schema({"booking"}, change=True)["properties"]["change"]["anyOf"][1]["properties"]["action"]["enum"] == ["cancel", "move"]


def test_the_owner_turns_it_off_in_the_settings(settings, rt, business):
    with TestClient(create_app(settings, rt, init=False)) as c:
        login(c)
        page = c.get("/panel/settings").text
        assert 'name="self_service"' in page and "checked" in page.split('name="self_service"')[1][:40]
        form = {k: v for k, v in _form_values(page).items() if k != "self_service"}
        c.post("/panel/settings", data=form)
        with db.new_session() as s:
            assert s.get(Business, business.id).self_service is False
        c.post("/panel/settings", data={**form, "self_service": "1"})
        with db.new_session() as s:
            assert s.get(Business, business.id).self_service is True


def _form_values(page: str) -> dict:
    import re

    out = {"csrf": csrf_of(page)}
    form = page[page.index('action="/panel/settings"'):]
    form = form[:form.index("</form>")]
    for name, value in re.findall(r'<input[^>]*name="([^"]+)"[^>]*value="([^"]*)"', form):
        out.setdefault(name, value)
    for name in re.findall(r'<input[^>]*type="checkbox"[^>]*name="([^"]+)"[^>]*checked', form):
        out[name] = "1"
    for name, body in re.findall(r'<textarea[^>]*name="([^"]+)"[^>]*>(.*?)</textarea>', form, re.S):
        out[name] = body
    for name, body in re.findall(r'<select[^>]*name="([^"]+)"[^>]*>(.*?)</select>', form, re.S):
        chosen = re.search(r'<option value="([^"]*)" selected', body) or re.search(r'<option value="([^"]*)"', body)
        out[name] = chosen.group(1) if chosen else ""
    return out
