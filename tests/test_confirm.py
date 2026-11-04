"""Confirming a visit from the reminder, and what happens when nobody confirms (joop/confirm.py)."""

from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlmodel import select

from joop import confirm, db
from joop.agent.engine import handle_incoming
from joop.agent.llm import AgentReply
from joop.channels.base import IncomingMessage
from joop.models import Booking, Business, Slot
from joop.scheduler import run_due_jobs
from joop.web.app import create_app

from .conftest import FakeLLM
from .test_scheduler import EVENING_UTC, _book, _run
from .test_web import csrf_of, login

NEXT_MORNING = datetime(2026, 11, 5, 2, 10)  # 08:10 in Bishkek on the day of the visit: the morning summary
VISIT_UTC = datetime(2026, 11, 5, 4, 0)  # the booking is at 10:00 Bishkek


def _say(business_id, rt, text, chat="1001", now=EVENING_UTC + timedelta(minutes=5), llm=None):
    with db.new_session() as s:
        out = handle_incoming(s, s.get(Business, business_id), IncomingMessage("telegram", chat, "text", text, "Айбек", f"tg:{chat}:{text[:12]}"),
                              (lambda: llm) if llm else rt.get_llm, now)
        s.commit()
        return out


def _booking(business_id):
    with db.new_session() as s:
        return s.exec(select(Booking).where(Booking.business_id == business_id, Booking.channel == "telegram")).one()


def test_reminder_asks_for_a_yes_and_a_yes_confirms_without_the_model(business, rt):
    _book(business, "telegram", "1001")
    assert _run(business, rt)["reminders"]["sent"] == 1
    reminder = rt.tg.sent[-1][1]
    assert reminder.endswith("Ответьте «да», если придёте, или напишите, если планы изменились.")
    llm = FakeLLM([AgentReply("не должно вызываться")])
    out = _say(business.id, rt, "Да, приду", llm=llm)
    assert out.reply == "Спасибо, ждём вас Чт 05.11 10:00!" and not llm.calls
    assert _booking(business.id).confirmed_at is not None
    out = _say(business.id, rt, "да", llm=FakeLLM([AgentReply("Чем ещё помочь?")]))  # already confirmed: the model answers
    assert out.reply == "Чем ещё помочь?"


def test_yes_in_kyrgyz_and_yes_without_a_reminder_pending(business, rt):
    _book(business, "telegram", "1001")
    llm = FakeLLM([AgentReply("Жакшы")])
    assert _say(business.id, rt, "ооба", llm=llm).reply == "Жакшы"  # no reminder yet: an ordinary message
    _run(business, rt)
    assert _say(business.id, rt, "Ооба, келем", llm=llm).reply == "Рахмат, Бш 05.11 10:00 күтөбүз!"


def test_morning_summary_lists_who_did_not_confirm(business, rt):
    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.admin_chat_ids, b.digest_hour = "999", 8
        s.add(b)
        s.commit()
    _book(business, "telegram", "1001")
    _book(business, "telegram", "1002", name="Нурлан")
    _run(business, rt)
    _say(business.id, rt, "да", chat="1001")
    _run(business, rt, NEXT_MORNING)
    [digest] = [t for chat, t in rt.tg.sent if chat == "999" and t.startswith("Сводка")]
    assert "Не подтвердили запись: 1 — 10:00 Нурлан, +996555123456. Позвоните или освободите время." in digest
    assert "Айбек" not in digest.split("Не подтвердили")[1].split("\n")[0]


def test_release_unconfirmed_when_the_business_chose_it(business, rt):
    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.admin_chat_ids, b.release_unconfirmed_hours = "999", 3
        s.add(b)
        s.commit()
    _book(business, "telegram", "1001")
    _book(business, "telegram", "1002", name="Нурлан")
    _run(business, rt)
    _say(business.id, rt, "да", chat="1001")
    assert "unconfirmed" not in _run(business, rt, VISIT_UTC - timedelta(hours=4))  # too early
    report = _run(business, rt, VISIT_UTC - timedelta(hours=3))
    assert report["unconfirmed"] == {"released": 1}
    with db.new_session() as s:
        rows = {b.customer_name: b for b in s.exec(select(Booking).where(Booking.channel == "telegram")).all()}
        assert rows["Айбек"].status == "booked" and rows["Нурлан"].status == "cancelled"
        assert s.get(Slot, rows["Нурлан"].slot_id).status == "free"
    assert ("1002", "Вы не подтвердили запись на Чт 05.11 10:00, поэтому время освобождено. Если хотите, запишу снова — напишите удобное время.") in rt.tg.sent
    assert any(chat == "999" and "Запись снята: Нурлан, +996555123456, Чт 05.11 10:00 — не подтвердил(а) после напоминания." in t
               for chat, t in rt.tg.sent)
    assert "unconfirmed" not in _run(business, rt, VISIT_UTC - timedelta(hours=2))  # once


def test_no_release_when_the_reminder_did_not_reach_the_customer(business, rt):
    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.release_unconfirmed_hours = 3
        s.add(b)
        s.commit()
    _book(business, "telegram", "1001")
    with db.new_session() as s:
        row = s.exec(select(Booking).where(Booking.channel == "telegram")).one()
        row.reminder_status = "failed"
        s.add(row)
        s.commit()
    assert "unconfirmed" not in _run(business, rt, VISIT_UTC - timedelta(hours=3))
    assert _booking(business.id).status == "booked"


def test_settings_save_the_release_hours(business, rt, settings):
    with TestClient(create_app(settings, rt, init=False)) as c:
        login(c)
        token = csrf_of(c.get("/panel/settings").text)
        c.post("/panel/settings", data={"csrf": token, "release_unconfirmed_hours": "4", "deposit_amount": "0", "deposit_hours": "2",
                                        "deposit_details": ""})
        with db.new_session() as s:
            assert s.get(Business, business.id).release_unconfirmed_hours == 4
        assert 'name="release_unconfirmed_hours" value="4"' in c.get("/panel/settings").text
