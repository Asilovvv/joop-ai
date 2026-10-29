import dataclasses
import re
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from joop import billing, db
from joop.agent.engine import handle_incoming
from joop.agent.llm import AgentReply
from joop.channels.base import IncomingMessage
from joop.models import Business, Payment, Prospect, Service, Subscription
from joop.web.app import create_app
from joop.web.saas import slugify

from .conftest import NOW_UTC


def csrf_of(html: str) -> str:
    match = re.search(r'name="csrf" value="([^"]+)"', html)
    assert match, "no csrf token on page"
    return match.group(1)


@pytest.fixture
def saas_settings(settings):
    return dataclasses.replace(settings, owner_password="owner-pass-123", price_som=3000, trial_days=14,
                               freedompay_merchant_id="555", freedompay_secret_key="fp-secret")


@pytest.fixture
def app_client(saas_settings, rt, engine):
    rt.settings = saas_settings
    with TestClient(create_app(saas_settings, rt, init=False)) as c:
        yield c


def signup(client, name="Ак-Тиш Дент", niche="dental", password="long-password", phone="0555 123 456"):
    token = csrf_of(client.get("/signup").text)
    return client.post("/signup", data={"name": name, "niche": niche, "contact_name": "Бектур", "phone": phone,
                                        "password": password, "csrf": token}, follow_redirects=False)


def owner_login(client):
    token = csrf_of(client.get("/owner/login").text)
    r = client.post("/owner/login", data={"password": "owner-pass-123", "csrf": token}, follow_redirects=False)
    assert r.headers["location"] == "/owner"
    return csrf_of(client.get("/owner").text)


def test_slugify_transliterates_kyrgyz_and_russian():
    assert slugify("Ак-Тиш Дент") == "ak-tish-dent"
    assert slugify("Өрүк Кафе №1") == "oruk-kafe-1"
    assert slugify("!!!") == "biz"


def test_signup_creates_business_with_demo_data_and_trial(app_client):
    r = signup(app_client)
    assert r.status_code == 303 and r.headers["location"] == "/panel/setup"
    page = app_client.get("/panel/setup").text
    assert "Запуск" in page and "Пробный период" in page and "ak-tish-dent" in page
    with db.new_session() as s:
        b = s.exec(select(Business).where(Business.slug == "ak-tish-dent")).one()
        sub = billing.get_subscription(s, b.id)
        assert b.niche == "dental" and sub.status == "trial" and sub.contact_phone == "0555 123 456"
        assert b.phone == "0555 123 456" and b.address == ""  # the demo's fake contacts are not kept
        assert s.exec(select(Service).where(Service.business_id == b.id)).first() is not None  # demo price list


def test_signup_rejects_short_password_and_bots(app_client):
    r = signup(app_client, password="short")
    assert r.headers["location"] == "/signup"
    token = csrf_of(app_client.get("/signup").text)
    app_client.post("/signup", data={"name": "Bot", "phone": "0555123456", "password": "long-password",
                                     "website": "spam", "csrf": token})
    with db.new_session() as s:
        assert s.exec(select(Business)).all() == []


def test_second_business_with_same_name_gets_unique_login(app_client, saas_settings, rt):
    signup(app_client)
    with TestClient(create_app(saas_settings, rt, init=False)) as other:
        signup(other)
    with db.new_session() as s:
        slugs = sorted(b.slug for b in s.exec(select(Business)).all())
    assert slugs == ["ak-tish-dent", "ak-tish-dent-2"]


def test_subscription_states_and_ai_gate(engine, business, llm):
    now = NOW_UTC
    with db.new_session() as s:
        b = s.get(Business, business.id)
        assert billing.access_ok(s, b.id, now)  # no subscription row: never blocked
        sub = billing.start_trial(s, b, 14, now)
        assert billing.state(sub, now).code == "trial"
        assert billing.state(sub, now + timedelta(days=15)).code == "grace"
        assert billing.state(sub, now + timedelta(days=18)).code == "expired"
        sub.trial_ends_at = now - timedelta(days=10)
        s.add(sub)
        s.commit()
        incoming = IncomingMessage("telegram", "42", "text", "Сколько стоит чистка?", "Айбек", "m1")
        outcome = handle_incoming(s, b, incoming, lambda: llm, now)
        assert outcome.skipped == "subscription" and llm.calls == []


