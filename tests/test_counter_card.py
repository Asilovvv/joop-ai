"""The printable card for the counter: a QR to the chat, «отвечает Joop AI» (joop/web/card.py)."""

from fastapi.testclient import TestClient
from sqlmodel import select

from joop import db
from joop.models import Business
from joop.web.app import create_app

from .test_web import login


def test_card_points_to_the_chat_the_owner_picks_and_carries_joops_name(business, rt, settings):
    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.phone, b.telegram_bot_username = "+996 555 000 111", "aktish_bot"
        b.wa_phone_number_id, b.wa_access_token = "pn1", "tok"  # the WhatsApp link only where Joop answers in WhatsApp
        s.add(b)
        s.commit()
    with TestClient(create_app(settings, rt, init=False)) as c:
        login(c)
        page = c.get("/panel/card").text
        assert "Запись 24/7" in page and "Отвечает <b>Joop AI</b>" in page and "<svg" in page
        assert "https://t.me/aktish_bot" in page  # the Telegram bot first when it is connected
        assert 'href="/panel/card?via=telegram"' in page and 'href="/panel/card?via=whatsapp"' in page
        assert "https://joop.test/c/aktish" in c.get("/panel/card?via=web").text  # the web chat always exists
        assert "https://wa.me/996555000111" in c.get("/panel/card?via=whatsapp").text
        assert "Жазылуу 24/7" in page  # the Kyrgyz line too
    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.phone, b.telegram_bot_username = "", ""
        s.add(b)
        s.commit()
    with TestClient(create_app(settings, rt, init=False)) as c:
        login(c)
        page = c.get("/panel/card?via=telegram").text  # nothing to point at: falls back to the web chat, says why
        assert "https://joop.test/c/aktish" in page and "Telegram-бот ещё не подключён" in page


def test_connecting_telegram_remembers_the_bot_username(business, rt, settings):
    import dataclasses

    from .test_web import csrf_of

    rt.settings = dataclasses.replace(settings, public_base_url="https://joop.test")
    rt.tg.get_me = lambda: {"username": "aktish_bot"}
    rt.tg.set_webhook = lambda url, secret: True
    with TestClient(create_app(rt.settings, rt, init=False)) as c:
        token = login(c)
        r = c.post("/panel/channels/telegram/webhook", data={"csrf": token}, follow_redirects=True)
        assert "@aktish_bot подключён" in r.text
        with db.new_session() as s:
            assert s.get(Business, business.id).telegram_bot_username == "aktish_bot"


def test_printable_pages_fit_a_phone_screen_and_keep_their_print_size(business, rt, settings):
    """The A5 card and the A4 sticker sheet have a fixed width for print; on a phone they used to run off the
    right edge (found by the page audit at 390 px). The phone layout applies to the screen only."""
    import re

    with TestClient(create_app(settings, rt, init=False)) as c:
        login(c)
        for url, print_size in (("/panel/card", "size: A5"), ("/panel/sticker", "size: A4")):
            page = c.get(url).text
            assert print_size in page
            phone = re.search(r"@media screen and \(max-width: \d+px\) \{(.*?)\n\s*\}", page, re.S)
            assert phone, url
            assert "width: auto" in phone.group(1) and "height: auto" in phone.group(1), url
