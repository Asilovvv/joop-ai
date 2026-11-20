"""Booking by link without a chat (/m/<slug>/book): the best no-key idea of the 19.11 world scan (Altegio's online
booking). Off until the owner turns it on; then a customer picks a time, gives a name and a phone, and the booking is
in the schedule under the AI's rules, with a note to staff and a calendar file for the customer."""

import re
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from joop import api, db, page_booking as pb
from joop.models import Booking, Business, Service, Slot, Staff, Subscription
from joop.presets import create_business
from joop.slots import claim_slot, seats_needed
from joop.timeutil import utc_to_local
from joop.web import booking_page
from joop.web.app import create_app

from .conftest import NOW_UTC
from .test_web import csrf_of, login

LOCAL = utc_to_local(NOW_UTC, "Asia/Bishkek")
CLOCK = {"t": 1_800_000_000.0}


@pytest.fixture(autouse=True)
def form_clock(monkeypatch):
    """The form's age is wall-clock seconds: the tests move this clock instead of sleeping."""
    CLOCK["t"] = 1_800_000_000.0
    monkeypatch.setattr(booking_page, "_now", lambda: CLOCK["t"])


def _open(business_id: int, page_booking: bool = True) -> None:
    with db.new_session() as s:
        b = s.get(Business, business_id)
        b.menu_enabled, b.page_booking, b.admin_chat_ids = True, page_booking, "555"
        s.add(b)
        s.commit()


def _form(html: str) -> dict:
    fields = dict(re.findall(r'<input type="hidden" name="(slot|t|lang)" value="([^"]*)"', html))
    assert set(fields) == {"slot", "t", "lang"}, "no booking form on the page"
    return fields


def _first_time(client, path: str = "/m/aktish/book") -> int:
    page = client.get(path).text
    found = re.search(r'href="\?slot=(\d+)', page)
    assert found, "no free time on the page"
    return int(found.group(1))


def _book(client, slot_id: int, wait: float = 5, **data):
    fields = _form(client.get(f"/m/aktish/book?slot={slot_id}").text)
    CLOCK["t"] += wait
    return client.post("/m/aktish/book", data={**fields, "name": "Айбек", "phone": "0555 123 456", **data},
                       follow_redirects=False)


def test_off_until_the_owner_turns_it_on_in_the_panel(business, settings, rt):
    _open(business.id, page_booking=False)
    with TestClient(create_app(settings, rt, init=False)) as c:
        assert c.get("/m/aktish/book", follow_redirects=False).headers["location"] == "/m/aktish"
        assert "Записаться онлайн" not in c.get("/m/aktish").text
        token = login(c)
        panel = c.get("/panel/menu").text
        assert "Клиенты записываются сами" in panel and 'name="self_booking"' in panel
        c.post("/panel/menu", data={"enabled": "1", "chat_url": "", "self_booking": "1", "csrf": token})
        with db.new_session() as s:
            assert s.get(Business, business.id).page_booking is True
        assert "Ссылка для записи" in c.get("/panel/menu").text and "https://joop.test/m/aktish/book" in c.get("/panel/menu").text
        page = c.get("/m/aktish").text
        # the main button books on the page; each of the three nearest times opens its own form
        assert '<a href="https://joop.test/m/aktish/book" rel="noopener">Записаться онлайн</a>' in page
        assert page.count('href="https://joop.test/m/aktish/book?slot=') == 3
        assert "Вы вошли в панель этой компании" in c.get("/m/aktish/book").text  # the owner trying it sees it is real


