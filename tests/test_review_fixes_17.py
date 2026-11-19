"""Fixes from the independent review of PRs #241–#246.

- Prices: the web menu (#242) and the app (#241) wrote «120 000 сом $» for a dollar listing, the web split «1.500»
  into «1 сом.500», and the two disagreed on «500 KGS», «500 с.», «0 сом»; «от 1 500 до 2 000» read «от 1 500 сом до
  2 000». One rule now, the same in joop/web/menu.py and mobile/lib/core/format.dart.
- A back-in-stock watch kept before #246 on an example item still sent its example price.
- After the owner switched to another bot, the chats linked through the old one still counted as getting alerts.
- «Это наши настоящие данные» also published the demo's address and phone («(демо-адрес)», «555 000 …»).
"""

import re
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlmodel import select

from joop import db, restock, samples
from joop.agent.engine import handle_incoming
from joop.channels.base import IncomingMessage
from joop.dispatch import alert_chats, notify_admins
from joop.models import Business, Conversation, Service, StockWatch
from joop.presets import create_business
from joop.web.app import create_app
from joop.web.menu import price_label
from joop.web.saas import checklist

from .conftest import NOW_UTC
from .test_example_terms import make_the_rows_its_own
from .test_web import csrf_of, login


# --- prices --------------------------------------------------------------------------------------------------------

def test_a_price_reads_the_same_on_the_web_menu_as_in_the_app():
    """The same cases as mobile/test/format_test.dart."""
    cases = {
        "500": "500 сом", "от 3 500": "от 3 500 сом", "3 500 за ночь": "3 500 сом за ночь",
        "800 за 60 минут": "800 сом за 60 минут", "200–300": "200–300 сом", "200 - 300 за час": "200 - 300 сом за час",
        "от 1 500 до 2 000": "от 1 500 до 2 000 сом",  # Altegio's range is one price
        "300 до 5 кг": "300 сом до 5 кг",  # a price and a condition
        "1.500": "1.500 сом", "2.000 за ночь": "2.000 сом за ночь", "от 1.200": "от 1.200 сом", "1,5": "1,5 сом",
        "150 за рубашку": "150 сом за рубашку",  # not roubles
        "500 сом": "500 сом", "500 Сом": "500 Сом", "500 KGS": "500 KGS", "500 с.": "500 с.",
        "78 000 $": "78 000 $", "450 $ в месяц": "450 $ в месяц", "1 200 USD": "1 200 USD", "90 €": "90 €",
        "450 у.е. в месяц": "450 у.е. в месяц", "2 000 руб.": "2 000 руб.", "10 000 тенге": "10 000 тенге",
        "0": "бесплатно", "0 сом": "бесплатно", "по договорённости": "по договорённости", "": "",
    }
    assert {price: price_label(price, "ru") for price in cases} == cases
    assert price_label("0 сом", "ky") == "акысыз" and price_label("500", "ky") == "500 сом"


def test_a_dollar_listing_is_not_shown_in_som(settings, rt, engine):
    with db.new_session() as s:
        b = create_business(s, slug="agency", name="Агентство", password="pass-12345", niche="realty", demo=False, now_utc=NOW_UTC)
        b.menu_enabled = True
        s.add(Service(business_id=b.id, name="Объект 7: 2-комнатная квартира", price="120 000 $", sort=0))
        s.add(Service(business_id=b.id, name="Объект 8: студия", price="1.500", sort=1))
        s.commit()
    with TestClient(create_app(settings, rt, init=False)) as c:
        page = c.get("/m/agency").text
    assert "120 000 $" in page and "сом $" not in page
    assert "1.500 сом" in page and "1 сом.500" not in page


# --- back in stock ---------------------------------------------------------------------------------------------------

