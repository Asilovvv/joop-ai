"""Independent review of #301–#310: a booking made on the business's own booking page from a browser logged in to the
panel (the owner trying it, staff booking a caller) must not tick «Первый настоящий клиент» in the launch steps
(panel, app, the founder's call list). Since the review of #311–#319 it stays a real booking (`by_staff`), not a test
one: a caller booked there is a real customer for reminders, «Касса» and the lists (test_review_fixes_26.py). A
customer booking from their own browser still ticks the step."""

from fastapi.testclient import TestClient
from sqlmodel import select

from joop import db
from joop.models import Booking, Business
from joop.web.app import create_app
from joop.web.saas import checklist

from .conftest import NOW_UTC
from .test_booking_page import _book, _first_time, _open, form_clock  # noqa: F401 - the form's clock
from .test_web import login


def _first_customer(business_id: int) -> bool:
    with db.new_session() as s:
        return next(x for x in checklist(s, s.get(Business, business_id), NOW_UTC) if x["key"] == "real")["done"]


def test_the_owners_own_page_booking_is_a_check_not_the_first_customer(business, settings, rt):
    _open(business.id)
    assert _first_customer(business.id) is False
    with TestClient(create_app(settings, rt, init=False)) as c:
        login(c)
        assert "Вы вошли в панель этой компании" in c.get("/m/aktish/book").text
        done = _book(c, _first_time(c))
        assert done.status_code == 303 and "Вы записаны" in c.get(done.headers["location"]).text
        with db.new_session() as s:
            own = s.exec(select(Booking).where(Booking.business_id == business.id, Booking.source == "page")).one()
            assert (own.by_staff, own.channel, own.status) == (True, "", "booked")  # real: it holds the time
        assert _first_customer(business.id) is False
        setup = c.get("/panel/setup").text
        assert "Первый настоящий клиент" in setup
    with TestClient(create_app(settings, rt, init=False)) as customer:  # no panel cookie: a customer
        done = _book(customer, _first_time(customer), name="Айгуль", phone="0700 111 222")
        assert done.status_code == 303
    with db.new_session() as s:
        theirs = s.exec(select(Booking).where(Booking.business_id == business.id, Booking.customer_name == "Айгуль")).one()
        assert (theirs.by_staff, theirs.channel) == (False, "")
    assert _first_customer(business.id) is True
