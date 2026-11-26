"""The payment loop without silences (joop/web/saas.py, joop/period_end.py).

Before: an owner who asked to pay by transfer waited until the founder happened to open the console; once the founder
confirmed it (or a card payment came), the owner learned it only by opening «Оплата»; and meanwhile the morning
summary and the panel kept saying «оплатите» to someone who already had.
"""

import dataclasses
from datetime import datetime, timedelta

import pytest
from sqlmodel import select

from joop import billing, db, health, timeutil
from joop.models import Business, Payment

from .test_saas import _callback, app_client, owner_login, saas_settings, signup  # noqa: F401
from .test_web import csrf_of


@pytest.fixture
def founder(rt, monkeypatch):
    told = []
    rt.settings = dataclasses.replace(rt.settings, founder_bot_token="F:TOKEN", founder_chat_id="42",
                                      public_base_url="https://joop.test")
    monkeypatch.setattr(health, "_send", lambda rt_, text: told.append(text) or True)
    return told


def staff_chat(slug="ak-tish-dent"):
    """The business's Telegram bot and staff chat, so its notes can be seen."""
    with db.new_session() as s:
        b = s.exec(select(Business).where(Business.slug == slug)).one()
        b.telegram_bot_token, b.admin_chat_ids = "123:TOKEN", "-5001"
        s.commit()
        return b.id


def ask_transfer(client):
    token = csrf_of(client.get("/panel/billing").text)
    client.post("/panel/billing/pay", data={"method": "manual", "csrf": token})
    with db.new_session() as s:
        return s.exec(select(Payment)).one()


def notes(rt):
    return [text for chat, text in rt.tg.sent if chat == "-5001"]


def test_the_founder_hears_of_a_transfer_request_at_once(app_client, founder, rt):
    signup(app_client)
    pay = ask_transfer(app_client)
    assert founder == [f"Joop AI: заявка на оплату переводом №{pay.id} — «Ак-Тиш Дент» (ak-tish-dent), 3000 сом. "
                       "Проверьте поступление и подтвердите: https://joop.test/owner"]


def test_the_owner_hears_the_transfer_was_confirmed(app_client, founder, rt):
    signup(app_client)
    staff_chat()
    pay = ask_transfer(app_client)
    token = owner_login(app_client)
    app_client.post(f"/owner/payment/{pay.id}", data={"action": "confirm", "csrf": token})
    (note,) = notes(rt)
    with db.new_session() as s:
        until = timeutil.utc_to_local(billing.get_subscription(s, pay.business_id).paid_until, "Asia/Bishkek")
    assert note == f"Оплата 3 000 сом получена, спасибо! ИИ-администратор «Ак-Тиш Дент» оплачен до {until:%d.%m.%Y}."
    app_client.post(f"/owner/payment/{pay.id}", data={"action": "confirm", "csrf": token})  # pressed twice
    assert len(notes(rt)) == 1


def test_the_owner_hears_a_payment_the_founder_marked(app_client, founder, rt):
    signup(app_client)
    bid = staff_chat()
    token = owner_login(app_client)
    app_client.post(f"/owner/business/{bid}", data={"action": "paid", "csrf": token})
    assert [n.split("!")[0] for n in notes(rt)] == ["Оплата 3 000 сом получена, спасибо"]


def test_a_card_payment_is_told_once_though_the_bank_repeats_it(app_client, rt):
    signup(app_client)
    bid = staff_chat()
    with db.new_session() as s:
        pay = Payment(business_id=bid, amount_som=3000, method="freedompay")
        s.add(pay)
        s.commit()
        pid = pay.id
    assert "<pg_status>ok</pg_status>" in _callback(app_client, pid, 3000).text
    assert "<pg_status>ok</pg_status>" in _callback(app_client, pid, 3000).text  # FreedomPay calls again
    assert len(notes(rt)) == 1 and notes(rt)[0].startswith("Оплата 3 000 сом получена")


def test_while_a_transfer_waits_nobody_is_told_to_pay(app_client, founder, rt, monkeypatch):
    signup(app_client)
    with db.new_session() as s:
        sub = billing.get_subscription(s, s.exec(select(Business)).one().id)
        end = sub.trial_ends_at
    monkeypatch.setattr(timeutil, "clock", lambda: end - timedelta(days=2))
    page = app_client.get("/panel").text
    assert "Перейти к оплате" in page
    pay = ask_transfer(app_client)
    page = app_client.get("/panel").text
    assert f"Заявка на оплату №{pay.id} ждёт подтверждения перевода" in page and "Перейти к оплате</a>" not in page
    from joop import period_end
    with db.new_session() as s:
        b = s.get(Business, pay.business_id)
        text = period_end.notice(s, b, end - timedelta(days=2), "https://joop.test", 3000)
    assert f"Заявка на оплату №{pay.id} ждёт подтверждения перевода" in text and "Оплатить" not in text


def test_an_old_request_is_not_on_its_way_any_more(engine, business):
    with db.new_session() as s:
        s.add(Payment(business_id=business.id, amount_som=3000, method="manual", created_at=datetime(2026, 11, 1)))
        s.commit()
        assert billing.pending_transfer(s, business.id, datetime(2026, 11, 7)) is not None
        assert billing.pending_transfer(s, business.id, datetime(2026, 11, 9)) is None