def test_a_customer_books_a_free_time_without_a_chat(business, settings, rt):
    _open(business.id)
    with db.new_session() as s:
        service = s.exec(select(Service).where(Service.business_id == business.id, Service.available == True)  # noqa: E712
                         .order_by(Service.id)).first()
    with TestClient(create_app(settings, rt, init=False)) as c:
        page = c.get("/m/aktish/book").text
        assert "Запись онлайн" in page and "<h2>Врачи</h2>" in page and "Любой" in page and "Вы вошли в панель" not in page
        slot_id = _first_time(c)
        form = c.get(f"/m/aktish/book?slot={slot_id}").text
        assert "Ваше имя" in form and f'value="{service.id}"' in form and "Политика конфиденциальности" in form
        assert 'name="party"' not in form  # a doctor's time is one person's
        done = _book(c, slot_id, service=str(service.id))
        assert done.status_code == 303 and done.headers["location"].startswith("/m/aktish/book/")
        page = c.get(done.headers["location"]).text
        assert "Вы записаны" in page and "Добавить в календарь" in page
        with db.new_session() as s:
            x = s.exec(select(Booking).where(Booking.business_id == business.id, Booking.source == "page")).one()
            slot = s.get(Slot, slot_id)
            assert (x.slot_id, x.customer_name, x.customer_phone, x.service, x.channel) == (slot_id, "Айбек", "+996555123456", service.name, "")
            assert slot.status == "booked" and x.start == slot.start and api.booking_json(x)["source"] == "page"
        assert x.staff_name in page and f"{x.start:%H:%M}" in page
        calendar = c.get(done.headers["location"] + "/booking.ics")
        assert calendar.headers["content-type"].startswith("text/calendar")
        start_utc = x.start - timedelta(hours=6)  # Bishkek is UTC+6
        assert f"DTSTART:{start_utc:%Y%m%dT%H%M%SZ}" in calendar.text and "TRIGGER:-PT2H" in calendar.text
        assert all(len(line.encode()) <= 75 for line in calendar.text.split("\r\n"))
        assert slot_id not in [r[0].id for r in pb.free_times(db.new_session(), business, LOCAL.replace(tzinfo=None))]
        login(c)
        assert "со страницы записи" in c.get("/panel/bookings").text
    note = rt.tg.sent[-1]
    assert note[0] == "555" and note[1].startswith(f"Новая запись со страницы: Айбек, +996 555 123 456, {service.name}")
    assert note[1].endswith("Клиент записался сам, без переписки.")


def test_a_time_taken_meanwhile_sends_the_customer_back_to_the_list(business, settings, rt):
    _open(business.id)
    with TestClient(create_app(settings, rt, init=False)) as c:
        slot_id = _first_time(c)
        fields = _form(c.get(f"/m/aktish/book?slot={slot_id}").text)
        with db.new_session() as s:
            assert claim_slot(s, slot_id)  # the AI booked it in a chat meanwhile
            s.commit()
        CLOCK["t"] += 5
        r = c.post("/m/aktish/book", data={**fields, "name": "Айбек", "phone": "0555123456"}, follow_redirects=False)
        assert r.headers["location"] == "/m/aktish/book?why=taken"
        assert "Это время только что заняли" in c.get(r.headers["location"]).text
        assert "Это время только что заняли" in c.get(f"/m/aktish/book?slot={slot_id}").text  # an old link to it too
    with db.new_session() as s:
        assert s.exec(select(Booking).where(Booking.source == "page")).first() is None


def test_scripts_and_floods_are_refused(business, settings, rt, monkeypatch):
    _open(business.id)
    with TestClient(create_app(settings, rt, init=False)) as c:
        slot_id = _first_time(c)
        assert "Не получилось записать" in _book(c, slot_id, hp_note="http://spam").text  # the field people never see
        assert _book(c, slot_id, wait=0.5).status_code == 400  # posted the moment the form was shown
        forged = c.post("/m/aktish/book", data={"slot": slot_id, "t": f"{int(CLOCK['t'])}.{'0' * 32}", "name": "A",
                                                "phone": "0555123456"}, follow_redirects=False)
        assert forged.status_code == 400
        old = _book(c, slot_id, wait=pb.MAX_FILL + 1)
        assert old.headers["location"] == "/m/aktish/book?why=stale"
        bad = _book(c, slot_id, phone="12")
        assert bad.status_code == 422 and "Укажите имя и номер телефона" in bad.text and 'value="Айбек"' in bad.text
        booking_page._by_address[f"{business.id}|testclient"] = (LOCAL.date().isoformat(), pb.PER_ADDRESS_DAY)
        assert _book(c, slot_id).status_code == 429
        booking_page.reset_limits()
        monkeypatch.setattr(pb, "PER_PHONE_AHEAD", 1)
        assert _book(c, slot_id).status_code == 303
        other = _first_time(c)
        refused = _book(c, other)
        assert refused.status_code == 429 and "На этот номер уже есть" in refused.text
        assert _book(c, other, phone="0700 111 222").status_code == 303  # another person may
        monkeypatch.setattr(pb, "PER_BUSINESS_DAY", 2)
        assert "Онлайн-запись на сегодня закрыта" in _book(c, _first_time(c), phone="0700 333 444").text
    with db.new_session() as s:
        assert len(s.exec(select(Booking).where(Booking.source == "page")).all()) == 2


