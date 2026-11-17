"""The rest of the independent review of #234-#240 (#241 fixed the menu's address, phone and order button)."""

from datetime import date

from fastapi.testclient import TestClient

from joop import api, db
from joop.models import Business
from joop.presets import create_business
from joop.timeutil import utc_to_local
from joop.web.app import create_app
from joop.web.menu import price_label

from .conftest import NOW_UTC
from .test_web import csrf_of

LOCAL = utc_to_local(NOW_UTC, "Asia/Bishkek")


def _fresh(**changes) -> int:
    with db.new_session() as s:
        b = create_business(s, slug="fresh", name="Свежая", password="fresh-pass", niche="restaurant", demo=True, now_utc=NOW_UTC)
        b.menu_enabled = True
        for k, v in changes.items():
            setattr(b, k, v)
        s.commit()
        return b.id


def test_public_menu_shows_no_example_hours_but_the_owners_own(settings, rt, engine):
    bid = _fresh()
    with TestClient(create_app(settings, rt, init=False)) as c:
        assert "доставка 11:00–22:00" not in c.get("/m/fresh").text
        with db.new_session() as s:
            b = s.get(Business, bid)
            b.hours_text = "Пн–Пт 9–18"
            s.add(b)
            s.commit()
        assert "Пн–Пт 9–18" in c.get("/m/fresh").text


def test_customer_card_link_does_not_lead_to_the_example_phone(settings, rt, engine):
    _fresh(wa_phone_number_id="1", wa_access_token="t")
    with TestClient(create_app(settings, rt, init=False)) as c:
        token = csrf_of(c.get("/login").text)
        c.post("/login", data={"slug": "fresh", "password": "fresh-pass", "csrf": token})
        page = c.get("/panel/card?via=whatsapp").text
    assert "996555000002" not in page


def test_menu_price_puts_som_after_the_price_not_after_the_unit():
    assert price_label("3 500 за ночь", "ru") == "3 500 сом за ночь"
    assert price_label("800 за 60 минут", "ru") == "800 сом за 60 минут"
    assert price_label("1 500–2 000", "ru") == "1 500–2 000 сом"
    assert price_label("от 3 500", "ru") == "от 3 500 сом" and price_label("350", "ru") == "350 сом"
    assert price_label("350 сом", "ru") == "350 сом" and price_label("договорная", "ru") == "договорная"


def test_slots_for_a_day_beyond_sixty_days_is_empty_not_an_error(business, engine):
    with db.new_session() as s:
        b = s.get(Business, business.id)
        assert api.free_slots(s, b, date(9999, 12, 31), LOCAL) == []
        assert api.free_slots(s, b, LOCAL.date().replace(year=LOCAL.year + 1), LOCAL) == []
