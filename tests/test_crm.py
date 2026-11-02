"""amoCRM / Kommo: bookings, requests and orders become deals, against a fake amoCRM API (joop/crm.py)."""

import json
from datetime import timedelta

import httpx
import pytest
from sqlmodel import select

from joop import crm, db
from joop.models import Booking, Business, Lead, Order, OrderLine
from joop.scheduler import run_due_jobs
from joop.timeutil import utc_to_local

from .conftest import NOW_UTC
from .test_web import client, csrf_of, login  # noqa: F401  (client is a fixture)

TOKEN = "long-lived-test-token"


class FakeAmo:
    def __init__(self):
        self.deals, self.notes, self.seen = [], [], []
        self.fail: dict[str, int] = {}  # deal name -> status to answer

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request)
        if request.headers.get("authorization") != f"Bearer {TOKEN}":
            return httpx.Response(401, json={"title": "Unauthorized"})
        path = request.url.path
        if path == "/api/v4/account":
            return httpx.Response(200, json={"id": 1, "name": "Ак-Тиш"})
        body = json.loads(request.content)
        if path == "/api/v4/leads/complex":
            deal = body[0]
            if deal["name"] in self.fail:
                return httpx.Response(self.fail[deal["name"]], json={"title": "Bad Request"})
            self.deals.append(deal)
            return httpx.Response(200, json=[{"id": 1000 + len(self.deals), "contact_id": 7, "company_id": None,
                                              "request_id": ["0"], "merged": False}])
        if path == "/api/v4/leads/notes":
            self.notes.extend(body)
            return httpx.Response(200, json={"_embedded": {"notes": [{"id": 1}]}})
        return httpx.Response(404)


@pytest.fixture
def amo(business, rt):
    fake = FakeAmo()
    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.crm_domain, b.crm_token = "aktish.amocrm.ru", TOKEN
        s.add(b)
        s.commit()
    rt.crm = lambda b: crm.AmoClient(httpx.Client(transport=httpx.MockTransport(fake.handler)), crm.base_url(b.crm_domain),
                                     b.crm_token, min_interval=0) if crm.connected(b) else None
    return fake


def seed(business_id):
    with db.new_session() as s:
        b = s.get(Business, business_id)
        start = utc_to_local(NOW_UTC, b.timezone).replace(minute=0, second=0, microsecond=0) + timedelta(days=1)
        s.add(Booking(business_id=b.id, start=start, service="Чистка зубов", staff_name="Доктор Асель", customer_name="Айбек",
                      customer_phone="+996555123456", channel="telegram", conversation_id=None, created_at=NOW_UTC - timedelta(hours=1),
                      deposit_due=500))
        s.add(Booking(business_id=b.id, start=start, service="Приём", source="panel", created_at=NOW_UTC))  # staff's own: not sent
        s.add(Lead(business_id=b.id, kind="handoff", summary="Жалоба на мастера", customer_name="Нургуль", channel="whatsapp",
                   created_at=NOW_UTC - timedelta(minutes=30)))
        s.add(Lead(business_id=b.id, kind="error", summary="ИИ не ответил", created_at=NOW_UTC))  # not a customer request
        s.add(Lead(business_id=b.id, kind="request", summary="Старая", created_at=NOW_UTC - timedelta(days=5)))  # too old
        order = Order(business_id=b.id, customer_name="Бакыт", customer_phone="+996700111222", total=2500, mode="delivery",
                      address="Ахунбаева 1", created_at=NOW_UTC - timedelta(minutes=10))
        s.add(order)
        s.flush()
        s.add(OrderLine(order_id=order.id, name="Лагман", quantity=2))
        s.commit()


def test_addresses_only_on_crm_hosts():
    assert crm.base_url("MyCompany.amocrm.ru") == "https://mycompany.amocrm.ru"
    assert crm.base_url("https://shop-1.kommo.com/leads/pipeline") == "https://shop-1.kommo.com"
    for bad in ("evil.com", "amocrm.ru", "a.b.amocrm.ru", "x.amocrm.ru.evil.com", "http://127.0.0.1", ""):
        assert crm.base_url(bad) == ""


