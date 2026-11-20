"""Fixes from the independent review of #250-#259 (20.11.2026)."""

import re
import threading
import time
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlmodel import select

from joop import db, recovery
from joop.agent.engine import handle_incoming
from joop.agent.llm import AgentReply, LLMError
from joop.channels.base import IncomingMessage
from joop.dispatch import alert_chats, alerts_other_bot, process_incoming
from joop.models import Booking, Business, Message, Slot
from joop.scheduler import Scheduler, run_due_jobs
from joop.timeutil import utc_to_local
from joop.web.app import create_app

from .conftest import NOW_UTC, FakeLLM
from .test_booking_page import _book, _first_time, _open, form_clock  # noqa: F401 - the form's clock
from .test_web import csrf_of, login


class SlowLLM(FakeLLM):
    def respond(self, system, messages, schema=None):
        time.sleep(1.0)
        return super().respond(system, messages, schema)


def test_a_late_answer_after_an_outage_waits_for_the_chats_turn(business, rt):
    """Recovery answered outside the chat's turn: with «вы тут?» at that moment the customer got two bookings."""
    recovery.reset()
    with db.new_session() as s:
        handle_incoming(s, s.get(Business, business.id),
                        IncomingMessage("telegram", "1001", "text", "Запишите на чистку завтра, Айбек 0555123456", "Айбек", "e1"),
                        lambda: FakeLLM([LLMError("down")]), NOW_UTC)
        s.commit()
        free = s.exec(select(Slot).where(Slot.business_id == business.id, Slot.status == "free").order_by(Slot.start)).all()
        first, second = free[0].id, free[1].id
    slow = SlowLLM([
        AgentReply("Записала вас.", booking={"slot_id": first, "name": "Айбек", "phone": "0555123456"}),
        AgentReply("Записала вас.", booking={"slot_id": second, "name": "Айбек", "phone": "0555123456"}),
    ])
    rt.get_llm = lambda: slow
    later = NOW_UTC + timedelta(minutes=20)

    def tick():
        with db.new_session() as s:
            run_due_jobs(s, rt, s.get(Business, business.id), later)
            s.commit()

    worker = threading.Thread(target=tick)
    worker.start()
    time.sleep(0.3)
    process_incoming(rt, business.id, IncomingMessage("telegram", "1001", "text", "Алло, вы тут?", "Айбек", "e2"), later)
    worker.join()
    # one after the other: the live message's model call already sees the late answer and its booking in the history
    # (before, both ran at once on the same history, and a real model booked twice)
    assert len(slow.calls) == 2
    assert "Записала вас." in str(slow.calls[1]["messages"]) and "Записала вас." not in str(slow.calls[0]["messages"])


def _page_booking_link(business, settings, rt, round_done: bool):
    _open(business.id)
    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.telegram_bot_username = "aktish_bot"
        if round_done:
            b.last_reminder_date = utc_to_local(NOW_UTC, b.timezone).date().isoformat()
        s.add(b)
        s.commit()
    with db.new_session() as s:  # now is 23:14: tomorrow's round is past, a visit the day after is reminded
        later = utc_to_local(NOW_UTC, "Asia/Bishkek").date() + timedelta(days=2 if not round_done else 1)
        slot = next(x for x in s.exec(select(Slot).where(Slot.business_id == business.id, Slot.status == "free")
                                      .order_by(Slot.start)).all() if x.start.date() == later)
    with TestClient(create_app(settings, rt, init=False)) as c:
        url = _book(c, slot.id).headers["location"]
        return c.get(url).text


def test_no_reminder_is_promised_once_its_round_has_run(business, settings, rt):
    page = _page_booking_link(business, settings, rt, round_done=True)
    assert "Напомнить в Telegram" not in page and "t.me/aktish_bot?start=" not in page
    with db.new_session() as s:
        x = s.exec(select(Booking).where(Booking.source == "page")).one()
        out = handle_incoming(s, s.get(Business, business.id),
                              IncomingMessage("telegram", "777", "command", f"/start b{x.id}_0", "Айбек", "r1"), lambda: None, NOW_UTC)
        assert "напомним" not in (out.reply or "")


def test_the_tap_is_not_a_dialogue_and_speaks_kyrgyz_from_the_kyrgyz_page(business, settings, rt):
    page = _page_booking_link(business, settings, rt, round_done=False)
    link = re.search(r"start=(b\d+_[0-9a-f]+)", page).group(1)
    with db.new_session() as s:
        b = s.get(Business, business.id)
        out = handle_incoming(s, b, IncomingMessage("telegram", "777", "command", f"/start {link}_ky", "Айбек", "r1"),
                              lambda: None, NOW_UTC)
        s.commit()
        assert out.reply.startswith("Даяр: бир күн мурун")
        roles = s.exec(select(Message.role).join(Booking, Booking.conversation_id == Message.conversation_id)
                       .where(Booking.source == "page")).all()
        assert roles == ["ai"]  # the tap itself is not stored: no «диалог с клиентом» in the figures


def test_with_the_ai_off_the_booking_page_bookings_are_still_reminded(business, settings, rt):
    _open(business.id)
    with TestClient(create_app(settings, rt, init=False)) as c:
        slot_id = _first_time(c)
        _book(c, slot_id)
    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.bot_enabled = False
        s.add(b)
        s.commit()
        start = s.get(Slot, slot_id).start
    evening = start - timedelta(days=1) - timedelta(hours=6) + timedelta(hours=18 - start.hour)  # 18:00 the day before
    Scheduler(rt, 60).tick(evening)
    assert any("Напомните вручную" in text for _, text in rt.tg.sent)


def test_alert_chats_linked_before_0063_are_not_kept_by_a_new_bot(business, settings, rt):
    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.admin_chat_ids, b.admin_bot = "555", ""  # linked through bot 123 before admin_bot existed
        s.add(b)
        s.commit()
    rt.tg.me = {"username": "new_bot"}
    rt.tg.set_webhook = lambda *args, **kwargs: True
    with TestClient(create_app(settings, rt, init=False)) as c:
        token = login(c)
        c.post("/panel/setup/telegram", data={"token": "99999:" + "N" * 35, "csrf": token})
    with db.new_session() as s:
        b = s.get(Business, business.id)
        assert b.telegram_bot_token == "99999:" + "N" * 35 and b.admin_bot == "123"
        assert alert_chats(b) == [] and alerts_other_bot(b)
