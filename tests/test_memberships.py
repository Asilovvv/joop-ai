from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlmodel import select

from joop import db, memberships
from joop.agent.engine import handle_incoming
from joop.channels.base import IncomingMessage
from joop.models import Booking, Business, Conversation, Membership
from joop.presets import create_business
from joop.timeutil import utc_to_local
from joop.web.app import create_app

from .conftest import NOW_UTC, FakeLLM
from .test_web import csrf_of

TODAY = utc_to_local(NOW_UTC, "Asia/Bishkek").date()


def gym():
    with db.new_session() as s:
        b = create_business(s, slug="gym", name="Фитнес", password="gym-pass-1", niche="fitness", demo=True, now_utc=NOW_UTC)
        s.add(Membership(business_id=b.id, customer_name="Сауле", customer_phone="+996 555 123 456", phone_key="555123456",
                         title="10 занятий йоги", visits_total=10, visits_used=3, valid_until=TODAY + timedelta(days=20)))
        s.commit()
        return b


def ask(business_id, channel, chat, text, ext):
    llm = FakeLLM()
    with db.new_session() as s:
        handle_incoming(s, s.get(Business, business_id), IncomingMessage(channel, chat, "text", text, "", ext), lambda: llm, NOW_UTC)
        s.commit()
    return llm.calls[-1]["system"]


def test_helpers():
    m = Membership(business_id=1, title="x", visits_total=5, visits_used=5)
    assert memberships.left(m) == 0 and not memberships.usable(m, TODAY)
    assert memberships.left(Membership(business_id=1, title="x")) is None
    assert memberships.phone_key("+996 (555) 12-34-56") == "555123456" and memberships.phone_key("12") == ""


def test_whatsapp_number_sees_its_pass(engine):
    b = gym()
    system = ask(b.id, "whatsapp", "996555123456", "Сколько у меня осталось занятий?", "m1")
    assert "«10 занятий йоги», осталось 7 из 10 посещений, действует до" in system


def test_typed_phone_alone_reveals_nothing(engine):
    b = gym()
    with db.new_session() as s:
        conv = Conversation(business_id=b.id, channel="telegram", chat_id="t1", customer_phone="0555 123 456")
        s.add(conv)
        s.commit()
        cid = conv.id
    system = ask(b.id, "telegram", "t1", "Сколько осталось занятий? мой номер 0555 123 456", "m2")
    assert "7 из 10" not in system and "не называй цифры" in system
    with db.new_session() as s:  # after a visit booked from this chat the phone is trusted
        s.add(Booking(business_id=b.id, conversation_id=cid, start=utc_to_local(NOW_UTC, b.timezone) - timedelta(days=2),
                      customer_phone="0555 123 456", channel="telegram", chat_id="t1"))
        s.commit()
    assert "7 из 10" in ask(b.id, "telegram", "t1", "А сейчас?", "m3")


def test_niches_without_passes_get_no_hint(engine, business):
    assert "абонемент" not in ask(business.id, "whatsapp", "996555123456", "Сколько осталось?", "m4").lower()


def test_panel(engine, settings, rt):
    gym()
    with TestClient(create_app(settings, rt, init=False)) as c:
        token = csrf_of(c.get("/login").text)
        c.post("/login", data={"slug": "gym", "password": "gym-pass-1", "csrf": token})
        page = c.get("/panel/memberships")
        token = csrf_of(page.text)
        assert "Абонементы" in page.text and "7 из 10" in page.text
        r = c.post("/panel/memberships", data={"customer_phone": "0700 111 222", "customer_name": "Бек", "title": "5 тренировок",
                                               "visits_total": "1", "valid_until": (TODAY + timedelta(days=30)).isoformat(), "csrf": token})
        assert "Абонемент добавлен" in r.text
        with db.new_session() as s:
            mid = s.exec(select(Membership).where(Membership.title == "5 тренировок")).one().id
        assert "осталось 0" in c.post(f"/panel/memberships/{mid}", data={"action": "visit", "csrf": token}).text
        assert "не осталось" in c.post(f"/panel/memberships/{mid}", data={"action": "visit", "csrf": token}).text
        assert "Сауле" in c.get("/panel/memberships?q=555 123 456").text
        assert "Бек" not in c.get("/panel/memberships?q=555 123 456").text


def test_panel_hidden_for_dental(engine, settings, rt, business):
    with TestClient(create_app(settings, rt, init=False)) as c:
        token = csrf_of(c.get("/login").text)
        c.post("/login", data={"slug": "aktish", "password": "secret-pass", "csrf": token})
        assert c.get("/panel/memberships").status_code == 404
