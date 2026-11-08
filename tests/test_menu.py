import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from joop import db
from joop.models import Business, Service
from joop.presets import create_business
from joop.web.app import create_app
from joop.web.menu import order_link, price_label

from .conftest import NOW_UTC
from .test_web import csrf_of


@pytest.fixture
def cafe(engine):
    with db.new_session() as s:
        b = create_business(s, slug="cafe", name="Кафе Ала-Тоо", password="cafe-pass", niche="restaurant", demo=True, now_utc=NOW_UTC)
        b.phone = "+996 555 000 111"
        b.example_ok = True  # this cafe's menu is its own (it equals the restaurant example)
        s.add(b)
        s.commit()
        return b


@pytest.fixture
def client(settings, rt, cafe):
    with TestClient(create_app(settings, rt, init=False)) as c:
        yield c


def login(client):
    token = csrf_of(client.get("/login").text)
    client.post("/login", data={"slug": "cafe", "password": "cafe-pass", "csrf": token})
    return csrf_of(client.get("/panel/menu").text)


def test_price_label():
    assert price_label("350", "ru") == "350 сом" and price_label("от 3 500", "ru") == "от 3 500 сом"
    assert price_label("0", "ky") == "акысыз" and price_label("350 сом", "ru") == "350 сом" and price_label("", "ru") == ""


def test_menu_is_off_until_enabled_then_public(client, cafe):
    assert client.get("/m/cafe").status_code == 404
    token = login(client)
    page = client.get("/panel/menu")
    assert "QR-меню" in page.text and "<svg" in page.text
    r = client.post("/panel/menu", data={"enabled": "1", "chat_url": "javascript:alert(1)", "csrf": token})
    assert "не сохранена" in r.text
    with db.new_session() as s:
        plov = s.exec(select(Service).where(Service.business_id == cafe.id, Service.name == "Плов")).one()
        plov.available = False  # stop list
        s.add(plov)
        s.commit()
    menu = client.get("/m/cafe?t=5")
    assert menu.status_code == 200 and "Кафе Ала-Тоо" in menu.text and "Стол 5" in menu.text
    assert "Лагман" in menu.text and "320 сом" in menu.text and "Сейчас нет" in menu.text
    # No chat link saved: WhatsApp to the company phone with the table number.
    assert "https://wa.me/996555000111?text=%D0%A1%D1%82%D0%BE%D0%BB%205%3A%20" in menu.text
    ky = client.get("/m/cafe?lang=ky")
    assert "Палоо" in ky.text and "Азыр жок" in ky.text
    client.post("/panel/menu", data={"enabled": "1", "chat_url": "https://t.me/cafe_bot", "csrf": token})
    assert 'href="https://t.me/cafe_bot"' in client.get("/m/cafe").text
    svg = client.get("/m/cafe/qr.svg?t=3")
    assert svg.headers["content-type"].startswith("image/svg+xml") and "/m/cafe?t=3" in svg.text
    sheet = client.get("/panel/menu/print?tables=3")
    assert sheet.text.count("<svg") == 4 and "Стол 3" in sheet.text


def test_print_sheet_needs_enabled_menu_and_login(client):
    assert client.get("/panel/menu/print", follow_redirects=False).headers["location"] == "/login"
    login(client)
    assert "Сначала включите" in client.get("/panel/menu/print?tables=2").text


def test_order_link_label_depends_on_niche(engine):
    b = Business(slug="x", name="X", niche="dental", phone="0555 123 456")
    url, label = order_link(b, "ru", 2)
    assert label == "Записаться" and url.startswith("https://wa.me/")  # a booking niche: the button books
    assert order_link(Business(slug="y", name="Y", niche="dental"), "ru", None) == ("", "")


def test_booking_page_shows_masters_nearest_times_and_where_to_write(settings, rt, business):
    """For a booking niche the public price page is the booking page: masters, three nearest free times, the connected channels."""
    from .test_web import login as panel_login

    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.menu_enabled, b.telegram_bot_username = True, "aktish_bot"
        s.add(b)
        s.commit()
    with TestClient(create_app(settings, rt, init=False)) as c:
        page = c.get("/m/aktish").text
        assert "Ближайшее свободное время" in page and "<h2>Врачи</h2>" in page and "Написать и записаться · Telegram" in page
        assert "Чат на сайте" in page and "wa.me" not in page  # WhatsApp is not connected: no link to a landline
        assert "Отвечает ИИ-администратор" in page and 'name="description"' in page
        assert page.count('class="chips"') == 1 and page.split('class="chips"')[1].count("<span>") == 3
        panel_login(c)
        assert "публичная страница записи" in c.get("/panel/menu").text


def test_public_page_never_shows_the_sign_up_example(settings, rt, engine):
    """A new business that opens the page before replacing the example: customers saw «Плов — 300 сом» and example
    tables or masters with their free times. Now only its own rows, and the panel says what is hidden."""
    with db.new_session() as s:
        b = create_business(s, slug="lotos", name="Салон Лотос", password="lotos-pass", niche="beauty", demo=True, now_utc=NOW_UTC)
        b.menu_enabled = True
        s.add(b)
        s.add(Service(business_id=b.id, name="Маникюр Алины", price="900"))
        s.commit()
        example_names = [r.name for r in s.exec(select(Service).where(Service.business_id == b.id)).all() if r.name != "Маникюр Алины"]
    with TestClient(create_app(settings, rt, init=False)) as c:
        page = c.get("/m/lotos").text
        assert "Маникюр Алины" in page and not any(n in page for n in example_names)
        assert "Ближайшее свободное время" not in page and "<h2>Мастера</h2>" not in page  # example masters and their times
        token = csrf_of(c.get("/login").text)
        c.post("/login", data={"slug": "lotos", "password": "lotos-pass", "csrf": token})
        panel = c.get("/panel/menu").text
        assert "На странице не видны позиции из примера" in panel and "мастера из примера" in panel