def test_a_watch_on_an_example_item_is_closed_without_a_message(settings, rt, engine):
    """A watch the old code kept on a pharmacy demo's masks: once they are back, the customer is not sent their
    example price, and the watch is closed."""
    with db.new_session() as s:
        b = create_business(s, slug="apteka", name="Аптека", password="pass-12345", niche="pharmacy", demo=True, now_utc=NOW_UTC)
        b.telegram_bot_token = "123:TEST"
        masks = s.exec(select(Service).where(Service.business_id == b.id, Service.name.startswith("Маски"))).one()
        own = Service(business_id=b.id, name="Бинт стерильный", price="60", price_value=60, stock=5, sort=99)
        conv = Conversation(business_id=b.id, channel="telegram", chat_id="5551", last_customer_at=NOW_UTC)
        s.add_all([own, conv])
        s.flush()
        s.add(StockWatch(business_id=b.id, conversation_id=conv.id, service_id=masks.id, created_at=NOW_UTC))
        s.add(StockWatch(business_id=b.id, conversation_id=conv.id, service_id=own.id, created_at=NOW_UTC))
        masks.stock, masks.sold_out, masks.available = 20, False, True
        s.add(masks)
        s.commit()
        bid = b.id
    with db.new_session() as s:
        restock.notify_back(s, rt, s.get(Business, bid), NOW_UTC + timedelta(hours=12))
        s.commit()
        assert all(w.notified_at for w in s.exec(select(StockWatch)).all())
    sent = [text for _, text in rt.tg.sent]
    assert not any("Маски" in t for t in sent) and any("Бинт стерильный" in t for t in sent)


# --- alerts after switching bots -------------------------------------------------------------------------------------

def link(business_id: int, chat_id: str) -> str:
    """The owner sends /admin <code> to the business's current bot."""
    with db.new_session() as s:
        b = s.get(Business, business_id)
        code = b.admin_link_code
        out = handle_incoming(s, b, IncomingMessage("telegram", chat_id, "command", f"/admin {code}", "Владелец", f"admin-{chat_id}"),
                              lambda: None, NOW_UTC)
        s.commit()
    return out.reply


def connect(c, token: str, rt, username: str):
    rt.tg.me, rt.tg.set_webhook = {"username": username}, lambda url, secret: True
    return c.post("/panel/setup/telegram", data={"token": token, "csrf": csrf_of(c.get("/panel/channels").text),
                                                 "back": "/panel/channels"})


def _chip(page: str) -> str:
    return re.search(r'<span class="chip[^"]*">Уведомления:[^<]*</span>', page).group(0)


def test_chats_linked_through_another_bot_do_not_count_until_linked_again(business, settings, rt):
    assert link(business.id, "-100777").startswith("Готово.")
    with db.new_session() as s:
        b = s.get(Business, business.id)
        assert (b.admin_chat_ids, b.admin_bot, alert_chats(b)) == ("-100777", "123", ["-100777"])
    old, new = "123:" + "A" * 35, "987654321:" + "B" * 35
    with TestClient(create_app(settings, rt, init=False)) as c:
        token = login(c)
        connect(c, old, rt, "aktish_bot")  # a new token from BotFather for the same bot keeps the chats
        assert _chip(c.get("/panel").text) == '<span class="chip ok">Уведомления: 1</span>'
        c.post("/panel/channels/telegram/disconnect", data={"csrf": token})
        page = re.sub(r"\s+", " ", connect(c, new, rt, "aktish_new_bot").text)
        assert "Чаты для уведомлений были привязаны через прежнего бота" in page
        assert _chip(c.get("/panel").text) == '<span class="chip warn">Уведомления: нет</span>'
        settings_page = re.sub(r"\s+", " ", c.get("/panel/settings").text)
        assert "Чаты привязаны через прежнего бота" in settings_page and "Бот отключён" not in settings_page
        with db.new_session() as s:
            b = s.get(Business, business.id)
            assert alert_chats(b) == [] and not {i["key"]: i for i in checklist(s, b, NOW_UTC)}["admin"]["done"]
            assert notify_admins(rt, b, ["Новая запись"]) == 0 and not rt.tg.sent  # the new bot cannot write there
        assert link(business.id, "5001").startswith("Готово.")  # the owner links again through the new bot
        assert _chip(c.get("/panel").text) == '<span class="chip ok">Уведомления: 1</span>'
    with db.new_session() as s:
        b = s.get(Business, business.id)
        assert (b.admin_chat_ids, b.admin_bot) == ("5001", "987654321")  # the old group cannot get this bot's alerts


