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
    assert label == "Задать вопрос" and url.startswith("https://wa.me/")
    assert order_link(Business(slug="y", name="Y", niche="dental"), "ru", None) == ("", "")
