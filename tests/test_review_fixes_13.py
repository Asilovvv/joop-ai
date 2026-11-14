"""Fixes from the independent review of PRs #178-#186."""

from datetime import datetime, time, timedelta

from fastapi.testclient import TestClient
from sqlmodel import select

from joop import broadcasts, db, holds, reorders, samples
from joop.agent.engine import handle_incoming
from joop.channels.base import IncomingMessage
from joop.models import Business, Conversation, Order, Slot, Staff
from joop.presets import create_business
from joop.timeutil import local_to_utc, utc_to_local
from joop.web.app import _login_fails, create_app

from .conftest import NOW_UTC, FakeLLM
from .test_holds import reserve, with_bot
from .test_pharmacy import pharmacy
from .test_reorders import turn_on
from .test_water import company, first_order


def midnight_after(business, when_utc, days):
    day = utc_to_local(when_utc, business.timezone).date()
    return local_to_utc(datetime.combine(day + timedelta(days=days + 1), time.min), business.timezone)


def test_a_reservation_counts_from_ready_and_accepted_orders_wait(engine, rt):
    b = pharmacy()
    with_bot(b.id)
    ready, accepted = reserve(b.id, chat="r1"), reserve(b.id, chat="r2")
    late = NOW_UTC + timedelta(days=1, hours=17)  # the next day, late evening
    with db.new_session() as s:
        s.get(Order, ready).status, s.get(Order, ready).sent_at = "sent", late
        s.get(Order, accepted).status = "accepted"
        s.commit()
        biz = s.get(Business, b.id)
        just_after = midnight_after(biz, NOW_UTC, 1) + timedelta(minutes=5)  # where the old code released both
        assert holds.release_expired(s, rt, biz, just_after) == []
        assert holds.release_expired(s, rt, biz, midnight_after(biz, late, 1) + timedelta(minutes=5)) == [ready]
        assert holds.release_expired(s, rt, biz, NOW_UTC + timedelta(days=30)) == []  # accepted: never released


def test_staff_are_asked_to_call_when_the_customer_could_not_be_told(engine, rt):
    b = pharmacy()
    with_bot(b.id)
    order_id = reserve(b.id, chat="wa1")
    with db.new_session() as s:
        conv = s.get(Conversation, s.get(Order, order_id).conversation_id)
        conv.channel, conv.last_customer_at = "whatsapp", NOW_UTC  # 24 hours will have passed
        s.commit()
        holds.release_expired(s, rt, s.get(Business, b.id), NOW_UTC + timedelta(days=3))
        s.commit()
    note = [t for chat, t in rt.tg.sent if chat == "999"][-1]
    assert f"Клиенту написать не получилось — позвоните: №{order_id} — Марат, +996555565656." in note


def test_a_whatsapp_reply_keeps_a_longer_manual_pause(engine, rt):
    with db.new_session() as s:
        b = create_business(s, slug="dent", name="Дент", password="pass-12345", niche="dental", demo=True, now_utc=NOW_UTC)
        b.takeover_minutes = 15
        conv = Conversation(business_id=b.id, channel="whatsapp", chat_id="996555", created_at=NOW_UTC,
                            ai_paused_until=NOW_UTC + timedelta(days=30))
        s.add(conv)
        s.commit()
        handle_incoming(s, s.get(Business, b.id), IncomingMessage("whatsapp", "996555", "staff_echo", "Здравствуйте, это администратор",
                                                                  "", "e1"), lambda: FakeLLM([]), NOW_UTC)
        s.commit()
        assert s.get(Conversation, conv.id).ai_paused_until == NOW_UTC + timedelta(days=30)


def test_the_old_demo_pharmacist_name_is_still_example(engine):
    with db.new_session() as s:
        b = create_business(s, slug="dary", name="Дары", password="pass-12345", niche="pharmacy", demo=True, now_utc=NOW_UTC)
        s.commit()
        row = s.exec(select(Staff).where(Staff.business_id == b.id)).one()
        row.name = "Фармацевт Гульнара"  # a pharmacy that signed up before the demo was renamed
        s.commit()
        assert samples.example_staff_ids(s, s.get(Business, b.id)) == {row.id}


def test_no_reminder_after_a_cancelled_order_and_stop_only_after_a_delivered_one(engine, rt):
    b = company()
    turn_on(b.id)
    first_order(b.id)
    with db.new_session() as s:
        conv = s.exec(select(Conversation).where(Conversation.business_id == b.id)).one()
        s.add(Order(business_id=b.id, conversation_id=conv.id, mode="delivery", status="cancelled", total=360,
                    created_at=NOW_UTC + timedelta(days=10)))
        s.commit()
        assert reorders.send_due(s, rt, s.get(Business, b.id), NOW_UTC + timedelta(days=14)) == {}
    other = company("water", "suu2")
    turn_on(other.id, token=False)  # no bot: the reminder cannot be delivered
    first_order(other.id, chat="w9")
    with db.new_session() as s:
        assert reorders.send_due(s, rt, s.get(Business, other.id), NOW_UTC + timedelta(days=14)) == {"sent": 0, "failed": 1}
        s.commit()
        conv = s.exec(select(Conversation).where(Conversation.business_id == other.id)).one()
        assert broadcasts.opt_change(s, conv, "стоп") is None  # «стоп» here means «wait», not «unsubscribe»


def test_mobile_cannot_book_the_example_person(settings, rt, engine):
    with db.new_session() as s:
        b = create_business(s, slug="dent2", name="Дент", password="pass-12345", niche="dental", demo=True, now_utc=NOW_UTC)
        s.commit()
        slot = s.exec(select(Slot).where(Slot.business_id == b.id, Slot.start > utc_to_local(NOW_UTC, b.timezone)).order_by(Slot.start)).first()
        assert slot.staff_id in samples.example_staff_ids(s, b)
    _login_fails.clear()
    with TestClient(create_app(settings, rt, init=False)) as c:
        token = c.post("/api/mobile/login", json={"company": "dent2", "password": "pass-12345"}).json()["token"]
        r = c.post("/api/mobile/bookings", json={"slot_id": slot.id, "name": "Айгуль", "phone": "0555112233"},
                   headers={"Authorization": f"Bearer {token}"})
    assert r.status_code >= 400
