"""Customers who got the "can't answer now" fallback during an outage are answered when the AI works again."""

from datetime import timedelta

import pytest
from sqlmodel import select

from joop import db, recovery
from joop.agent.engine import ERROR_REPLY, LATE_PREFIX_KY, LATE_PREFIX_RU, handle_incoming
from joop.agent.llm import AgentReply, LLMError
from joop.channels.base import IncomingMessage
from joop.models import Booking, Business, Conversation, Lead, Message
from joop.scheduler import run_due_jobs

from .conftest import NOW_UTC, FakeLLM, first_free_slot

LATER = NOW_UTC + timedelta(minutes=20)


@pytest.fixture(autouse=True)
def _fresh():
    recovery.reset()
    yield
    recovery.reset()


@pytest.fixture
def admins(business):
    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.admin_chat_ids = "999"
        s.add(b)
        s.commit()
    return business


def fail(business, text="Сколько стоит чистка?", chat="1001", channel="telegram", when=NOW_UTC, ext=None):
    llm = FakeLLM([LLMError("Claude API call failed: BadRequestError")])
    with db.new_session() as s:
        out = handle_incoming(s, s.get(Business, business.id),
                              IncomingMessage(channel, chat, "text", text, "Айбек", ext or f"{channel}:{chat}:{text[:12]}:{when}"),
                              lambda: llm, when)
        s.commit()
    assert out.reply == ERROR_REPLY
    return out


def tick(rt, business, when=LATER):
    with db.new_session() as s:
        report = run_due_jobs(s, rt, s.get(Business, business.id), when)
        s.commit()
    return report


def messages(chat="1001"):
    with db.new_session() as s:
        conv = s.exec(select(Conversation).where(Conversation.chat_id == chat)).one()
        return [(m.role, m.text) for m in s.exec(select(Message).where(Message.conversation_id == conv.id).order_by(Message.id))]


def test_waiting_customer_is_answered_once_with_an_apology(admins, rt, llm):
    fail(admins)
    fail(admins, text="Ау, вы тут?", ext="second")  # two messages during the outage
    llm.replies = [AgentReply("Профессиональная чистка стоит 3 000 сом. Записать вас?")]

    report = tick(rt, admins)

    assert report["answered_after_outage"] == 1
    answer = LATE_PREFIX_RU + "Профессиональная чистка стоит 3 000 сом. Записать вас?"
    assert ("1001", answer) in rt.tg.sent
    # the model sees both customer messages as one turn, without the fallback replies
    assert llm.calls[0]["messages"] == [{"role": "user", "content": "Сколько стоит чистка?\nАу, вы тут?"}]
    assert messages()[-1] == ("ai", answer)
    with db.new_session() as s:
        leads = s.exec(select(Lead).where(Lead.kind == "error")).all()
        assert len(leads) == 2 and all(lead.status == "done" and lead.closed_by == recovery.CLOSED_BY for lead in leads)
    summary = [t for chat, t in rt.tg.sent if chat == "999"]
    assert summary and "ИИ снова отвечает" in summary[-1] and "Айбек (Telegram)" in summary[-1]

    rt.tg.sent.clear()
    assert "answered_after_outage" not in tick(rt, admins, LATER + timedelta(minutes=5))  # never twice
    assert len(llm.calls) == 1 and not rt.tg.sent


def test_kyrgyz_customer_gets_the_kyrgyz_apology(business, rt, llm):
    fail(business, text="Тиш тазалоо канча турат?")
    llm.replies = [AgentReply("Тиш тазалоо 3 000 сом турат.")]
    tick(rt, business)
    assert ("1001", LATE_PREFIX_KY + "Тиш тазалоо 3 000 сом турат.") in rt.tg.sent


def test_still_down_stores_nothing_and_waits_before_the_next_try(business, rt, llm):
    fail(business)
    llm.replies = [LLMError("Claude API call failed: BadRequestError")]
    before = messages()
    assert "answered_after_outage" not in tick(rt, business)
    assert messages() == before and not rt.tg.sent
    with db.new_session() as s:
        assert len(s.exec(select(Lead).where(Lead.kind == "error")).all()) == 1  # no new request for the retry

    llm.replies = [AgentReply("Чистка — 3 000 сом.")]
    tick(rt, business, LATER + timedelta(minutes=2))
    assert len(llm.calls) == 1  # inside the pause: no model call
    tick(rt, business, LATER + recovery.RETRY_EVERY)
    assert ("1001", LATE_PREFIX_RU + "Чистка — 3 000 сом.") in rt.tg.sent


def test_a_booking_made_after_the_outage_is_checked_like_any_other(admins, rt, llm):
    fail(admins, text="Запишите на чистку завтра в 9, Айбек 0555123456")
    slot = first_free_slot(admins.id)
    llm.replies = [AgentReply("Записала вас на завтра 9:00.", booking={"slot_id": slot.id, "name": "Айбек", "phone": "0555123456",
                                                                        "service": "чистка"})]
    tick(rt, admins)
    with db.new_session() as s:
        booking = s.exec(select(Booking)).one()
        assert booking.customer_phone == "+996555123456" and booking.status == "booked"
    assert any(chat == "999" and "Новая запись через ИИ" in t for chat, t in rt.tg.sent)
    assert any(chat == "1001" and t.startswith(LATE_PREFIX_RU) for chat, t in rt.tg.sent)


def test_left_alone_when_someone_already_answered_or_it_is_too_late(admins, rt, llm):
    fail(admins, chat="2001")  # staff replied from the panel
    with db.new_session() as s:
        conv = s.exec(select(Conversation).where(Conversation.chat_id == "2001")).one()
        s.add(Message(business_id=admins.id, conversation_id=conv.id, role="staff", text="Чистка 3 000 сом", created_at=NOW_UTC))
        s.commit()
    fail(admins, chat="2002")  # staff marked the request done
    with db.new_session() as s:
        lead = s.exec(select(Lead).where(Lead.chat_id == "2002")).one()
        lead.status = "done"
        s.add(lead)
        s.commit()
    fail(admins, chat="2003")  # staff took the chat over
    with db.new_session() as s:
        conv = s.exec(select(Conversation).where(Conversation.chat_id == "2003")).one()
        conv.ai_paused_until = NOW_UTC + timedelta(hours=12)
        s.add(conv)
        s.commit()
    fail(admins, chat="2004", when=NOW_UTC - recovery.RECOVERY_WINDOW - timedelta(minutes=30))  # too old
    fail(admins, chat="web-abc", channel="web")  # the site chat cannot show a late answer

    assert "answered_after_outage" not in tick(rt, admins)
    assert llm.calls == [] and not rt.tg.sent


def test_a_later_message_answered_normally_closes_nothing_and_sends_nothing(business, rt, llm):
    fail(business)
    ok = FakeLLM([AgentReply("Чистка — 3 000 сом.")])
    with db.new_session() as s:
        handle_incoming(s, s.get(Business, business.id), IncomingMessage("telegram", "1001", "text", "А цена?", "Айбек", "x2"),
                        lambda: ok, NOW_UTC + timedelta(minutes=5))
        s.commit()
    tick(rt, business)
    assert llm.calls == [] and not rt.tg.sent  # the customer already has an answer; the request stays for staff
