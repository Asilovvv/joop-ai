"""A missed call becomes a WhatsApp message and a note to staff (joop/missed_calls.py)."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from joop import db, missed_calls
from joop.models import Business, Conversation, Message
from joop.web.app import create_app

from .conftest import NOW_UTC
from .test_web import csrf_of, login


@pytest.fixture(autouse=True)
def fresh():
    missed_calls.reset()
    yield
    missed_calls.reset()


def _setup(business_id, template="", wa=True):
    with db.new_session() as s:
        b = s.get(Business, business_id)
        b.telegram_bot_token, b.admin_chat_ids = "1:x", "555"
        if wa:
            b.wa_phone_number_id, b.wa_access_token = "pn-1", "wa-token"
        b.wa_missed_call_template = template
        b.missed_call_token = "secret-token"
        s.add(b)
        s.commit()


def test_caller_reads_the_number_whatever_the_phone_sent():
    assert missed_calls.caller({"phone": "0555 123 456"}) == "+996555123456"
    assert missed_calls.caller({"call_number": "+996 700 11 22 33"}) == "+996700112233"
    assert missed_calls.caller({"caller_id": "996555123456"}) == "+996555123456"
    assert missed_calls.caller({"phone": "Скрытый номер"}) is None and missed_calls.caller({}) is None


def test_a_recent_customer_gets_text_others_the_template_and_rings_count_once(business, rt):
    _setup(business.id, template="missed_call")
    with db.new_session() as s:
        recent = Conversation(business_id=business.id, channel="whatsapp", chat_id="996555123456", customer_name="Айгерим",
                              last_customer_at=NOW_UTC - timedelta(hours=2))
        s.add(recent)
        s.commit()
    first = missed_calls.process(rt, business.id, "+996555123456", NOW_UTC)
    assert first.sent == "text" and rt.wa.sent[-1][0] == "996555123456"
    assert "не успели ответить на ваш звонок" in rt.wa.sent[-1][1]
    assert rt.tg.sent[-1] == ("555", "Пропущенный звонок: Айгерим (+996555123456). Joop написал в WhatsApp, ИИ ответит, если клиент напишет.")
    assert missed_calls.process(rt, business.id, "+996555123456", NOW_UTC).skipped == "duplicate"  # it rang again

    stranger = missed_calls.process(rt, business.id, "+996700112233", NOW_UTC)
    assert stranger.sent == "template" and rt.wa.templates[-1] == ("996700112233", "missed_call", "ru", [business.name])
    with db.new_session() as s:
        conv = s.exec(select(Conversation).where(Conversation.chat_id == "996700112233")).one()
        assert conv.channel == "whatsapp" and conv.customer_phone == "+996700112233" and conv.last_customer_at is None
        assert "missed_call" in s.exec(select(Message.text).where(Message.conversation_id == conv.id)).one()


def test_without_a_template_or_whatsapp_staff_are_told_to_call_back(business, rt):
    _setup(business.id)
    out = missed_calls.process(rt, business.id, "+996700112233", NOW_UTC)
    assert out.sent == "" and rt.wa.templates == [] and rt.wa.sent == []
    assert "Перезвоните (в WhatsApp можно написать первым только шаблоном" in rt.tg.sent[-1][1]
    _setup(business.id, template="missed_call", wa=False)
    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.wa_access_token = ""
        s.add(b)
        s.commit()
    assert missed_calls.process(rt, business.id, "+996777000111", NOW_UTC).notes == ["Пропущенный звонок: +996777000111. Перезвоните."]


def test_a_blocked_number_gets_nothing(business, rt):
    _setup(business.id, template="missed_call")
    with db.new_session() as s:
        s.add(Conversation(business_id=business.id, channel="whatsapp", chat_id="996700112233", blocked_at=NOW_UTC))
        s.commit()
    assert missed_calls.process(rt, business.id, "+996700112233", NOW_UTC).skipped == "blocked"
    assert rt.wa.templates == [] and rt.tg.sent == []


@pytest.fixture
def web(settings, rt, business):
    with TestClient(create_app(settings, rt, init=False)) as c:
        yield c


def test_webhook_needs_the_secret_header_and_the_panel_switches_it(web, business, rt):
    url = f"/webhooks/missed-call/{business.slug}"
    assert web.post(url, data={"phone": "0700112233"}).status_code == 403  # off: no token yet
    token = login(web)
    page = web.get("/panel/channels").text
    assert 'id="missed-calls"' in page and "Включить" in page
    web.post("/panel/channels/missed-calls", data={"csrf": token, "action": "on"})
    with db.new_session() as s:
        secret = s.get(Business, business.id).missed_call_token
    assert secret and secret in web.get("/panel/channels").text
    assert web.post(url, data={"phone": "0700112233"}, headers={"X-Joop-Token": "wrong"}).status_code == 403
    r = web.post(url, data={"phone": "0700112233"}, headers={"X-Joop-Token": secret})
    assert r.status_code == 200 and r.json()["phone"] is True
    assert web.post(url, json={"caller_id": "996700112244"}, headers={"X-Joop-Token": secret}).json()["phone"] is True
    assert web.post(url, data={"phone": "скрыт"}, headers={"X-Joop-Token": secret}).json()["phone"] is False
    web.post("/panel/channels/missed-calls", data={"csrf": csrf_of(web.get("/panel/channels").text), "action": "off"})
    assert web.post(url, data={"phone": "0700112233"}, headers={"X-Joop-Token": secret}).status_code == 403
