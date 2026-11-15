"""Prepayments in the mobile app: what a booking waits for, the receipts to check, and «Предоплата получена»."""

from datetime import timedelta

from fastapi.testclient import TestClient
from joop import db
from joop.models import Booking, Business, PanelUser
from joop.security import hash_password
from joop.web.app import _login_fails, create_app

from .conftest import NOW_UTC
from .test_mobile import _chat_booking, auth, book, sign_in, tomorrow_slots


def _awaiting(booking_id, status="check"):
    with db.new_session() as s:
        row = s.get(Booking, booking_id)
        row.deposit_due, row.deposit_status, row.deposit_deadline = 500, status, NOW_UTC.replace(tzinfo=None) + timedelta(hours=2)
        s.add(row)
        s.commit()


def test_the_owner_sees_a_receipt_to_check_and_marks_the_prepayment_received(business, rt, settings):
    _login_fails.clear()
    slots = tomorrow_slots(business.id)
    sent_receipt, waiting = _chat_booking(business.id, slots[0]), book(business.id, slots[1], name="Бакыт")
    _awaiting(sent_receipt, "check")
    _awaiting(waiting, "awaiting")
    with TestClient(create_app(settings, rt, init=False)) as c:
        token = sign_in(c).json()["token"]
        summary = c.get("/api/mobile/summary", headers=auth(token)).json()
        assert [x["id"] for x in summary["deposits"]] == [sent_receipt]  # only a receipt waits for a person's look
        day = c.get("/api/mobile/bookings", params={"day": "2026-11-05"}, headers=auth(token)).json()["bookings"]
        deposit = {x["id"]: x["deposit"] for x in day}
        assert deposit[waiting] == {"due": 500, "status": "awaiting", "deadline": "2026-11-04T19:14:00Z"}

        r = c.post(f"/api/mobile/bookings/{sent_receipt}/deposit", headers=auth(token))
        assert r.status_code == 200 and r.json()["told"] is True and r.json()["booking"]["deposit"]["status"] == "paid"
        assert rt.tg.sent[-1][0] == "9001" and "Предоплата получена" in rt.tg.sent[-1][1]
        assert c.get("/api/mobile/summary", headers=auth(token)).json()["deposits"] == []
        again = c.post(f"/api/mobile/bookings/{sent_receipt}/deposit", headers=auth(token))
        assert again.status_code == 409 and "уже не ждёт" in again.json()["error"]
        quiet = c.post(f"/api/mobile/bookings/{waiting}/deposit", headers=auth(token)).json()
        assert quiet["told"] is False  # booked without a chat: staff confirm to the customer themselves
    _login_fails.clear()


def test_a_master_marks_only_her_own_and_another_business_none(business, rt, settings):
    _login_fails.clear()
    slots = tomorrow_slots(business.id)
    mine = slots[0]
    other = next(x for x in slots if x.staff_id != mine.staff_id)
    hers, theirs = book(business.id, mine), book(business.id, other, name="Бакыт")
    _awaiting(hers)
    _awaiting(theirs)
    with db.new_session() as s:
        s.add(PanelUser(business_id=business.id, name="Айгерим", login="aigerim", password_hash=hash_password("staff-pass-1"),
                        staff_id=mine.staff_id))
        s.add(Business(slug="other", name="Другая", admin_password_hash=hash_password("other-pass-1")))
        s.commit()
    with TestClient(create_app(settings, rt, init=False)) as c:
        master = sign_in(c, user="aigerim", password="staff-pass-1").json()["token"]
        assert [x["id"] for x in c.get("/api/mobile/summary", headers=auth(master)).json()["deposits"]] == [hers]
        assert c.post(f"/api/mobile/bookings/{theirs}/deposit", headers=auth(master)).status_code == 404
        stranger = sign_in(c, company="other", password="other-pass-1").json()["token"]
        assert c.post(f"/api/mobile/bookings/{hers}/deposit", headers=auth(stranger)).status_code == 404
        assert c.post(f"/api/mobile/bookings/{hers}/deposit", headers=auth(master)).status_code == 200
    with db.new_session() as s:
        assert s.get(Booking, theirs).deposit_status == "check" and s.get(Booking, hers).deposit_status == "paid"
    _login_fails.clear()


def test_a_test_chats_receipt_is_not_on_the_today_screen(business, rt, settings):
    """The panel's test chat books like a customer; its prepayment is not a real one to check."""
    _login_fails.clear()
    slots = tomorrow_slots(business.id)
    test_booking = book(business.id, slots[2], name="Тест", channel="console")
    _awaiting(test_booking, "check")
    with TestClient(create_app(settings, rt, init=False)) as c:
        token = sign_in(c).json()["token"]
        assert c.get("/api/mobile/summary", headers=auth(token)).json()["deposits"] == []
    _login_fails.clear()
