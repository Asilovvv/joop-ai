"""Independent review of #311–#319.

1. #313 marked every booking made on the public page from a logged-in browser as a test. The panel has no other booking
   form, and the page tells staff «запись будет настоящей»: a receptionist booking a caller there lost her from the
   app's «Записи», «Касса», reminders and the digest, while her time stayed taken. Such a booking is real now, only
   kept out of «Первый настоящий клиент» (`Booking.by_staff`) — also after «Напомнить в Telegram», which overwrote
   the test mark and made the owner's own try count as the first customer.
2. #318 cut a hall's seats to 500 when added or edited in the app; the panel takes any number and wedding halls seat
   800 or more.
"""

import re
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlmodel import select

from joop import cash, db
from joop.agent.engine import handle_incoming
from joop.channels.base import IncomingMessage
from joop.models import Booking, Business, Slot, Staff
from joop.scheduler import send_reminders
from joop.web.app import create_app
from joop.web.saas import checklist

from .conftest import NOW_UTC
from .test_booking_page import LOCAL, _book, _first_time, _open, form_clock  # noqa: F401 - the form's clock
from .test_mobile import auth, sign_in
from .test_web import login


def _first_customer(business_id: int) -> bool:
    with db.new_session() as s:
        return next(x for x in checklist(s, s.get(Business, business_id), NOW_UTC) if x["key"] == "real")["done"]


def test_a_caller_booked_by_staff_on_the_page_is_a_real_booking(business, settings, rt):
    _open(business.id)
    with TestClient(create_app(settings, rt, init=False)) as c:
        login(c)
        assert "запись будет настоящей" in c.get("/m/aktish/book").text
        assert _book(c, _first_time(c), name="Гульнара", phone="0700 999 888").status_code == 303
        h = auth(sign_in(c).json()["token"])
        with db.new_session() as s:
            x = s.exec(select(Booking).where(Booking.customer_name == "Гульнара")).one()
            assert (x.by_staff, x.channel) == (True, "")
            day = x.start.date().isoformat()
        listed = c.get("/api/mobile/bookings", headers=h, params={"day": day}).json()["bookings"]
        assert [b["customer"]["name"] for b in listed] == ["Гульнара"]
        assert c.get("/api/mobile/summary", headers=h).json()["week"] == 1
    with db.new_session() as s:
        b = s.get(Business, business.id)
        x = s.exec(select(Booking).where(Booking.customer_name == "Гульнара")).one()
        assert [r.customer_name for r in cash._visits(s, b, x.start - timedelta(hours=1), x.start + timedelta(hours=1))] \
            == ["Гульнара"]
        assert send_reminders(s, rt, b, x.start - timedelta(hours=24)) == {"sent": 0, "manual": 1}  # no chat: staff call
    assert _first_customer(business.id) is False  # staff booked her: not a customer finding the page by herself


def test_remind_in_telegram_does_not_turn_the_owners_try_into_the_first_customer(business, settings, rt):
    _open(business.id)
    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.telegram_bot_username = "aktish_bot"
        s.add(b)
        s.commit()
        later = LOCAL.date() + timedelta(days=2)
        slot = next(x for x in s.exec(select(Slot).where(Slot.business_id == business.id, Slot.status == "free")
                                      .order_by(Slot.start)).all() if x.start.date() == later)
    with TestClient(create_app(settings, rt, init=False)) as c:
        login(c)
        page = c.get(_book(c, slot.id).headers["location"]).text
        link = re.search(r'href="https://t\.me/aktish_bot\?start=(b\d+_[0-9a-f]+)"', page)
        assert link
    with db.new_session() as s:
        handle_incoming(s, s.get(Business, business.id),
                        IncomingMessage("telegram", "4242", "command", f"/start {link.group(1)}", "Owner", "r1"),
                        lambda: None, NOW_UTC)
        s.commit()
        x = s.exec(select(Booking).where(Booking.source == "page")).one()
        assert (x.channel, x.chat_id, x.by_staff) == ("telegram", "4242", True)  # still staff's booking, not the customer's
        # the step's page-booking count (saas.checklist) leaves it out; the owner's own Telegram chat with the bot is a
        # chat like any other (only the panel's test link makes a test chat), and counts as it did before #313
        counted = s.exec(select(Booking).where(Booking.business_id == business.id, Booking.source == "page",
                                               Booking.by_staff == False)).all()  # noqa: E712
        assert counted == []


def test_a_wedding_hall_keeps_its_800_seats_from_the_app(engine, settings, rt):
    hall = {"name": "Тойкана Ак-Сай", "niche": "banquet", "phone": "0555 333 444", "password": "toi-pass-2026",
            "contact_name": "Бакыт"}
    with TestClient(create_app(settings, rt, init=False)) as c:
        h = auth(c.post("/api/mobile/signup", json=hall).json()["token"])
        c.post("/api/mobile/staff/example/delete", headers=h)
        r = c.post("/api/mobile/staff", headers=h, json={"name": "Большой зал", "role": "зал", "capacity": 800}).json()
        row = next(x for x in r["staff"] if x["name"] == "Большой зал")
        assert row["capacity"] == 800
        r = c.post(f"/api/mobile/staff/{row['id']}", headers=h,
                   json={"name": "Большой зал «Ала-Тоо»", "role": "зал", "capacity": 800, "group_size": 0}).json()
        assert [x["capacity"] for x in r["staff"] if x["id"] == row["id"]] == [800]
    with db.new_session() as s:
        assert s.get(Staff, row["id"]).capacity == 800