def test_payment_extends_period_once(engine, business):
    now = NOW_UTC
    with db.new_session() as s:
        billing.start_trial(s, s.get(Business, business.id), 14, now)
        pay = Payment(business_id=business.id, amount_som=3000)
        s.add(pay)
        s.flush()
        sub = billing.mark_paid(s, pay, now)
        assert sub.status == "active" and sub.paid_until == now + timedelta(days=30)
        billing.mark_paid(s, pay, now)  # a repeated callback does not add a second month
        assert sub.paid_until == now + timedelta(days=30)
        assert billing.mrr(s, now, 3000) == 3000


def test_freedompay_signature_roundtrip():
    params = {"pg_order_id": "7", "pg_amount": "3000", "pg_salt": "abc"}
    params["pg_sig"] = billing.fp_sign("result", params, "fp-secret")
    assert billing.fp_verify("result", params, "fp-secret")
    assert not billing.fp_verify("result", {**params, "pg_amount": "1"}, "fp-secret")
    assert "<pg_status>ok</pg_status>" in billing.fp_reply("result", "ok", "Принято", "fp-secret")


def _callback(client, payment_id, amount, result="1", secret="fp-secret"):
    params = {"pg_order_id": str(payment_id), "pg_amount": str(amount), "pg_result": result,
              "pg_payment_id": "fp-1", "pg_salt": "xyz"}
    params["pg_sig"] = billing.fp_sign("result", params, secret)
    return client.post("/billing/freedompay/result", data=params)


def test_card_payment_flow_and_callback(app_client, rt):
    signup(app_client)

    class FakeResponse:
        text = "<response><pg_status>ok</pg_status><pg_payment_id>fp-1</pg_payment_id><pg_redirect_url>https://pay.test/x</pg_redirect_url></response>"

    sent = {}

    class FakeHttp:
        def post(self, url, data):
            sent["url"], sent["data"] = url, data
            return FakeResponse()

    rt.http = FakeHttp()
    token = csrf_of(app_client.get("/panel/billing").text)
    r = app_client.post("/panel/billing/pay", data={"method": "card", "csrf": token}, follow_redirects=False)
    assert r.headers["location"] == "https://pay.test/x"
    assert sent["url"].endswith("/init_payment.php") and sent["data"]["pg_amount"] == "3000"
    assert billing.fp_verify("init_payment.php", sent["data"], "fp-secret")
    pid = int(sent["data"]["pg_order_id"])

    assert _callback(app_client, pid, 3000, secret="wrong").status_code == 403
    bad = _callback(app_client, pid, 10)
    assert "<pg_status>error</pg_status>" in bad.text
    ok = _callback(app_client, pid, 3000)
    assert ok.status_code == 200 and "<pg_status>ok</pg_status>" in ok.text
    with db.new_session() as s:
        assert s.get(Payment, pid).status == "paid"
        assert s.exec(select(Subscription)).one().status == "active"


def test_manual_payment_waits_for_owner(app_client):
    signup(app_client)
    token = csrf_of(app_client.get("/panel/billing").text)
    app_client.post("/panel/billing/pay", data={"method": "manual", "csrf": token})
    with db.new_session() as s:
        pay = s.exec(select(Payment)).one()
        assert pay.status == "pending" and pay.method == "manual"
    token = owner_login(app_client)
    assert "Ждут подтверждения" in app_client.get("/owner").text
    app_client.post(f"/owner/payment/{pay.id}", data={"action": "confirm", "csrf": token})
    with db.new_session() as s:
        assert s.get(Payment, pay.id).status == "paid"


