"""«Позвонить сегодня»: whom the founder should call, and why (joop/founder_calls.py).

The console listed every business in one table; finding the trial that ends in two days, the owner stuck halfway
through the setup and the AI stopped last week meant reading all of it. Now the list is on top of /owner and in the
founder's Telegram every morning at 10:00.
"""

import dataclasses
from datetime import datetime, timedelta

import pytest
from sqlmodel import select

from joop import billing, db, founder_calls, health, timeutil
from joop.models import Business, FounderCallList, Payment, Subscription
from joop.presets import create_business

from .test_saas import app_client, owner_login, saas_settings  # noqa: F401

NOW = datetime(2026, 11, 27, 5, 0)  # 11:00 in Bishkek


def signed_up(slug: str, days_ago: float, trial_days: int = 14, **sub_fields) -> int:
    """A business that signed up `days_ago` days before NOW, as /signup makes it."""
    at = NOW - timedelta(days=days_ago)
    with db.new_session() as s:
        b = create_business(s, slug=slug, name=f"Компания {slug}", password="x" * 12, niche="dental", now_utc=at)
        sub = billing.start_trial(s, b, trial_days, at)
        sub.contact_name, sub.contact_phone, sub.created_at = "Айгуль", "+996 555 100 200", at
        for field, value in sub_fields.items():
            setattr(sub, field, value)
        s.commit()
        return b.id


def listed():
    with db.new_session() as s:
        return {c.name.removeprefix("Компания "): c for c in founder_calls.calls(s, NOW)}


def test_a_trial_that_ends_soon_is_a_call_to_offer_payment(engine):
    signed_up("ends", days_ago=12.5)  # ends in 1.5 days
    signed_up("later", days_ago=5)  # nine days left and a stalled setup: that is another call
    found = listed()
    c = found["ends"]
    assert c.kind == "ends" and c.who == "Айгуль, +996\u00a0555\u00a0100\u00a0200"
    assert c.reason.startswith("Пробный период заканчивается 28.11 (осталось 2 дн.). За это время: настоящих клиентов ещё не было.")
    assert c.offer == "Предложите оплату или год."
    assert found["later"].kind == "setup"


def test_an_owner_stuck_in_the_setup_is_a_call_to_help(engine):
    signed_up("stuck", days_ago=3)
    signed_up("fresh", days_ago=0.5)  # signed up this morning: a day to try alone
    signed_up("gone", days_ago=11, trial_days=30)  # a stalled setup of eleven days is a lost lead, not a call
    found = listed()
    assert set(found) == {"stuck"}
    c = found["stuck"]
    assert c.kind == "setup" and c.reason.startswith("Не закончил настройку: 0 из ") and "Зарегистрировался 3 дн. назад." in c.reason
    assert "дальше «Контакты и часы работы»" in c.reason and c.offer.startswith("Предложите помочь")


def test_an_ai_stopped_for_payment_is_a_call_to_win_back(engine):
    signed_up("stopped", days_ago=14 + 3 + 5)  # trial ended 8 days ago, stopped 5 days ago
    signed_up("long-ago", days_ago=14 + 3 + 20)
    found = listed()
    assert set(found) == {"stopped"}
    assert found["stopped"].reason.startswith("ИИ остановлен 22.11: пробный период закончился.")


def test_who_is_not_called(engine):
    signed_up("cancelled", days_ago=12.5, cancelled_at=NOW - timedelta(days=1))
    signed_up("free", days_ago=12.5, plan="free")
    signed_up("paused", days_ago=12.5, status="suspended")
    waiting = signed_up("paid-by-transfer", days_ago=12.5)
    with db.new_session() as s:
        s.add(Payment(business_id=waiting, amount_som=3000, method="manual", created_at=NOW - timedelta(hours=2)))
        s.commit()
    demo = signed_up("site-demo-salon", days_ago=12.5)
    assert listed() == {} and demo


def test_money_comes_first_in_the_list(engine):
    signed_up("b-setup", days_ago=3)
    signed_up("c-stopped", days_ago=22)
    signed_up("a-ends", days_ago=12.5)
    with db.new_session() as s:
        assert [c.kind for c in founder_calls.calls(s, NOW)] == ["ends", "stopped", "setup"]


@pytest.fixture
def founder(rt, monkeypatch):
    told = []
    rt.settings = dataclasses.replace(rt.settings, founder_bot_token="F:T", founder_chat_id="42", public_base_url="https://joop.test")
    monkeypatch.setattr(health, "_send", lambda rt_, text: told.append(text) or True)
    return told


def test_the_founder_gets_it_once_a_morning(engine, rt, founder):
    signed_up("ends", days_ago=12.5)
    with db.new_session() as s:
        assert founder_calls.maybe_send(s, rt, NOW - timedelta(hours=2)) is None  # 09:00: not yet
        row = founder_calls.maybe_send(s, rt, NOW)
        assert row.sent and row.count == 1
        assert founder_calls.maybe_send(s, rt, NOW + timedelta(hours=3)) is None  # the same day: once
    (text,) = founder
    assert text.startswith("Joop AI: позвонить сегодня (1).\n1. «Компания ends» — Айгуль, +996\u00a0555\u00a0100\u00a0200. Пробный период заканчивается 28.11")
    assert text.endswith("Консоль: https://joop.test/owner")


def test_nobody_to_call_sends_nothing(engine, rt, founder):
    with db.new_session() as s:
        row = founder_calls.maybe_send(s, rt, NOW)
        assert row.count == 0 and not row.sent
        assert s.exec(select(FounderCallList)).one().day.isoformat() == "2026-11-27"
    assert founder == []


def test_the_console_shows_the_list(app_client, monkeypatch):
    monkeypatch.setattr(timeutil, "clock", lambda: NOW)
    signed_up("ends", days_ago=12.5)
    owner_login(app_client)
    page = app_client.get("/owner").text
    assert "Позвонить сегодня (1)" in page and "Предложите оплату или год." in page
    with db.new_session() as s:
        assert s.exec(select(Subscription)).one().contact_phone == "+996 555 100 200"
        assert s.exec(select(Business)).one().slug == "ends"
