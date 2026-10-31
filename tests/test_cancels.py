"""A customer cancels or moves their own booking in the chat (joop/cancels.py)."""

from datetime import timedelta

from sqlmodel import select

from joop import db
from joop.agent.engine import handle_incoming
from joop.agent.llm import AgentReply
from joop.cancels import EXTERNAL_REPLY, NOT_FOUND_REPLY
from joop.channels.base import IncomingMessage
from joop.dispatch import process_incoming
from joop.models import Booking, Business, Conversation, Lead, Slot, WaitlistEntry

from .conftest import NOW_UTC, FakeLLM, first_free_slot

NAME, PHONE = "Айбек", "0555123456"


def say(business_id, text, llm, ext, chat="c1", when=NOW_UTC):
    with db.new_session() as s:
        b = s.get(Business, business_id)
        out = handle_incoming(s, b, IncomingMessage("telegram", chat, "text", text, NAME, ext), lambda: llm, when)
        s.commit()
        return out


def book(business_id, slot_id, ext="b1", chat="c1"):
    llm = FakeLLM([AgentReply("Записала!", booking={"slot_id": slot_id, "name": NAME, "phone": PHONE, "service": "осмотр"})])
    out = say(business_id, f"Запишите, {NAME}, {PHONE}", llm, ext, chat)
    assert out.booking_id
    return out.booking_id


def free_slots(business_id):
    with db.new_session() as s:
        return s.exec(select(Slot).where(Slot.business_id == business_id, Slot.status == "free").order_by(Slot.start)).all()


def test_prompt_lists_the_customers_upcoming_bookings(business):
    bid = book(business.id, first_free_slot(business.id).id)
    llm = FakeLLM([AgentReply("Какую запись отменить?")])
    say(business.id, "Хочу отменить запись", llm, "q1")
    system = llm.calls[0]["system"]
    assert "Предстоящие записи клиента (номер записи" in system and f"- {bid}: " in system
    assert '"cancel": null или номер записи' in system
    assert "cancel" in llm.calls[0]["schema"]["properties"]
    # Another customer's chat does not see this booking.
    other = FakeLLM([AgentReply("Здравствуйте!")])
    say(business.id, "Здравствуйте", other, "o1", chat="c2")
    assert "Предстоящие записи клиента (номер записи" not in other.calls[0]["system"]


def test_customer_cancels_and_the_time_is_free_again(business):
    slot = first_free_slot(business.id)
    bid = book(business.id, slot.id)
    out = say(business.id, "Жазылууну жокко чыгарыңызчы", FakeLLM([AgentReply("Жазылууңуз жокко чыгарылды.", cancel=bid)]), "x1")
    assert out.cancelled_id == bid and out.freed_slot_id == slot.id and out.reply == "Жазылууңуз жокко чыгарылды."
    assert any("Клиент отменил запись в чате" in n for n in out.admin_notes)
    with db.new_session() as s:
        assert s.get(Booking, bid).status == "cancelled"
        assert (s.get(Slot, slot.id).status, s.get(Slot, slot.id).taken) == ("free", 0)


def test_code_refuses_a_booking_that_is_not_this_customers(business):
    theirs = book(business.id, first_free_slot(business.id).id, ext="t1", chat="other")
    out = say(business.id, "Отмените запись", FakeLLM([AgentReply("Отменила.", cancel=theirs)]), "x2")
    assert out.cancelled_id is None and out.reply == NOT_FOUND_REPLY and out.lead_id is not None
    with db.new_session() as s:
        assert s.get(Booking, theirs).status == "booked"
        assert s.get(Lead, out.lead_id).kind == "handoff"


def test_past_or_unknown_bookings_are_not_cancelled(business):
    slot = first_free_slot(business.id)
    bid = book(business.id, slot.id)
    out = say(business.id, "Отмените", FakeLLM([AgentReply("Отменила.", cancel=bid)]), "x3", when=NOW_UTC + timedelta(days=30))
    assert out.cancelled_id is None and out.reply == NOT_FOUND_REPLY
    out = say(business.id, "Отмените", FakeLLM([AgentReply("Отменила.", cancel=99999)]), "x4")
    assert out.cancelled_id is None


def test_move_cancels_the_old_booking_only_when_the_new_one_is_made(business):
    first, second, third = free_slots(business.id)[:3]
    old = book(business.id, first.id)
    # The new time is taken by someone else first: the old booking must stay.
    book(business.id, second.id, ext="z1", chat="someone")
    move = AgentReply("Перенесла.", booking={"slot_id": second.id, "name": NAME, "phone": PHONE, "service": "осмотр"}, cancel=old)
    out = say(business.id, "Перенесите на другое время", FakeLLM([move]), "m1")
    assert out.booking_id is None and out.cancelled_id is None and "занято" in out.reply
    with db.new_session() as s:
        assert s.get(Booking, old).status == "booked"
    move = AgentReply("Перенесла.", booking={"slot_id": third.id, "name": NAME, "phone": PHONE, "service": "осмотр"}, cancel=old)
    out = say(business.id, "Тогда на это время", FakeLLM([move]), "m2")
    assert out.booking_id and out.cancelled_id == old and out.reply == "Перенесла."
    with db.new_session() as s:
        assert s.get(Booking, old).status == "cancelled" and s.get(Slot, first.id).status == "free"


def test_booking_in_altegio_goes_to_staff_instead(business):
    bid = book(business.id, first_free_slot(business.id).id)
    with db.new_session() as s:
        b = s.get(Booking, bid)
        b.external_id = "987654"
        s.add(b)
        s.commit()
    out = say(business.id, "Отмените запись", FakeLLM([AgentReply("Отменила.", cancel=bid)]), "a1")
    assert out.cancelled_id is None and out.reply == EXTERNAL_REPLY
    with db.new_session() as s:
        assert s.get(Booking, bid).status == "booked"  # closed by the Altegio sync once staff cancel it there
        assert "987654" in s.get(Lead, out.lead_id).summary


def test_dispatcher_offers_the_freed_time_to_the_waiting_list(business, rt):
    slot = first_free_slot(business.id)
    bid = book(business.id, slot.id)
    with db.new_session() as s:  # someone waits for that day
        conv = Conversation(business_id=business.id, channel="telegram", chat_id="w9", created_at=NOW_UTC)
        s.add(conv)
        s.flush()
        s.add(WaitlistEntry(business_id=business.id, conversation_id=conv.id, chat_id="w9", channel="telegram",
                            customer_name="Гүл", customer_phone="0700111222", day=slot.start.date(), created_at=NOW_UTC))
        s.commit()
    rt._llm = FakeLLM([AgentReply("Отменила вашу запись.", cancel=bid)])
    out = process_incoming(rt, business.id, IncomingMessage("telegram", "c1", "text", "Отмените запись", NAME, "d1"), NOW_UTC)
    assert out.cancelled_id == bid
    assert rt.tg.sent[0] == ("c1", "Отменила вашу запись.")  # the reply goes first
    assert rt.tg.sent[-1][0] == "w9" and "освободилось время" in rt.tg.sent[-1][1]
    with db.new_session() as s:
        assert s.exec(select(WaitlistEntry)).one().status == "notified"
