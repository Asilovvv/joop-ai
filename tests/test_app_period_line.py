"""The app's home screen gets the panel's line about the end of the trial or paid month (joop/web/mobile.py: summary).

An owner who runs the business from the phone never sees the panel: the morning summary says it once, the panel shows
it on every page, and the app said nothing.
"""

from datetime import datetime

import pytest

from joop import billing, db, timeutil
from joop.models import Business, PanelUser, Payment
from joop.security import hash_password

from .test_mobile import auth, client, sign_in  # noqa: F401

START = datetime(2026, 11, 2, 6, 0)  # the trial ends 16.11 at 12:00 in Bishkek


@pytest.fixture
def at(monkeypatch):
    def move(day: int):
        monkeypatch.setattr(timeutil, "clock", lambda: datetime(2026, 11, day, 4, 0))
    return move


def trial(business_id):
    with db.new_session() as s:
        billing.start_trial(s, s.get(Business, business_id), 14, START)
        s.commit()


def period(client, token):
    return client.get("/api/mobile/summary", headers=auth(token)).json()["period"]


def test_the_owner_sees_it_with_the_way_to_pay(client, business, at):
    token = sign_in(client).json()["token"]
    at(10)
    assert period(client, token) is None  # no subscription: never blocked
    trial(business.id)
    assert period(client, token) is None  # six days left
    at(14)
    assert period(client, token) == {
        "level": "warn", "text": "Пробный период заканчивается 16.11 в 12:00 — осталось 3 дня. Без оплаты ИИ остановится 19.11.",
        "pay_url": "https://joop.test/panel/billing", "ask_owner": False}
    at(25)
    line = period(client, token)
    assert line["level"] == "error" and line["text"].startswith("ИИ не отвечает клиентам с 19.11")


def test_staff_are_asked_to_tell_the_owner(client, business, at):
    trial(business.id)
    with db.new_session() as s:
        s.add(PanelUser(business_id=business.id, login="admin1", name="Администратор", password_hash=hash_password("staff-pass-123")))
        s.commit()
    token = sign_in(client, user="admin1", password="staff-pass-123").json()["token"]
    at(25)
    line = period(client, token)
    assert line["pay_url"] is None and line["ask_owner"] is True


def test_a_waiting_transfer_is_not_a_reason_to_pay_again(client, business, at):
    trial(business.id)
    with db.new_session() as s:
        s.add(Payment(business_id=business.id, amount_som=3000, method="manual", created_at=datetime(2026, 11, 24)))
        s.commit()
    token = sign_in(client).json()["token"]
    at(25)
    line = period(client, token)
    assert "ждёт подтверждения перевода" in line["text"] and line["pay_url"] is None and line["ask_owner"] is False


def test_a_shop_or_a_hotel_gets_it_too(client, business, at):
    """Independent review of #308: shops, hotels and rentals have no «Сегодня»; the app shows the line above every tab,
    so the summary answers for them too, with no bookings to count."""
    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.niche = "hotel"
        s.add(b)
        s.commit()
    trial(business.id)
    token = sign_in(client).json()["token"]
    assert client.get("/api/mobile/me", headers=auth(token)).json()["sections"]["bookings"] is False
    at(25)
    data = client.get("/api/mobile/summary", headers=auth(token)).json()
    assert data["today"] == 0 and data["next"] is None
    assert data["period"]["level"] == "error" and data["period"]["pay_url"] == "https://joop.test/panel/billing"
