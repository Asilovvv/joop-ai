"""Independent review of #320–#333.

1. While #313 was in main (about fifteen hours on 27 Nov), a booking staff made on the public booking page got the
   panel test chat's channel and vanished from «Записи», «Касса» and the reminders; 0070 added `Booking.by_staff` but
   left those rows hidden. 0071 makes them real bookings again.
2. A receptionist booking callers on the page stopped at the ten bookings a day one address may make, and the staff's
   alert said the customer had booked by themselves.
3. The Kyrgyz free-delivery term in «Запуск» read «акысыз жеткирүү, сомдон баштап 5000 сом».
4. Kyrgyz refusals and the period line named the app's sections in Russian («Диалоги», «Оплата», «Расписание»,
   «Мастера») and missed endings («{date} баштап», «саат 12:00 чейин»).
5. The customer's place card opened the booking page and the public page in Russian for an app in Kyrgyz, and named
   the page in Russian.
6. The test that the app's language does not leak between requests could not fail: each request runs in its own
   context anyway. The route class's reset is checked directly.
"""

import asyncio
from datetime import datetime

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import select
from starlette.requests import Request

from joop import checklist_ky, db, errors_ky, free_plan, migrate, page_booking as pb, period_ky
from joop.models import Booking, Business
from joop.web import booking_page, mobile
from joop.web.app import create_app

from .test_booking_page import LOCAL, _book, _first_time, _open, form_clock  # noqa: F401 - the form's clock
from .test_mobile import client  # noqa: F401 - the client fixture
from .test_mobile_place import _set
from .test_web import login

KY = {"Accept-Language": "ky"}
APP_SECTIONS_RU = ("«Диалоги»", "«Оплата»", "«Расписание»", "«Мастера»", "«Каналы»")


def test_staff_page_bookings_hidden_by_313_are_real_again(engine, business):
    with db.new_session() as s:
        s.add(Booking(business_id=business.id, start=datetime(2026, 11, 28, 10), customer_name="Гульнара",
                      customer_phone="+996700999888", source="page", channel="console"))  # written by #313
        s.add(Booking(business_id=business.id, start=datetime(2026, 11, 28, 11), customer_name="Проба",
                      source="ai", channel="console"))  # the panel's test chat booked it: still a test
        s.commit()
    with engine.begin() as conn:
        conn.execute(text("update alembic_version set version_num = '0070'"))
    migrate.upgrade()
    with db.new_session() as s:
        rows = {x.customer_name: (x.by_staff, x.channel) for x in s.exec(select(Booking).where(
            Booking.business_id == business.id, Booking.customer_name.in_(["Гульнара", "Проба"]))).all()}
    assert rows == {"Гульнара": (True, ""), "Проба": (False, "console")}


def test_a_receptionist_books_callers_past_one_addresss_daily_limit(business, settings, rt):
    _open(business.id)
    booking_page.reset_limits()
    try:
        with TestClient(create_app(settings, rt, init=False)) as c:
            booking_page._by_address[f"{business.id}|testclient"] = (LOCAL.date().isoformat(), pb.PER_ADDRESS_DAY)
            assert _book(c, _first_time(c)).status_code == 429  # a visitor from that address: the limit holds
            login(c)
            assert _book(c, _first_time(c), name="Гульнара", phone="0700 999 888").status_code == 303
            assert _book(c, _first_time(c), name="Бакыт", phone="0700 777 666").status_code == 303
        assert rt.tg.sent[-1][1].startswith("Новая запись со страницы: Бакыт")
        assert rt.tg.sent[-1][1].endswith("Записал сотрудник на странице записи.")
        assert booking_page._by_address[f"{business.id}|testclient"][1] == pb.PER_ADDRESS_DAY  # staff do not use it up
    finally:
        booking_page.reset_limits()


def test_the_kyrgyz_free_delivery_term_reads_right():
    b = Business(slug="nan", name="Нан", min_order=500, delivery_fee=200, free_delivery_from=5000)
    _, hint = checklist_ky._contacts({"from_example": ["order"]}, b)
    assert "минималдуу буйрутма 500 сом, жеткирүү 200 сом, 5000 сомдон баштап акысыз жеткирүү)" in hint, hint


def test_kyrgyz_sentences_name_the_apps_sections_in_kyrgyz():
    for ky in [*errors_ky.KY_ERRORS.values(), *(k for _, k in errors_ky.KY_PATTERNS), *(k for _, k in period_ky.KY_PERIOD)]:
        assert not any(name in ky for name in APP_SECTIONS_RU), ky
    cancelled = period_ky.kyrgyz("ИИ не отвечает клиентам: подписка отменена. Сообщения из Telegram и с сайта приходят "
                                 "вам — отвечайте в «Диалогах». Возобновить можно в «Оплате».")
    assert "«Диалогдор»" in cancelled and "«Төлөм»" in cancelled
    assert "саат 12:00 болгуча" in period_ky.kyrgyz(
        "Пробный период закончился 16.11. ИИ отвечает клиентам до 19.11 12:00, потом остановится.")
    assert errors_ky.kyrgyz("Бронируем с 28.11.2026 и не дальше чем на год вперёд.").startswith("28.11.2026 күндөн баштап")
    assert "«Төлөм»" in errors_ky.kyrgyz(free_plan.TOO_MANY) and "«Төлөм»" in errors_ky.kyrgyz(free_plan.TOO_MANY_EXAMPLE)


def test_the_place_card_opens_the_pages_in_the_apps_language(client, business):
    _set(business.id, menu_enabled=True, page_booking=True)
    ru = client.get("/api/mobile/places/aktish").json()
    ky = client.get("/api/mobile/places/aktish", headers=KY).json()
    assert (ru["book_url"], ru["page_url"], ru["page_label"]) == \
        ("https://joop.test/m/aktish/book", "https://joop.test/m/aktish", "Прайс онлайн")
    assert (ky["book_url"], ky["page_url"], ky["page_label"]) == \
        ("https://joop.test/m/aktish/book?lang=ky", "https://joop.test/m/aktish?lang=ky", "Онлайн баалар")
    for url in (ky["book_url"], ky["page_url"]):  # both pages open in Kyrgyz
        assert '<html lang="ky">' in client.get(url.removeprefix("https://joop.test")).text, url


def test_the_route_class_puts_the_language_back_after_each_request(monkeypatch):
    seen = []

    async def endpoint(request: Request):
        seen.append(mobile._LANGUAGE.get())
        if request.headers.get("x-fail"):
            raise RuntimeError("the endpoint failed")
        return "ok"

    monkeypatch.setattr(APIRoute, "get_route_handler", lambda self: endpoint)
    handler = mobile._InAppLanguage("/x", lambda: None).get_route_handler()

    def request(headers: dict) -> Request:
        return Request({"type": "http", "method": "GET", "path": "/x", "query_string": b"",
                        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()]})

    async def run() -> list[str]:  # one task, one context: nothing copies it between the calls
        after = []
        await handler(request(KY))
        after.append(mobile._LANGUAGE.get())
        try:
            await handler(request({**KY, "X-Fail": "1"}))
        except RuntimeError:
            pass
        after.append(mobile._LANGUAGE.get())
        await handler(request({}))
        return after

    assert asyncio.run(run()) == ["ru", "ru"]
    assert seen == ["ky", "ky", "ru"]
