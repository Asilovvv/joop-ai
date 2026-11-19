"""Fixes from the independent review of #241-#247."""

import re
from datetime import timedelta

from fastapi.testclient import TestClient

from joop import api, broadcasts, db
from joop.models import Business
from joop.presets import create_business
from joop.timeutil import utc_to_local
from joop.web.app import create_app
from joop.web.menu import price_label

from .conftest import NOW_UTC
from .test_broadcasts import DAY, person
from .test_web import csrf_of, login

LOCAL = utc_to_local(NOW_UTC, "Asia/Bishkek")


def _set(business_id: int, **fields) -> None:
    with db.new_session() as s:
        b = s.get(Business, business_id)
        for k, v in fields.items():
            setattr(b, k, v)
        s.add(b)
        s.commit()


def _preview(business_id: int) -> broadcasts.Preview:
    with db.new_session() as s:
        return broadcasts.preview(s, s.get(Business, business_id), "all", "", DAY)


# --- 1. a broadcast goes out only through a connected channel (#245 fixed the test button, not the count) ------------


def test_a_broadcast_counts_only_customers_of_connected_channels(business):
    person(business.id, "t1")
    person(business.id, "w1", channel="whatsapp", wrote=DAY - timedelta(hours=2))
    _set(business.id, wa_phone_number_id="", wa_access_token="")
    p = _preview(business.id)
    assert (p.telegram, p.window, p.off, p.reachable) == (1, 0, 1, 1)  # WhatsApp is not connected
    _set(business.id, telegram_bot_token="")  # «Отключить бота»
    p = _preview(business.id)
    assert (p.telegram, p.window, p.off, p.reachable) == (0, 0, 2, 0)
    with db.new_session() as s:
        item, error = broadcasts.start(s, s.get(Business, business.id), "Скидка", "", "all", "", True, DAY)
    assert item is None and error == "В этой группе сейчас некому отправить."


def test_the_panel_says_who_will_not_get_it_and_where_the_result_goes(business, settings, rt, monkeypatch):
    import joop.web.broadcasts as page

    monkeypatch.setattr(page, "utcnow", lambda: DAY)
    person(business.id, "t1")
    person(business.id, "w1", channel="whatsapp", wrote=DAY - timedelta(hours=2))
    _set(business.id, telegram_bot_token="", admin_chat_ids="999", wa_phone_number_id="555", wa_access_token="wa-test")
    with TestClient(create_app(settings, rt, init=False)) as c:
        token = login(c)
        form = {"csrf": token, "segment": "all", "text": "Свободные окна в субботу", "text_ky": ""}
        html = re.sub(r"\s+", " ", c.post("/panel/broadcasts", data={**form, "action": "preview"}).text)
        assert "Отправить 1 клиентам" in html and "<b>1</b><span>не получат: канал отключён (Telegram)</span>" in html
        assert c.post("/panel/broadcasts", data={**form, "action": "send"}, follow_redirects=False).status_code == 303
        html = re.sub(r"\s+", " ", c.get("/panel/broadcasts").text)
    assert "Рассылка запущена: 1 клиентам" in html
    assert "итог придёт вам в Telegram" not in html and "итог будет здесь, в истории рассылок" in html


def test_empty_pages_promise_telegram_only_when_alerts_arrive(business, settings, rt):
    _set(business.id, admin_chat_ids="999")
    with TestClient(create_app(settings, rt, init=False)) as c:
        login(c)
        assert "и придёт вам в Telegram" in re.sub(r"\s+", " ", c.get("/panel").text)
        _set(business.id, telegram_bot_token="")
        page = re.sub(r"\s+", " ", c.get("/panel").text)
    assert "Записей пока нет" in page and "придёт в Telegram" not in page and "придёт вам в Telegram" not in page


# --- 2, 3. the menu's prices: the business's own currency, decimals, a quantity before the price -------------------


