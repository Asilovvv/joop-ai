import json
import re

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from joop import db, studio
from joop.models import StudioRequest
from joop.web.app import create_app

from .test_saas import csrf_of, owner_login, saas_settings  # noqa: F401  (fixture)

GOOD = json.dumps({
    "headline": "Стоматология в Джале", "subheadline": "Лечение и чистка без очередей",
    "services": [{"name": "Чистка", "price": "2500 сом", "note": ""}, {"name": "<script>x</script>", "price": "", "note": ""}],
    "about": "Работаем с 2020 года.", "address": "Бишкек, Джал", "hours": "Пн–Сб 9–19", "phone": "0555 123 456",
    "instagram": "@dent.jal", "cta": "Записаться",
}, ensure_ascii=False)


@pytest.fixture
def client(saas_settings, rt, engine):  # noqa: F811
    rt.settings = saas_settings
    with TestClient(create_app(saas_settings, rt, init=False)) as c:
        yield c


def test_parse_site_keeps_only_known_fields_and_strips_markup():
    site = studio.parse_site("Вот JSON:\n" + GOOD)
    assert site["headline"] == "Стоматология в Джале" and site["instagram"] == "dent.jal"
    assert site["services"][1]["name"] == "scriptx/script"  # angle brackets removed
    assert studio.parse_site("no json here") is None
    assert studio.parse_site('{"headline": ""}') is None
    assert studio.phone_digits("0555 123 456") == "996555123456"


def order(client, **over):
    token = csrf_of(client.get("/studio").text)
    data = {"kind": "site", "business_name": "Дент Джал", "contact_name": "Айгуль", "phone": "0555 123 456",
            "niche": "dental", "description": "Чистка 2500 сом, лечение кариеса от 2000. Адрес Джал, 9-19.", "csrf": token}
    data.update(over)
    return client.post("/studio", data=data)


def test_public_order_is_saved_and_validated(client):
    assert "Заявка принята" in order(client).text
    assert "Подождите" in order(client).text  # 30-second guard
    with db.new_session() as s:
        items = s.exec(select(StudioRequest)).all()
    assert len(items) == 1 and items[0].business_name == "Дент Джал" and items[0].status == "new"


def test_short_order_and_bot_are_rejected(saas_settings, rt, engine):  # noqa: F811
    with TestClient(create_app(saas_settings, rt, init=False)) as c:
        assert "опишите" in order(c, description="коротко").text.lower()
    with TestClient(create_app(saas_settings, rt, init=False)) as c:
        order(c, website="spam")
    with db.new_session() as s:
        assert s.exec(select(StudioRequest)).all() == []


def test_owner_drafts_edits_and_publishes_site(client, llm):
    order(client)
    token = owner_login(client)
    with db.new_session() as s:
        rid = s.exec(select(StudioRequest)).one().id
    assert client.get("/site/dent-dzhal").status_code == 404
    llm.write = lambda instruction, facts, usage: GOOD
    r = client.post(f"/owner/studio/{rid}", data={"action": "draft", "csrf": token})
    assert "Черновик сайта готов" in r.text and "Стоматология в Джале" in r.text
    client.post(f"/owner/studio/{rid}", data={"action": "save", "headline": "Дент Джал: стоматология", "csrf": token})
    client.post(f"/owner/studio/{rid}", data={"action": "publish", "csrf": token})
    page = client.get("/site/dent-dzhal")
    assert page.status_code == 200 and "Дент Джал: стоматология" in page.text and "2500 сом" in page.text
    assert "https://wa.me/996555123456" in page.text and "<script>" not in page.text
    client.post(f"/owner/studio/{rid}", data={"action": "status", "status": "paid", "price_som": "5000", "csrf": token})
    with db.new_session() as s:
        r = s.get(StudioRequest, rid)
        assert r.status == "paid" and r.price_som == 5000 and r.published


def test_studio_console_requires_owner(client):
    assert client.get("/owner/studio", follow_redirects=False).headers["location"] == "/owner/login"


def test_prospect_site_offer_uses_site_writer(client, llm):
    token = owner_login(client)
    client.post("/owner/prospects", data={"name": "Кафе Ала-Тоо", "niche": "restaurant", "csrf": token})
    seen = {}

    def write(instruction, facts, usage):
        seen["instruction"] = instruction
        return "Здравствуйте! Можем сделать меню онлайн."

    llm.write = write
    from joop.models import Prospect

    with db.new_session() as s:
        pid = s.exec(select(Prospect)).one().id
    r = client.post(f"/owner/prospects/{pid}", data={"action": "draft_site", "csrf": token})
    assert "Joop Studio" in seen["instruction"] and "меню онлайн" in r.text


def test_booking_url_accepts_only_messenger_links():
    assert studio.clean_booking_url("https://t.me/dent_jal_bot") == "https://t.me/dent_jal_bot"
    assert studio.clean_booking_url("https://wa.me/996555123456") == "https://wa.me/996555123456"
    assert studio.clean_booking_url("javascript:alert(1)") == ""
    assert studio.clean_booking_url("https://evil.example/t.me/x") == ""


def test_studio_order_becomes_joop_company_with_trial(client):
    from joop import billing
    from joop.models import Business, Service

    token = owner_login(client)
    with db.new_session() as s:
        r = StudioRequest(kind="site", business_name="Дент Джал", contact_name="Айгуль", phone="0555 123 456",
                          niche="dental", description="Нужен сайт для стоматологии", content_json=GOOD,
                          public_slug="dent-dzhal", published=True)
        s.add(r)
        s.commit()
        rid = r.id
    page = client.get("/owner/studio")
    assert "Подключить ИИ-администратора" in page.text
    resp = client.post(f"/owner/studio/{rid}", data={"action": "create_business", "csrf": token})
    assert "Компания Joop AI создана" in resp.text
    with db.new_session() as s:
        r = s.get(StudioRequest, rid)
        b = s.get(Business, r.business_id)
        services = s.exec(select(Service).where(Service.business_id == b.id).order_by(Service.sort)).all()
        assert b.niche == "dental" and b.address == "Бишкек, Джал" and b.hours_text == "Пн–Сб 9–19"
        assert services[0].name == "Чистка" and services[0].price_value == 2500
        assert billing.get_subscription(s, b.id).status == "trial"
    # A second click does not create a duplicate company.
    assert client.post(f"/owner/studio/{rid}", data={"action": "create_business", "csrf": token}).status_code == 400
    # The site's main button leads to the bot once the link is saved; unsafe links are refused.
    client.post(f"/owner/studio/{rid}", data={"action": "save", "booking_url": "javascript:alert(1)", "csrf": token})
    assert "Записаться через ИИ" not in client.get("/site/dent-dzhal").text
    client.post(f"/owner/studio/{rid}", data={"action": "save", "booking_url": "https://t.me/dent_jal_bot", "csrf": token})
    site = client.get("/site/dent-dzhal").text
    assert "Записаться через ИИ" in site and "https://t.me/dent_jal_bot" in site
