"""A line on top of every panel page while the AI is about to stop or has stopped for the subscription.

The morning summary says it once (joop/period_end.py: notice); whoever opens the panel later, or never reads the
summary, saw nothing — and after the stop answered no one, not knowing the AI was quiet.
"""

import re
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from joop import billing, db, timeutil
from joop.models import Business, PanelUser, Staff
from joop.security import hash_password
from joop.web.app import create_app

from .test_web import login

START = datetime(2026, 11, 2, 6, 0)  # the trial ends 16.11 at 12:00 in Bishkek


@pytest.fixture
def at(monkeypatch):
    def move(day: int, hour_utc: int = 4):
        monkeypatch.setattr(timeutil, "clock", lambda: datetime(2026, 11, day, hour_utc, 0))
    return move


def trial(business_id, *, cancelled=False, free=False, suspended=False):
    with db.new_session() as s:
        sub = billing.start_trial(s, s.get(Business, business_id), 14, START)
        if cancelled:
            billing.cancel(sub, START + timedelta(days=1))
        if free:
            sub.plan = "free"
        if suspended:
            sub.status = "suspended"
        s.commit()


def line(page: str) -> str | None:
    found = re.search(r'<div class="flash (warn|error)" role="status">(.*?)</div>', page, re.S)
    return f"{found.group(1)}: {re.sub(r'<[^>]+>', '', found.group(2)).strip()}" if found else None


@pytest.fixture
def owner(settings, rt, business):
    with TestClient(create_app(settings, rt, init=False)) as c:
        login(c)
        yield c


def test_the_owner_sees_it_on_every_page_with_the_way_to_pay(owner, business, at):
    trial(business.id)
    at(12)
    assert line(owner.get("/panel").text) is None  # four days left and more: nothing
    at(14)
    page = owner.get("/panel/conversations").text
    assert line(page) == "warn: Пробный период заканчивается 16.11 в 12:00 — осталось 3 дня. Без оплаты ИИ остановится 19.11. Перейти к оплате"
    assert '<a href="/panel/billing">Перейти к оплате</a>' in page
    at(17)
    assert line(owner.get("/panel").text) == "warn: Пробный период закончился 16.11. ИИ отвечает клиентам до 19.11 12:00, потом остановится. Перейти к оплате"
    at(25)  # weeks after the stop it is still the state of things, unlike the summary's one-time notice
    assert line(owner.get("/panel").text) == ("error: ИИ не отвечает клиентам с 19.11: пробный период закончился. "
                                              "Сообщения из Telegram и с сайта приходят вам — отвечайте в «Диалогах». Перейти к оплате")
    billing_page = owner.get("/panel/billing").text
    assert line(billing_page).startswith("error: ИИ не отвечает клиентам") and "Перейти к оплате</a>" not in billing_page


def test_staff_are_asked_to_tell_the_owner(settings, rt, business, at):
    trial(business.id)
    with db.new_session() as s:
        s.add(PanelUser(business_id=business.id, login="admin1", name="Администратор", password_hash=hash_password("staff-pass-123")))
        s.commit()
    at(25)
    with TestClient(create_app(settings, rt, init=False)) as c:
        token = re.search(r'name="csrf" value="([^"]+)"', c.get("/login").text).group(1)
        c.post("/login", data={"slug": "aktish", "user": "admin1", "password": "staff-pass-123", "csrf": token})
        page = c.get("/panel/conversations").text
    assert line(page).endswith("отвечайте в «Диалогах». Скажите владельцу.") and "/panel/billing\">" not in page


def test_a_cancelled_subscription_shows_only_the_stop(owner, business, at):
    trial(business.id, cancelled=True)
    at(14)
    assert line(owner.get("/panel").text) is None  # no reminders to pay: the owner chose
    at(17)  # cancelled: no waiting days
    assert line(owner.get("/panel").text).startswith("error: ИИ не отвечает клиентам: подписка отменена.")


def test_the_free_plan_with_more_than_one_master(owner, business, at):
    trial(business.id, free=True)
    at(14)
    with db.new_session() as s:
        masters = len([r for r in s.exec(select(Staff).where(Staff.business_id == business.id, Staff.active == True)).all()])  # noqa: E712
    assert masters > 1
    assert line(owner.get("/panel").text).startswith(
        f"error: ИИ не отвечает клиентам: бесплатный тариф — для одного мастера, а работают {masters}.")
    with db.new_session() as s:
        for i, row in enumerate(s.exec(select(Staff).where(Staff.business_id == business.id)).all()):
            row.active = i == 0
            s.add(row)
        s.commit()
    assert line(owner.get("/panel").text) is None


def test_suspended_has_no_pay_link(owner, business, at):
    trial(business.id, suspended=True)
    at(5)
    page = owner.get("/panel").text
    assert line(page) == "error: ИИ не отвечает клиентам: доступ приостановлен. Напишите нам." and "Перейти к оплате" not in page


def test_no_subscription_no_line(owner, business, at):
    """Created from the command line: never blocked, nothing to say."""
    at(25)
    assert line(owner.get("/panel").text) is None