def test_test_chat_answers_from_the_panel(app_client, llm):
    signup(app_client)
    llm.replies.append(AgentReply("Чистка стоит 2500 сом."))
    token = csrf_of(app_client.get("/panel/try").text)
    app_client.post("/panel/try", data={"text": "Сколько стоит чистка?", "csrf": token})
    page = app_client.get("/panel/try").text
    assert "Сколько стоит чистка?" in page and "Чистка стоит 2500 сом." in page
    assert "✓" in app_client.get("/panel/setup").text  # "test the AI" step is done


def test_telegram_one_step_connect(app_client, rt):
    signup(app_client)
    rt.tg.get_me = lambda: {"username": "aktish_bot"}
    rt.tg.set_webhook = lambda url, secret: url.endswith("/webhooks/telegram/ak-tish-dent")
    token = csrf_of(app_client.get("/panel/setup").text)
    r = app_client.post("/panel/setup/telegram", data={"token": "not-a-token", "csrf": token})
    assert "не похоже на токен" in r.text
    r = app_client.post("/panel/setup/telegram", data={"token": "123456789:" + "A" * 35, "csrf": token})
    assert "@aktish_bot подключён" in r.text


def test_owner_console_requires_password_and_manages_businesses(app_client, saas_settings, rt, engine):
    assert app_client.get("/owner", follow_redirects=False).headers["location"] == "/owner/login"
    signup(app_client)
    token = owner_login(app_client)
    page = app_client.get("/owner").text
    assert "Ак-Тиш Дент" in page and "Пробный период" in page
    with db.new_session() as s:
        bid = s.exec(select(Business)).one().id
    app_client.post(f"/owner/business/{bid}", data={"action": "paid", "csrf": token})
    assert "3 000" in app_client.get("/owner").text  # MRR
    r = app_client.post(f"/owner/business/{bid}", data={"action": "login", "csrf": token}, follow_redirects=False)
    assert r.headers["location"] == "/panel/setup"

    closed = dataclasses.replace(saas_settings, owner_password="")
    with TestClient(create_app(closed, rt, init=False)) as c:
        assert c.get("/owner/login").status_code == 404


def test_owner_login_wrong_password(app_client):
    token = csrf_of(app_client.get("/owner/login").text)
    app_client.post("/owner/login", data={"password": "nope", "csrf": token})
    assert app_client.get("/owner", follow_redirects=False).headers["location"] == "/owner/login"


def test_prospects_import_draft_and_demo(app_client, llm):
    token = owner_login(app_client)
    csv_text = "name,niche,phone,instagram,notes,language\nДент Плюс,dental,0555 111 222,dentplus,2 филиала,ru\nӨрүк,restaurant,,oruk.kg,,ky"
    app_client.post("/owner/prospects", data={"csv_text": csv_text, "csrf": token})
    with db.new_session() as s:
        items = s.exec(select(Prospect).order_by(Prospect.id)).all()
    assert [p.name for p in items] == ["Дент Плюс", "Өрүк"] and items[1].language == "ky"

    llm.write = lambda instruction, facts, usage: "Здравствуйте! " + facts.splitlines()[0]
    app_client.post(f"/owner/prospects/{items[0].id}", data={"action": "draft", "csrf": token})
    r = app_client.post(f"/owner/prospects/{items[0].id}", data={"action": "demo", "csrf": token})
    assert "Здравствуйте! Business: Дент Плюс" in r.text and "Демо создано" in r.text
    with db.new_session() as s:
        p = s.get(Prospect, items[0].id)
        assert p.status == "demo" and p.demo_business_id is not None
        assert billing.get_subscription(s, p.demo_business_id).source == "prospect"


def test_test_chat_has_a_daily_limit(app_client, monkeypatch):
    import joop.web.saas as saas

    monkeypatch.setattr(saas, "TRY_DAILY_LIMIT", 1)
    signup(app_client)
    token = csrf_of(app_client.get("/panel/try").text)
    app_client.post("/panel/try", data={"text": "Привет", "csrf": token})
    r = app_client.post("/panel/try", data={"text": "Ещё раз", "csrf": token})
    assert "не больше 1 сообщений" in r.text