def test_menu_price_keeps_another_currency():
    for price in ("120 000 $", "450 $ в месяц", "$300", "100 USD", "50 €", "1 000 ₸", "500 руб", "90 000 тенге", "300 KGS"):
        assert price_label(price, "ru") == price, price


def test_menu_price_with_decimals_and_a_quantity_first():
    assert price_label("1,500", "ru") == "1,500 сом"
    assert price_label("1.500", "ru") == "1.500 сом"
    assert price_label("2,5", "ru") == "2,5 сом"
    assert price_label("1 кг — 450", "ru") == "1 кг — 450 сом"
    assert price_label("0,5 л — 120", "ru") == "0,5 л — 120 сом"
    assert price_label("60 минут — 1 200", "ru") == "60 минут — 1 200 сом"
    assert price_label("2 часа", "ru") == "2 часа"  # no price in it: left as written
    # unchanged from #242
    assert price_label("3 500 за ночь", "ru") == "3 500 сом за ночь"
    assert price_label("800 за 60 минут", "ru") == "800 сом за 60 минут"
    assert price_label("1 500–2 000", "ru") == "1 500–2 000 сом" and price_label("от 3 500", "ru") == "от 3 500 сом"


# --- 4. a far day is refused out loud, as MCP does, not answered with «no free time» -----------------------------


def test_slots_for_a_day_out_of_range_is_an_error_not_an_empty_list(business, settings, rt):
    with db.new_session() as s:
        b = s.get(Business, business.id)
        key = api.new_key(b)
        b.api_booking = True
        s.add(b)
        s.commit()
    auth = {"Authorization": f"Bearer {key}"}
    with TestClient(create_app(settings, rt, init=False)) as c:
        for far in (LOCAL.date() + timedelta(days=api.DAY_AHEAD + 1), LOCAL.date() - timedelta(days=1)):
            r = c.get(f"/api/v1/slots?date={far:%Y-%m-%d}", headers=auth)
            assert r.status_code == 400 and r.json()["error"] == f"date must be from today to {api.DAY_AHEAD} days ahead"
        assert c.get("/api/v1/slots?date=9999-12-31", headers=auth).status_code == 400
        assert c.get(f"/api/v1/slots?date={LOCAL.date() + timedelta(days=api.DAY_AHEAD):%Y-%m-%d}", headers=auth).status_code == 200
        login(c)
        assert f"до {api.DAY_AHEAD} дней вперёд" in c.get("/panel/api").text


# --- 5. the menu page tells the owner where the button really leads ---------------------------------------------


def _fresh_menu(niche: str = "dental", **changes) -> int:
    with db.new_session() as s:
        b = create_business(s, slug="fresh", name="Свежая", password="fresh-pass", niche=niche, demo=True, now_utc=NOW_UTC)
        b.menu_enabled = True
        for k, v in changes.items():
            setattr(b, k, v)
        s.commit()
        return b.id


def _hint(settings, rt) -> str:
    with TestClient(create_app(settings, rt, init=False)) as c:
        c.post("/login", data={"slug": "fresh", "password": "fresh-pass", "csrf": csrf_of(c.get("/login").text)})
        page = re.sub(r"\s+", " ", c.get("/panel/menu").text)
    return re.search(r"Пусто — [^<]*", page).group(0)


def test_menu_hint_follows_the_button(settings, rt, engine):
    _fresh_menu()  # the example's phone, the AI on, nothing connected: the button opens the chat on the site
    hint = _hint(settings, rt)
    assert "в чат на сайте" in hint and "WhatsApp" not in hint
    assert "телефон в настройках — из примера" in hint


def test_menu_hint_without_the_ai_and_a_phone(settings, rt, engine):
    _fresh_menu(bot_enabled=False)
    assert "кнопки не будет" in _hint(settings, rt)


def test_menu_hint_with_the_owners_phone(settings, rt, engine):
    _fresh_menu(niche="restaurant", phone="+996 700 123 456", bot_enabled=False)
    assert "в WhatsApp на номер +996 700 123 456" in _hint(settings, rt)
