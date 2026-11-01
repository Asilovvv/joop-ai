"""Prepayment for a booking asked in the chat (joop/deposits.py)."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from joop import db, deposits
from joop.agent.engine import handle_incoming
from joop.agent.llm import AgentReply
from joop.channels.base import IncomingMessage
from joop.models import Booking, Business, Slot
from joop.scheduler import run_due_jobs
from joop.timeutil import local_to_utc, utc_to_local
from joop.web.app import create_app

from .conftest import NOW_UTC, FakeLLM, first_free_slot
from .test_web import csrf_of, login

DETAILS = "перевод MBank по номеру 0555 000 111 (Айгерим К.)"


def turn_on(business_id, **values):
    with db.new_session() as s:
        b = s.get(Business, business_id)
        b.deposit_amount, b.deposit_details, b.deposit_hours, b.admin_chat_ids = 500, DETAILS, 2, "999"
        for k, v in values.items():
            setattr(b, k, v)
        s.add(b)
        s.commit()


def say(business_id, rt, text, kind="text", label="", now=NOW_UTC, chat="c1"):
    with db.new_session() as s:
        out = handle_incoming(s, s.get(Business, business_id), IncomingMessage("telegram", chat, kind, text, media_label=label),
                              rt.get_llm, now)
        s.commit()
        return out


def book(business_id, rt, now=NOW_UTC):
    slot = first_free_slot(business_id)
    rt._llm = FakeLLM([AgentReply("Записала!", booking={"slot_id": slot.id, "name": "Айбек", "phone": "0555 123 456",
                                                         "service": "консультация"})])
    out = say(business_id, rt, "Запишите, Айбек, 0555 123 456", now=now)
    with db.new_session() as s:
        return out, s.get(Booking, out.booking_id), slot


def test_after_booking_the_customer_gets_amount_details_and_deadline(business, rt):
    turn_on(business.id)
    out, booking, slot = book(business.id, rt)
    assert (booking.deposit_status, booking.deposit_due) == ("awaiting", 500)
    deadline_local = utc_to_local(booking.deposit_deadline, business.timezone)
    assert booking.deposit_deadline == min(NOW_UTC + timedelta(hours=2), local_to_utc(slot.start, business.timezone) - timedelta(hours=1))
    assert out.reply.startswith("Записала!\n\nЧтобы закрепить запись, нужна предоплата 500 сом. Как оплатить: " + DETAILS)
    assert f"Оплатите до {deadline_local:%d.%m %H:%M}" in out.reply and "освободится" not in out.reply
    assert any(f"Ждём предоплату 500 сом до {deadline_local:%d.%m %H:%M}." in n for n in out.admin_notes)
    assert "Для записи нужна предоплата 500 сом" in rt._llm.calls[0]["system"]  # so "нужна ли предоплата?" is answered


def test_off_by_default_and_not_for_a_visit_too_soon(business, rt):
    out, booking, _ = book(business.id, rt)
    assert booking.deposit_status == "" and "предоплата" not in out.reply
    assert "предоплата" not in rt._llm.calls[0]["system"]
    turn_on(business.id)
    with db.new_session() as s:
        b = s.get(Business, business.id)
        soon = Booking(business_id=b.id, start=utc_to_local(NOW_UTC, b.timezone) + timedelta(minutes=75))
        assert deposits.require(b, soon, NOW_UTC) is False  # an hour before the visit leaves only 15 minutes to pay
        b.deposit_details = " "
        assert deposits.require(b, Booking(business_id=b.id, start=soon.start + timedelta(days=1)), NOW_UTC) is False


@pytest.mark.parametrize("message", [dict(text="Оплатила"), dict(text="", kind="media", label="фото"), dict(text="төлөп койдум")])
def test_receipt_or_paid_message_goes_to_staff_to_check(business, rt, message):
    turn_on(business.id)
    _, booking, _ = book(business.id, rt)
    out = say(business.id, rt, now=NOW_UTC + timedelta(minutes=20), **message)
    kyrgyz = message["text"] == "төлөп койдум"
    assert out.reply == ("Рахмат! Администратор төлөмдү текшерип, жазылууңузду ырастайт." if kyrgyz
                         else "Спасибо! Администратор проверит оплату и подтвердит запись.")
    assert out.admin_notes[0].startswith("Предоплата: Айбек, ") and "500 сом" in out.admin_notes[0]
    assert ("прислал(а) чек" in out.admin_notes[0]) == (message.get("kind") == "media")
    assert len(rt._llm.calls) == 1  # no model call for this
    with db.new_session() as s:
        assert s.get(Booking, booking.id).deposit_status == "check"


def test_a_question_about_paying_still_goes_to_the_ai(business, rt):
    turn_on(business.id)
    book(business.id, rt)
    rt._llm.replies.append(AgentReply("Реквизиты в сообщении выше."))
    assert say(business.id, rt, "А как оплатить?").reply == "Реквизиты в сообщении выше."
    say(business.id, rt, "Оплатила", chat="other")  # a chat without a booking: an ordinary message
    assert len(rt._llm.calls) == 3


def test_deadline_tells_staff_or_releases_the_booking(business, rt):
    turn_on(business.id)
    _, booking, slot = book(business.id, rt)
    late = booking.deposit_deadline + timedelta(minutes=1)
    with db.new_session() as s:
        assert deposits.check_deadlines(s, rt, s.get(Business, business.id), booking.deposit_deadline - timedelta(minutes=1)) == {}
        assert deposits.check_deadlines(s, rt, s.get(Business, business.id), late) == {"released": 0, "overdue": 1}
        s.commit()
    assert any(chat == "999" and "Предоплата не пришла к сроку: Айбек" in text for chat, text in rt.tg.sent)
    with db.new_session() as s:  # told once
        assert s.get(Booking, booking.id).deposit_status == "overdue"
        assert deposits.check_deadlines(s, rt, s.get(Business, business.id), late) == {}


def test_auto_release_frees_the_time_and_tells_the_customer(business, rt):
    turn_on(business.id, deposit_auto_cancel=True)
    out, booking, slot = book(business.id, rt)
    assert "Без предоплаты время освободится." in out.reply
    with db.new_session() as s:
        report = run_due_jobs(s, rt, s.get(Business, business.id), booking.deposit_deadline + timedelta(minutes=1))
        s.commit()
        assert report["deposits"] == {"released": 1, "overdue": 0}
        b = s.get(Booking, booking.id)
        assert (b.status, b.deposit_status) == ("cancelled", "expired") and s.get(Slot, slot.id).status == "free"
    assert any(chat == "c1" and text.startswith("Предоплата не поступила, поэтому время") for chat, text in rt.tg.sent)
    assert any(chat == "999" and "Запись снята: Айбек" in text for chat, text in rt.tg.sent)


@pytest.fixture
def client(settings, rt, business):
    with TestClient(create_app(settings, rt, init=False)) as c:
        yield c


def test_panel_settings_and_marking_the_payment(client, business, rt):
    token = login(client)
    page = client.get("/panel/settings").text
    assert "Предоплата за запись" in page
    form = {"csrf": token, "name": "Ак-Тиш Дент", "work_start": "09:00", "work_end": "19:00", "timezone": "Asia/Bishkek",
            "niche": "dental", "bot_enabled": "1", "deposit_amount": "500", "deposit_hours": "3", "deposit_details": ""}
    assert "Предоплата не включена" in client.post("/panel/settings", data=form).text
    with db.new_session() as s:
        assert s.get(Business, business.id).deposit_amount == 0
    client.post("/panel/settings", data={**form, "deposit_details": DETAILS, "deposit_auto_cancel": "1"})
    with db.new_session() as s:
        b = s.get(Business, business.id)
        assert (b.deposit_amount, b.deposit_hours, b.deposit_details, b.deposit_auto_cancel) == (500, 3, DETAILS, True)
    _, booking, _ = book(business.id, rt)
    say(business.id, rt, "Перевела")
    page = client.get("/panel/bookings").text
    assert "прислал чек — проверьте 500 сом" in page and f"/panel/bookings/{booking.id}/paid" in page
    r = client.post(f"/panel/bookings/{booking.id}/paid", data={"csrf": csrf_of(page)})
    assert "Предоплата отмечена. Клиенту отправлено подтверждение." in r.text
    assert any(chat == "c1" and text.startswith("Предоплата получена, спасибо! Ждём вас") for chat, text in rt.tg.sent)
    page = client.get("/panel/bookings").text
    assert "предоплата 500 сом получена" in page and f"/panel/bookings/{booking.id}/paid" not in page
