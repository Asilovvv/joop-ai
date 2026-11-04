"""One follow-up to a customer who asked and went quiet without booking (joop/unfinished.py)."""

from datetime import datetime, timedelta

from sqlmodel import select

from joop import db, unfinished
from joop.agent.engine import handle_incoming
from joop.agent.llm import AgentReply
from joop.channels.base import IncomingMessage
from joop.models import Business, Conversation, Message
from joop.scheduler import run_due_jobs

from .conftest import FakeLLM, first_free_slot

ASKED_UTC = datetime(2026, 11, 4, 6, 0)  # 12:00 Bishkek, Wednesday: working hours
LATER = ASKED_UTC + timedelta(hours=2, minutes=5)


def _turn_on(business_id, **values):
    with db.new_session() as s:
        b = s.get(Business, business_id)
        b.nudge_unfinished = True
        for k, v in values.items():
            setattr(b, k, v)
        s.add(b)
        s.commit()


def _say(business_id, rt, text, chat="1001", channel="telegram", now=ASKED_UTC, llm=None):
    with db.new_session() as s:
        out = handle_incoming(s, s.get(Business, business_id), IncomingMessage(channel, chat, "text", text, "Айбек", f"{channel}:{chat}:{text[:12]}"),
                              (lambda: llm) if llm else rt.get_llm, now)
        s.commit()
        return out


def _run(business, rt, now):
    with db.new_session() as s:
        report = run_due_jobs(s, rt, s.get(Business, business.id), now)
        s.commit()
        return report


def test_asked_the_price_and_went_quiet_gets_two_nearest_times_once(business, rt):
    _turn_on(business.id)
    _say(business.id, rt, "Сколько стоит чистка?", llm=FakeLLM([AgentReply("Чистка — 3 000 сом.")]))
    assert "unfinished" not in _run(business, rt, ASKED_UTC + timedelta(hours=1))  # too soon
    report = _run(business, rt, LATER)
    assert report["unfinished"] == {"sent": 1}
    slot = first_free_slot(business.id)
    text = rt.tg.sent[-1][1]
    assert text.startswith("Если удобно, могу записать вас: ") and f"{slot.start:%d.%m %H:%M}" in text
    assert text.endswith("Напишите «да» или другое удобное время.")
    assert "unfinished" not in _run(business, rt, LATER + timedelta(hours=1))  # once per conversation
    with db.new_session() as s:
        conv = s.exec(select(Conversation)).one()
        assert conv.followup_at is not None
        assert [m.role for m in s.exec(select(Message).where(Message.conversation_id == conv.id).order_by(Message.id)).all()] == ["customer", "ai", "ai"]


def test_no_follow_up_when_booked_handed_off_off_hours_or_turned_off(business, rt):
    _say(business.id, rt, "Сколько стоит чистка?", llm=FakeLLM([AgentReply("3 000 сом.")]))
    assert "unfinished" not in _run(business, rt, LATER)  # off by default
    _turn_on(business.id)
    # booked in that chat: nothing to chase
    slot = first_free_slot(business.id)
    _say(business.id, rt, "Запишите, Айбек 0555 123 456", now=ASKED_UTC + timedelta(minutes=5),
         llm=FakeLLM([AgentReply("Записала!", booking={"slot_id": slot.id, "name": "Айбек", "phone": "0555 123 456", "service": "чистка"})]))
    assert "unfinished" not in _run(business, rt, LATER)
    # handed to a person: staff are on it
    _say(business.id, rt, "Хочу пожаловаться", chat="1002", llm=FakeLLM([AgentReply("Передаю администратору.", handoff="жалоба")]))
    assert "unfinished" not in _run(business, rt, LATER)
    # asked at night: the follow-up waits for working hours, then goes
    night = datetime(2026, 11, 4, 17, 30)  # 23:30 Bishkek
    _say(business.id, rt, "Есть окна завтра?", chat="1003", now=night, llm=FakeLLM([AgentReply("Есть 10:00 и 11:00.")]))
    assert "unfinished" not in _run(business, rt, night + timedelta(hours=3))
    assert _run(business, rt, datetime(2026, 11, 5, 4, 10))["unfinished"] == {"sent": 1}  # 10:10 next morning


def test_kyrgyz_customer_gets_kyrgyz_and_a_silent_customer_is_not_chased_twice_a_day(business, rt):
    _turn_on(business.id)
    _say(business.id, rt, "Тазалоо канча турат?", llm=FakeLLM([AgentReply("3 000 сом.")]))
    assert _run(business, rt, LATER)["unfinished"] == {"sent": 1}
    assert rt.tg.sent[-1][1].startswith("Ыңгайлуу болсо, жазып коёюн: ")
    # the customer answers "да" to the follow-up: the AI books as usual (the model gets the message)
    out = _say(business.id, rt, "да", now=LATER + timedelta(minutes=3), llm=FakeLLM([AgentReply("Кайсы убакыт?")]))
    assert out.reply == "Кайсы убакыт?"


def test_weekly_report_counts_follow_ups_and_bookings_after_them(business, rt):
    from joop.scheduler import weekly_report_text

    _turn_on(business.id)
    _say(business.id, rt, "Сколько стоит чистка?", llm=FakeLLM([AgentReply("3 000 сом.")]))
    _run(business, rt, LATER)
    slot = first_free_slot(business.id)
    _say(business.id, rt, "да, Айбек 0555 123 456", now=LATER + timedelta(minutes=10),
         llm=FakeLLM([AgentReply("Записала!", booking={"slot_id": slot.id, "name": "Айбек", "phone": "0555 123 456", "service": "чистка"})]))
    with db.new_session() as s:
        text = weekly_report_text(s, s.get(Business, business.id), LATER + timedelta(days=1))
    assert "Напомнили о себе 1 клиенту, который спросил и замолчал; записались после этого: 1." in text