def test_a_table_takes_the_guests_it_seats(business, settings, rt):
    _open(business.id)
    with TestClient(create_app(settings, rt, init=False)) as c:
        slot_id = _first_time(c)
        with db.new_session() as s:
            member = s.get(Staff, s.get(Slot, slot_id).staff_id)
            member.capacity = 4
            s.add(member)
            s.commit()
        assert 'name="party" type="number" min="1" max="4"' in c.get(f"/m/aktish/book?slot={slot_id}").text
        assert "За этим столом меньше мест" in _book(c, slot_id, party="6").text
        assert _book(c, slot_id, party="3").status_code == 303
    with db.new_session() as s:
        assert s.exec(select(Booking).where(Booking.source == "page")).one().party_size == 3


def test_never_the_example_people_altegio_or_a_lapsed_subscription(business, settings, rt, engine):
    with db.new_session() as s:
        b = create_business(s, slug="lotos", name="Салон Лотос", password="lotos-pass", niche="beauty", demo=True, now_utc=NOW_UTC)
        b.menu_enabled, b.page_booking = True, True
        s.add(b)
        s.commit()
    _open(business.id)
    with TestClient(create_app(settings, rt, init=False)) as c:
        page = c.get("/m/lotos/book").text  # only the sign-up example's masters so far: nobody to book with
        assert "Свободного времени на ближайшие две недели нет" in page and "?slot=" not in page
        with db.new_session() as s:
            b = s.get(Business, business.id)
            b.altegio_location_id = "1"
            s.add(b)
            s.commit()
        assert c.get("/m/aktish/book", follow_redirects=False).headers["location"] == "/m/aktish"
        login(c)
        assert "используйте онлайн-запись Altegio" in c.get("/panel/menu").text
        with db.new_session() as s:
            b = s.get(Business, business.id)
            b.altegio_location_id = ""
            s.add_all([b, Subscription(business_id=b.id, plan="pro", status="suspended")])
            s.commit()
        assert c.get("/m/aktish/book", follow_redirects=False).headers["location"] == "/m/aktish"
        assert "при активной подписке" in c.get("/panel/menu").text


def test_the_page_in_kyrgyz(business, settings, rt):
    _open(business.id)
    with TestClient(create_app(settings, rt, init=False)) as c:
        page = c.get("/m/aktish/book?lang=ky").text
        assert "Онлайн жазылуу" in page and "Убакыт" in page and "Каалаган" in page
        slot_id = int(re.search(r'href="\?slot=(\d+)&amp;lang=ky"', page).group(1))
        fields = _form(c.get(f"/m/aktish/book?slot={slot_id}&lang=ky").text)
        assert fields["lang"] == "ky"
        CLOCK["t"] += 5
        done = c.post("/m/aktish/book", data={**fields, "name": "Айбек", "phone": "0555123456"}, follow_redirects=False)
        assert done.headers["location"].endswith("?lang=ky")
        assert "Сиз жазылдыңыз" in c.get(done.headers["location"]).text


