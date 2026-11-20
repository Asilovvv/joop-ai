"""The privacy page lists every place where the service collects people's data."""

from fastapi.testclient import TestClient

from joop.web.app import create_app


def test_privacy_names_the_booking_page_staff_entries_and_sign_up(settings, rt, engine):
    with TestClient(create_app(settings, rt, init=False)) as c:
        page = c.get("/privacy").text
    assert "страницы записи клиента" in page and "Напомнить в Telegram" in page  # /m/<slug>/book, #255 and #258
    assert "вносят в панель сами" in page  # bookings by phone, stays, memberships, job orders
    assert "только в виде хеша" in page and "имя и телефон из регистрации" in page
    assert "которым мы сами предлагаем сервис" in page  # the founder's prospects list
    assert "не храним номера карт, пароли от мессенджеров" in page