def test_deals_with_contact_tags_and_notes_once(business, rt, amo):
    seed(business.id)
    with db.new_session() as s:
        report = run_due_jobs(s, rt, s.get(Business, business.id), NOW_UTC)
        s.commit()
    assert report["crm"] == {"sent": 3, "skipped": 0}
    names = [d["name"] for d in amo.deals]
    assert names[0].startswith("Запись: Чистка зубов — ") and names[1] == "Вопрос администратору: Жалоба на мастера"
    assert names[2] == "Заказ №1" and amo.deals[2]["price"] == 2500
    contact = amo.deals[0]["_embedded"]["contacts"][0]
    assert contact == {"first_name": "Айбек", "custom_fields_values": [
        {"field_code": "PHONE", "values": [{"value": "+996555123456", "enum_code": "WORK"}]}]}
    assert {"name": "Joop AI"} in amo.deals[0]["_embedded"]["tags"] and "pipeline_id" not in amo.deals[0]
    notes = {n["entity_id"]: n["params"]["text"] for n in amo.notes}
    assert "Предоплата: 500 сом" in notes[1001] and "Доктор Асель" in notes[1001] and "Канал: Telegram" in notes[1001]
    assert "Лагман × 2" in notes[1003] and "Доставка: Ахунбаева 1" in notes[1003] and "Итого: 2500 сом" in notes[1003]
    assert all(n["note_type"] == "common" for n in amo.notes)
    with db.new_session() as s:
        assert s.exec(select(Booking.crm_id).where(Booking.source == "ai")).one() == "1001"
        b = s.get(Business, business.id)
        assert b.crm_synced_at == NOW_UTC and b.crm_error == ""
        assert crm.push_due(s, rt.crm(b), b, NOW_UTC) == {}  # nothing twice


def test_a_rejected_deal_is_skipped_and_a_bad_token_stops(business, rt, amo):
    seed(business.id)
    amo.fail["Вопрос администратору: Жалоба на мастера"] = 400
    with db.new_session() as s:
        b = s.get(Business, business.id)
        assert crm.push_due(s, rt.crm(b), b, NOW_UTC) == {"sent": 2, "skipped": 1}
        assert s.exec(select(Lead.crm_id).where(Lead.kind == "handoff")).one() == "-"
        assert "не принял одну сделку (400" in b.crm_error
        s.commit()
    with db.new_session() as s:
        s.add(Lead(business_id=business.id, kind="lead", summary="Новый", created_at=NOW_UTC))
        b = s.get(Business, business.id)
        b.crm_token = "revoked"
        s.commit()
    with db.new_session() as s:
        b = s.get(Business, business.id)
        assert crm.push_due(s, rt.crm(b), b, NOW_UTC) == {}
        assert "создайте новый долгосрочный токен" in b.crm_error
        assert s.exec(select(Lead.crm_id).where(Lead.summary == "Новый")).one() == ""  # tried again next time


def test_panel_connect_checks_the_token(client, business, rt, monkeypatch):  # noqa: F811
    fake = FakeAmo()
    rt.http = httpx.Client(transport=httpx.MockTransport(fake.handler))
    login(client)
    page = client.get("/panel/channels").text
    assert "amoCRM / Kommo" in page and "Подключить amoCRM" in page
    form = {"csrf": csrf_of(page), "domain": "evil.example.com", "token": TOKEN, "action": "connect"}
    assert "Укажите адрес аккаунта amoCRM" in client.post("/panel/crm", data=form).text
    assert "amoCRM не принял подключение (401)" in client.post("/panel/crm", data={**form, "domain": "aktish.amocrm.ru", "token": "wrong"}).text
    page = client.post("/panel/crm", data={**form, "domain": "https://aktish.amocrm.ru/leads", "pipeline_id": "123"}).text
    assert "amoCRM подключён: Ак-Тиш" in page and "оставьте пустым, чтобы не менять" in page and TOKEN not in page
    with db.new_session() as s:
        b = s.get(Business, business.id)
        assert (b.crm_domain, b.crm_token, b.crm_pipeline_id) == ("aktish.amocrm.ru", TOKEN, 123)
    assert "amoCRM отключён" in client.post("/panel/crm", data={**form, "action": "disconnect"}).text
    with db.new_session() as s:
        assert s.get(Business, business.id).crm_token == ""