def test_the_confirmation_needs_its_signed_address(business, settings, rt):
    _open(business.id)
    with TestClient(create_app(settings, rt, init=False)) as c:
        url = _book(c, _first_time(c)).headers["location"]
        booking_id = int(url.rsplit("/", 1)[1].split(".")[0])
        assert c.get(url[:-1] + ("0" if url[-1] != "0" else "1")).status_code == 404
        assert c.get(f"/m/aktish/book/{booking_id}").status_code == 404
        with db.new_session() as s:
            x = s.get(Booking, booking_id)
            x.status = "cancelled"  # staff cancelled it
            s.add(x)
            s.commit()
        assert "Эта запись отменена" in c.get(url).text and c.get(url + "/booking.ics").status_code == 404


def test_api_group_class_booking_keeps_its_seats_to_give_back(business):
    """A class of five booked through the API for three people took three seats but kept party_size 0, so a
    cancellation gave one seat back and two stayed taken."""
    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.api_booking = True
        slot = s.exec(select(Slot).where(Slot.business_id == b.id, Slot.status == "free", Slot.start > LOCAL.replace(tzinfo=None)
                                         + timedelta(hours=3)).order_by(Slot.start)).first()
        slot.seats = 5
        s.add_all([b, slot])
        s.commit()
        done = api.book(s, b, {"slot_id": slot.id, "name": "Айбек", "phone": "0555123456", "party_size": 3},
                        LOCAL.replace(tzinfo=None), NOW_UTC)
        assert done.booking.party_size == 3 and s.get(Slot, slot.id).taken == 3
        assert seats_needed(slot, done.booking.party_size) == 3  # what a cancellation gives back


def test_calendar_file_escapes_and_folds():
    lines = pb._fold("SUMMARY:" + "Консультация, чистка; " * 6)
    assert all(len(x.encode()) <= 75 for x in lines) and all(x.startswith(" ") for x in lines[1:])
    assert "".join(x[1:] if i else x for i, x in enumerate(lines)) == "SUMMARY:" + "Консультация, чистка; " * 6
    assert pb._escape("a, b; c\nd") == "a\\, b\\; c\\nd"


def test_the_reminder_goes_to_telegram_after_one_tap(business, settings, rt):
    from joop.agent.engine import handle_incoming
    from joop.channels.base import IncomingMessage
    from joop.scheduler import send_reminders

    _open(business.id)
    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.telegram_bot_username = "aktish_bot"
        s.add(b)
        s.commit()
    with TestClient(create_app(settings, rt, init=False)) as c:
        url = _book(c, _first_time(c)).headers["location"]
        page = c.get(url).text
        link = re.search(r'href="(https://t\.me/aktish_bot\?start=(b\d+_[0-9a-f]+))"', page)
        assert link and "Напомнить в Telegram" in page and len(link.group(2)) <= 64
    with db.new_session() as s:
        b = s.get(Business, business.id)
        x = s.exec(select(Booking).where(Booking.source == "page")).one()
        forged = handle_incoming(s, b, IncomingMessage("telegram", "900", "command", f"/start b{x.id}_{'0' * 20}", "Чужой", "f1"),
                                 lambda: None, NOW_UTC)
        assert "Напомним сюда" not in (forged.reply or "") and s.get(Booking, x.id).chat_id == ""
        out = handle_incoming(s, b, IncomingMessage("telegram", "777", "command", f"/start {link.group(2)}", "Айбек", "r1"),
                              lambda: None, NOW_UTC)
        assert out.reply.startswith("Готово: напомним сюда накануне.")
        x = s.get(Booking, x.id)
        assert (x.channel, x.chat_id) == ("telegram", "777") and x.conversation_id
        again = handle_incoming(s, b, IncomingMessage("telegram", "888", "command", f"/start {link.group(2)}", "Другой", "r2"),
                                lambda: None, NOW_UTC)
        assert s.get(Booking, x.id).chat_id == "777" and "Напомним сюда" not in (again.reply or "")  # a link works once
        evening = x.start - timedelta(hours=18) - timedelta(hours=6)  # the evening before, in UTC
        send_reminders(s, rt, b, evening)
    assert any(chat == "777" and "Напоминаем" in text for chat, text in rt.tg.sent)
    with TestClient(create_app(settings, rt, init=False)) as c:
        page = c.get(url).text
        assert "Напоминание придёт в Telegram" in page and "t.me/aktish_bot?start=" not in page
