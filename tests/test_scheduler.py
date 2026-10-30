from datetime import datetime, timedelta

from sqlmodel import select

from joop import db
from joop.agent.engine import handle_incoming
from joop.agent.llm import AgentReply
from joop.channels.base import IncomingMessage
from joop.models import Booking, Business, Message, Slot, Staff
from joop.scheduler import Scheduler, run_due_jobs

from .conftest import NOW_UTC, FakeLLM

# 18:05 in Bishkek on Wednesday 4 Nov (12:05 UTC): reminder time for Thursday's bookings.
EVENING_UTC = datetime(2026, 11, 4, 12, 5)


def _book(business, channel, chat_id, minutes_ago_customer=10, name="Айбек"):
    """Create a booking for tomorrow 10:00 through the real engine."""
    with db.new_session() as s:
        b = s.get(Business, business.id)
        slot = s.exec(
            select(Slot).join(Staff).where(Slot.business_id == b.id, Slot.status == "free", Slot.start == datetime(2026, 11, 5, 10, 0))
        ).first()
        llm = FakeLLM([AgentReply("Записала", booking={"slot_id": slot.id, "name": name, "phone": "0555123456", "service": "чистка"})])
        when = EVENING_UTC - timedelta(minutes=minutes_ago_customer)
        handle_incoming(s, b, IncomingMessage(channel, chat_id, "text", f"запишите, {name}", "", f"{channel}:{chat_id}"), lambda: llm, when)
        s.commit()


def _run(business, rt, now=EVENING_UTC):
    with db.new_session() as s:
        b = s.get(Business, business.id)
        report = run_due_jobs(s, rt, b, now)
        s.commit()
        return report


def test_reminders_by_channel(business, rt):
    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.admin_chat_ids = "-5001"
        b.wa_phone_number_id, b.wa_access_token, b.wa_reminder_template = "pn1", "tok", "appointment_reminder"
        b.ig_account_id, b.ig_access_token = "ig1", "tok"
        s.commit()
    _book(business, "telegram", "1001")
    _book(business, "whatsapp", "996555000111", minutes_ago_customer=60 * 30)  # outside the 24h window
    _book(business, "instagram", "igsid-1", minutes_ago_customer=60 * 30)  # outside the window: manual

    report = _run(business, rt)
    assert report["reminders"] == {"sent": 2, "manual": 1}
    assert rt.tg.sent[0][0] == "1001" and rt.tg.sent[0][1].startswith("Напоминаем: завтра, Чт 05.11 10:00")
    assert rt.wa.templates == [("996555000111", "appointment_reminder", "ru", ["Айбек", "Чт 05.11 10:00", rt.wa.templates[0][3][2]])]
    assert rt.ig.sent == []
    manual_note = rt.tg.sent[-1]
    assert manual_note[0] == "-5001" and manual_note[1].startswith("Напомните вручную")
    with db.new_session() as s:
        statuses = sorted(b.reminder_status for b in s.exec(select(Booking)).all())
        assert statuses == ["manual", "sent", "sent"]
        assert s.exec(select(Message).where(Message.text.startswith("Напоминаем"))).all()

    # Same day again: nothing is sent twice.
    rt.tg.sent.clear()
    assert "reminders" not in _run(business, rt, EVENING_UTC + timedelta(minutes=30))
    assert rt.tg.sent == []


def test_instagram_reminder_inside_window(business, rt):
    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.ig_account_id, b.ig_access_token = "ig1", "tok"
        s.commit()
    _book(business, "instagram", "igsid-2", minutes_ago_customer=30)
    assert _run(business, rt)["reminders"] == {"sent": 1, "manual": 0}
    assert rt.ig.sent[0][0] == "igsid-2"


def test_digest_runs_in_the_morning_only(business, rt):
    with db.new_session() as s:
        s.get(Business, business.id).admin_chat_ids = "-5001"
        s.commit()
    _book(business, "telegram", "1001")
    thursday_morning = datetime(2026, 11, 5, 2, 30)  # 08:30 in Bishkek
    report = _run(business, rt, thursday_morning)
    assert report["digest"] is True
    text = rt.tg.sent[-1][1]
    assert text.startswith("Сводка «Ак-Тиш Дент» на 05.11")
    assert "10:00 — Айбек, +996555123456 — чистка" in text

    # A restart at night must not send a "morning" summary.
    with db.new_session() as s:
        s.get(Business, business.id).last_digest_date = ""
        s.commit()
    night = datetime(2026, 11, 5, 17, 0)  # 23:00 local
    assert "digest" not in _run(business, rt, night)


def test_scheduler_tick_skips_disabled_business(business, rt):
    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.bot_enabled = False
        b.admin_chat_ids = "-5001"
        s.commit()
    Scheduler(rt, 60).tick(datetime(2026, 11, 5, 2, 30))
    with db.new_session() as s:
        assert s.get(Business, business.id).last_digest_date == ""