def test_chats_linked_before_the_bot_was_recorded_still_count(business):
    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.admin_chat_ids, b.telegram_bot_token = "111", "555:" + "C" * 35  # linked before 0063: admin_bot unknown
        assert alert_chats(b) == ["111"]


# --- the example's contacts are never confirmed ----------------------------------------------------------------------

def test_the_demo_address_and_phone_are_never_published_by_the_confirm_button(settings, rt, engine):
    with db.new_session() as s:
        b = create_business(s, slug="bereke", name="Береке", password="pass-12345", niche="restaurant", demo=True, now_utc=NOW_UTC)
        b.menu_enabled = True
        s.commit()
        make_the_rows_its_own(s, b.id)
    with TestClient(create_app(settings, rt, init=False)) as c:
        c.post("/login", data={"slug": "bereke", "password": "pass-12345", "csrf": csrf_of(c.get("/login").text)})
        home = re.sub(r"\s+", " ", c.get("/panel").text)
        assert ('<a href="/panel/settings">Контакты</a>: адрес, телефон, описание компании — придуманы для примера: '
                "впишите свои") in home
        assert "Это наши настоящие данные" in home and "(кнопка ниже их не подтвердит, а уберёт)" in home
        settings_page = re.sub(r"\s+", " ", c.get("/panel/settings").text)
        assert "Ещё из примера: адрес, телефон, описание компании, часы работы, порядок записи, условия заказа." in settings_page
        assert "Контакты из примера придуманы — впишите свои." in settings_page and "Часы и правила впишите сами" in settings_page
        page = re.sub(r"\s+", " ", c.post("/panel/example/ok", data={"csrf": csrf_of(home)}).text)
        assert "Адрес, телефон, описание компании из примера убраны — впишите свои в «Настройках»." in page
        menu = c.get("/m/bereke").text
        assert "демо-адрес" not in menu and "555 000 002" not in menu and "(демо)" not in menu
        home = re.sub(r"\s+", " ", c.get("/panel").text)
        assert "Часть данных — ещё пример" not in home  # the rest is the café's own now
    with db.new_session() as s:
        b = s.get(Business, s.exec(select(Business.id).where(Business.slug == "bereke")).one())
        assert (b.address, b.phone, b.description) == ("", "", "") and samples.example_terms(b) == frozenset()
        assert b.hours_text and samples.customer_hours(b) == b.hours_text  # the hours were confirmed, not cleared
        contacts = next(i for i in checklist(s, b, NOW_UTC) if i["key"] == "contacts")
        assert not contacts["done"] and "Осталось указать: адрес, телефон." in contacts["hint"]


def test_only_the_demo_contacts_left_shows_no_confirm_button(settings, rt, engine):
    """Rows, hours and rules are the owner's own; only the demo's address is left: there is nothing to confirm."""
    with db.new_session() as s:
        b = create_business(s, slug="bereke", name="Береке", password="pass-12345", niche="restaurant", demo=True, now_utc=NOW_UTC)
        b.phone, b.description, b.hours_text = "+996 700 123 456", "Кафе национальной кухни", "Ежедневно 10:00–22:00"
        b.booking_policy, b.delivery_fee = "Стол держим 20 минут.", 200
        s.commit()
        make_the_rows_its_own(s, b.id)
        assert samples.left(s, s.get(Business, b.id)).contacts == ["адрес"] and not samples.left(s, s.get(Business, b.id)).confirmable
    with TestClient(create_app(settings, rt, init=False)) as c:
        c.post("/login", data={"slug": "bereke", "password": "pass-12345", "csrf": csrf_of(c.get("/login").text)})
        home = re.sub(r"\s+", " ", c.get("/panel").text)
    assert '<a href="/panel/settings">Контакты</a>: адрес — придуманы для примера: впишите свои</li>' in home
    assert "Это наши настоящие данные" not in home
