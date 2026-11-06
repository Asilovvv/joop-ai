"""Joop's own API and webhooks (joop/api.py, /api/v1, /panel/api)."""

import hashlib
import hmac
import json
import socket
from datetime import timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from joop import api, db
from joop.models import Booking, Business, Lead, Order, OrderLine, WebhookDelivery
from joop.scheduler import run_due_jobs
from joop.timeutil import utc_to_local
from joop.web.app import create_app

from .conftest import NOW_UTC
from .test_web import csrf_of, login

LOCAL = utc_to_local(NOW_UTC, "Asia/Bishkek")
PUBLIC = "93.184.216.34"


@pytest.fixture(autouse=True)
def resolver(monkeypatch):
    """Hostnames resolve offline: *.internal to a private address, anything else to a public one."""
    def fake(host, port, *args, **kwargs):
        if host in ("127.0.0.1", "localhost") or host.endswith(".internal"):
            ip = "127.0.0.1" if host != "db.internal" else "10.0.0.5"
        elif host == "nowhere.example":
            raise socket.gaierror("no such host")
        else:
            ip = PUBLIC
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]
    monkeypatch.setattr(api.socket, "getaddrinfo", fake)
    api._calls.clear()


def _seed(business_id):
    with db.new_session() as s:
        rows = [
            Booking(business_id=business_id, customer_name="Айбек", customer_phone="+996555123456", service="Чистка", staff_name="Айгерим",
                    start=LOCAL + timedelta(hours=20), channel="telegram", created_at=NOW_UTC - timedelta(minutes=5)),
            Booking(business_id=business_id, customer_name="Тест", service="Чистка", start=LOCAL + timedelta(hours=2), channel="console",
                    created_at=NOW_UTC - timedelta(minutes=4)),
            Lead(business_id=business_id, kind="request", summary="Хочет на завтра", customer_name="Мадина", channel="whatsapp",
                 created_at=NOW_UTC - timedelta(minutes=3)),
            Lead(business_id=business_id, kind="error", summary="сбой", channel="telegram", created_at=NOW_UTC - timedelta(minutes=3)),
            Order(business_id=business_id, customer_name="Нурлан", customer_phone="+996700111222", total=900, channel="telegram", created_at=NOW_UTC - timedelta(minutes=2)),
        ]
        s.add_all(rows)
        s.commit()
        s.add(OrderLine(order_id=rows[4].id, name="Самса", quantity=3, unit_price=300))
        s.commit()
        return [r.id for r in rows]


def test_key_is_stored_as_a_hash_and_reads_only_this_business(business, settings, rt):
    _seed(business.id)
    with db.new_session() as s:
        b = s.get(Business, business.id)
        key = api.new_key(b)
        s.add(b)
        s.commit()
        assert b.api_key_hash == hashlib.sha256(key.encode()).hexdigest() and key not in (b.api_key_hash, b.api_key_hint)
        other = Business(slug="other", name="Другой", password_hash="x")
        s.add(other)
        s.commit()
        s.add(Booking(business_id=other.id, customer_name="Чужой", start=LOCAL, channel="telegram"))
        s.commit()
    with TestClient(create_app(settings, rt, init=False)) as c:
        assert c.get("/api/v1/bookings").status_code == 401
        assert c.get("/api/v1/bookings", headers={"Authorization": "Bearer joop_wrong"}).status_code == 401
        auth = {"Authorization": f"Bearer {key}"}
        r = c.get("/api/v1/bookings", headers=auth)
        assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
        data = r.json()["data"]
        assert [x["customer"]["name"] for x in data] == ["Айбек"]  # no test chat, no other business
        assert data[0]["staff"] == "Айгерим" and data[0]["created_at"].endswith("Z") and data[0]["paid"] is None
        order = c.get("/api/v1/orders", headers=auth).json()["data"][0]
        assert order["total"] == 900 and order["lines"] == [{"name": "Самса", "quantity": 3, "unit_price": 300, "note": ""}]
        assert [x["kind"] for x in c.get("/api/v1/leads", headers=auth).json()["data"]] == ["request"]  # not Joop's own error rows
        assert c.get("/api/v1/bookings?since=2026-11-05T00:00:00Z", headers=auth).json()["data"] == []
        assert c.get("/api/v1/bookings?since=yesterday", headers=auth).status_code == 400
        assert c.get("/api/v1/settings", headers=auth).status_code == 404
        assert c.post("/api/v1/bookings", headers=auth).status_code == 405  # read-only


