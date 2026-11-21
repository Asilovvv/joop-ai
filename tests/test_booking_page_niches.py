"""The booking page in every niche that books a time: the walk a customer takes, end to end."""

import re

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from joop import db
from joop.models import Booking, Business, Slot, Staff
from joop.niches import all_packs, get_pack
from joop.presets import create_business
from joop.web.app import create_app

from .conftest import NOW_UTC
from .test_booking_page import CLOCK, form_clock  # noqa: F401 - the form's clock

BOOKING_NICHES = sorted(n for n in all_packs() if get_pack(n).has("booking"))


@pytest.mark.parametrize("niche", BOOKING_NICHES)
def test_a_customer_books_on_the_page(niche, engine, settings, rt):
    with db.new_session() as s:
        b = create_business(s, slug=f"page-{niche}", name="Тест", password="pass-12345", niche=niche, demo=True, now_utc=NOW_UTC)
        b.example_ok, b.menu_enabled, b.page_booking = True, True, True  # the owner kept the example as their own
        s.add(b)
        s.commit()
        bid = b.id
    pack = get_pack(niche)
    with TestClient(create_app(settings, rt, init=False)) as c:
        menu = c.get(f"/m/page-{niche}").text
        assert "Записаться онлайн" in menu and menu.count(f"/m/page-{niche}/book?slot=") == 3, niche
        page = c.get(f"/m/page-{niche}/book").text
        assert f"<h2>{pack.resource_label}</h2>" in page or "?staff=" not in page, niche
        slot_id = int(re.search(r'href="\?slot=(\d+)"', page).group(1))
        times = re.findall(r'href="\?slot=\d+">(\d\d:\d\d)</a>', page)
        assert times == sorted(times) and len(set(times)) == len(times), niche  # «Любой»: one per start, in order
        form = c.get(f"/m/page-{niche}/book?slot={slot_id}").text
        fields = dict(re.findall(r'<input type="hidden" name="(slot|t|lang)" value="([^"]*)"', form))
        with db.new_session() as s:
            member = s.get(Staff, s.get(Slot, slot_id).staff_id)
        assert ('name="party"' in form) == (member.capacity > 1), niche
        CLOCK["t"] += 5
        done = c.post(f"/m/page-{niche}/book", data={**fields, "name": "Айбек", "phone": "0555123456",
                                                      "party": str(min(2, member.capacity or 1))}, follow_redirects=False)
        assert done.status_code == 303, (niche, done.text[:300])
        assert "Вы записаны" in c.get(done.headers["location"]).text, niche
    with db.new_session() as s:
        x = s.exec(select(Booking).where(Booking.business_id == bid)).one()
        assert (x.source, x.slot_id, x.status) == ("page", slot_id, "booked"), niche


def test_niches_without_times_have_no_booking_page(engine, settings, rt):
    others = sorted(n for n in all_packs() if not get_pack(n).has("booking"))
    assert others  # shops, hotels, delivery: they order or stay, the page keeps «Написать»
    with db.new_session() as s:
        b = create_business(s, slug="page-shop", name="Тест", password="pass-12345", niche=others[0], demo=True, now_utc=NOW_UTC)
        b.example_ok, b.menu_enabled, b.page_booking = True, True, True
        s.add(b)
        s.commit()
    with TestClient(create_app(settings, rt, init=False)) as c:
        assert c.get("/m/page-shop/book", follow_redirects=False).headers["location"] == "/m/page-shop"
        assert "Записаться онлайн" not in c.get("/m/page-shop").text