def test_customers_endpoint_lists_cards(business, settings, rt):
    _seed(business.id)
    with db.new_session() as s:
        b = s.get(Business, business.id)
        key = api.new_key(b)
        s.add(b)
        s.commit()
    with TestClient(create_app(settings, rt, init=False)) as c:
        names = {x["name"] for x in c.get("/api/v1/customers", headers={"Authorization": f"Bearer {key}"}).json()["data"]}
        assert {"Айбек", "Нурлан"} <= names and "Тест" not in names


def test_rate_limit():
    assert all(api.allow("h", now=100.0) for _ in range(api.RATE))
    assert not api.allow("h", now=100.5)
    assert api.allow("h", now=161.0)


def test_ipv4_mapped_loopback_is_refused(monkeypatch):
    monkeypatch.setattr(api.socket, "getaddrinfo", lambda *a, **k: [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::ffff:127.0.0.1", 443, 0, 0))])
    assert api._public_ip("evil.example") == ""


def test_url_check_blocks_internal_and_plain_http():
    assert api.check_url("https://hook.eu1.make.com/abc") == ""
    assert "https" in api.check_url("http://hook.eu1.make.com/abc")
    assert api.check_url("https://localhost/x") and api.check_url("https://127.0.0.1/x") and api.check_url("https://db.internal/x")
    assert api.check_url("https://nowhere.example/x")
    assert api.check_url("https://user:pass@hook.eu1.make.com/x")


class Receiver:
    def __init__(self, status=200):
        self.status, self.got = status, []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.got.append(request)
        return httpx.Response(self.status)


def _hooked(business_id, since=None):
    with db.new_session() as s:
        b = s.get(Business, business_id)
        b.webhook_url, b.webhook_secret, b.webhook_since = "https://hook.example.com/joop", "s3cret", since
        s.add(b)
        s.commit()


def test_webhooks_are_signed_sent_once_and_skip_test_chat(business, rt):
    ids = _seed(business.id)
    _hooked(business.id)
    rx = Receiver()
    http = httpx.Client(transport=httpx.MockTransport(rx.handler))
    with db.new_session() as s:
        b = s.get(Business, business.id)
        assert api.send_due(s, http, b, NOW_UTC) == {"sent": 3, "failed": 0}
        s.commit()
        events = [r.headers["x-joop-event"] for r in rx.got]
        assert events == ["booking.created", "order.created", "lead.created"]  # an internal error is not a lead
        first = rx.got[0]
        assert first.url.host == PUBLIC and first.headers["host"] == "hook.example.com"  # pinned to the checked address
        assert first.extensions.get("sni_hostname") == "hook.example.com"
        assert first.headers["x-joop-signature"] == "sha256=" + hmac.new(b"s3cret", first.content, hashlib.sha256).hexdigest()
        body = json.loads(first.content)
        assert body["business"] == "aktish" and body["data"]["id"] == ids[0]
        assert api.send_due(s, http, b, NOW_UTC) == {}  # nothing twice
        booking = s.get(Booking, ids[0])
        booking.paid_som, booking.paid_method, booking.paid_at = 3000, "cash", NOW_UTC
        s.add(booking)
        s.commit()
        assert api.send_due(s, http, b, NOW_UTC + timedelta(minutes=1)) == {"sent": 1, "failed": 0}
        assert rx.got[-1].headers["x-joop-event"] == "booking.paid" and json.loads(rx.got[-1].content)["data"]["paid"]["som"] == 3000


def test_webhooks_retry_then_give_up_and_skip_the_backlog(business, rt):
    _seed(business.id)
    _hooked(business.id, since=NOW_UTC - timedelta(minutes=4, seconds=30))  # switched on after the first booking
    rx = Receiver(status=500)
    http = httpx.Client(transport=httpx.MockTransport(rx.handler))
    with db.new_session() as s:
        b = s.get(Business, business.id)
        for i in range(api.MAX_ATTEMPTS):
            assert api.send_due(s, http, b, NOW_UTC + timedelta(minutes=i)) == {"sent": 0, "failed": 1}  # stops at the first failure
            s.commit()
        assert "HTTP 500" in b.webhook_error
        assert "booking.created" not in {r.headers["x-joop-event"] for r in rx.got}  # older than the switch-on
        rx.status = 200
        assert api.send_due(s, http, b, NOW_UTC + timedelta(minutes=9))["sent"] == 1  # the given-up one stays given up
        s.commit()
        row = s.exec(select(WebhookDelivery).where(WebhookDelivery.attempts == api.MAX_ATTEMPTS)).one()
        assert row.delivered_at is None and b.webhook_error == ""


def test_webhook_refuses_an_address_that_turned_inward(business, rt):
    _seed(business.id)
    _hooked(business.id)
    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.webhook_url = "https://db.internal/x"
        rx = Receiver()
        api.send_due(s, httpx.Client(transport=httpx.MockTransport(rx.handler)), b, NOW_UTC)
        assert rx.got == [] and "внутреннюю" in b.webhook_error


def test_scheduler_sends_webhooks(business, rt):
    _seed(business.id)
    _hooked(business.id)
    rx = Receiver()
    rt.http = httpx.Client(transport=httpx.MockTransport(rx.handler))
    with db.new_session() as s:
        report = run_due_jobs(s, rt, s.get(Business, business.id), NOW_UTC)
        s.commit()
    assert len(rx.got) == 3 and report.get("webhooks") == {"sent": 3, "failed": 0}


def test_panel_page_owner_only_key_shown_once(business, settings, rt):
    with TestClient(create_app(settings, rt, init=False)) as c:
        login(c)
        page = c.get("/panel/api").text
        assert "API и вебхуки" in page and "Создать ключ" in page
        token = csrf_of(page)
        page = c.post("/panel/api", data={"csrf": token, "action": "new_key"}).text
        key = page.split('value="joop_')[1].split('"')[0]
        assert "больше он показан не будет" in page
        assert "joop_" + key not in c.get("/panel/api").text  # shown once
        with db.new_session() as s:
            assert s.get(Business, business.id).api_key_hint == key[-4:]
        assert c.get("/api/v1/bookings", headers={"Authorization": f"Bearer joop_{key}"}).status_code == 200
        r = c.post("/panel/api", data={"csrf": token, "action": "save_webhook", "url": "https://localhost/x"}, follow_redirects=True)
        assert "внутреннюю сеть" in r.text
        page = c.post("/panel/api", data={"csrf": token, "action": "save_webhook", "url": "https://hook.example.com/a"}).text
        assert "Секрет подписи" in page
        with db.new_session() as s:
            b = s.get(Business, business.id)
            assert b.webhook_url == "https://hook.example.com/a" and len(b.webhook_secret) == 48 and b.webhook_since == NOW_UTC
        c.post("/panel/api", data={"csrf": token, "action": "revoke_key"})
        assert c.get("/api/v1/bookings", headers={"Authorization": f"Bearer joop_{key}"}).status_code == 401
        c.post("/panel/api", data={"csrf": token, "action": "off_webhook"})
        with db.new_session() as s:
            b = s.get(Business, business.id)
            assert b.webhook_url == "" and b.webhook_secret == ""
