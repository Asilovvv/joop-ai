from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from joop import db, followups
from joop.agent.engine import handle_incoming
from joop.channels.base import IncomingMessage
from joop.models import Booking, Business, Conversation, Lead, Message, Service
from joop.scheduler import run_due_jobs
from joop.timeutil import utc_to_local
from joop.web.app import create_app

from .conftest import NOW_UTC, FakeLLM
from .test_web import csrf_of, login

DAY_UTC = NOW_UTC - timedelta(hours=8)  # 15:14 in Bishkek: inside the hours when follow-ups go out


def visit(business_id, start, channel="telegram", chat="777", service="Профессиональная чистка", phone="0555 111 222",
          last_customer_at=None):
    with db.new_session() as s:
        conv = Conversation(business_id=business_id, channel=channel, chat_id=chat, customer_name="Айбек",
                            customer_phone=phone, last_customer_at=last_customer_at)
        s.add(conv)
        s.flush()
        b = Booking(business_id=business_id, conversation_id=conv.id, start=start, service=service, staff_name="Доктор",
                    customer_name="Айбек", customer_phone=phone, channel=channel, chat_id=chat)
        s.add(b)
        s.commit()
        return b.id, conv.id


def enable(business_id, **values):
    with db.new_session() as s:
        b = s.get(Business, business_id)
        for k, v in values.items():
            setattr(b, k, v)
        s.add(b)
        s.commit()


def say(business_id, chat, text, llm, ext, when=DAY_UTC):
    with db.new_session() as s:
        b = s.get(Business, business_id)
        out = handle_incoming(s, b, IncomingMessage("telegram", chat, "text", text, "", ext), lambda: llm, when)
        s.commit()
        return out


def test_rating_request_then_high_and_low_ratings(business, rt):
    enable(business.id, review_requests=True, review_url="https://2gis.kg/bishkek/firm/1")
    local = utc_to_local(DAY_UTC, business.timezone)
    good, _ = visit(business.id, local - timedelta(hours=3), chat="701")
    bad, _ = visit(business.id, local - timedelta(hours=4), chat="702")
    soon, _ = visit(business.id, local - timedelta(minutes=30), chat="703")  # visit not over yet
    wa, _ = visit(business.id, local - timedelta(hours=3), channel="whatsapp", chat="996555")  # outside the 24h window
    with db.new_session() as s:
        report = run_due_jobs(s, rt, s.get(Business, business.id), DAY_UTC)
        s.commit()
    assert report["reviews"] == 2
    assert sorted(c for c, _ in rt.tg.sent) == ["701", "702"] and "от 1 до 5" in rt.tg.sent[0][1]
    with db.new_session() as s:
        assert s.get(Booking, soon).review_status == "" and s.get(Booking, wa).review_status == "skipped"

    llm = FakeLLM()
    out = say(business.id, "701", "5", llm, "r1")
    assert "https://2gis.kg/bishkek/firm/1" in out.reply and not llm.calls and not out.admin_notes
    out = say(business.id, "702", "2 из 5", llm, "r2")
    assert "администратор" in out.reply and "Низкая оценка 2/5" in out.admin_notes[0] and not llm.calls
    with db.new_session() as s:
        assert (s.get(Booking, good).rating, s.get(Booking, bad).rating) == (5, 2)
        assert s.get(Lead, out.lead_id).kind == "handoff"
    # Once rated, a digit is an ordinary message again.
    say(business.id, "701", "3", llm, "r3")
    assert len(llm.calls) == 1


def test_no_rating_capture_without_a_request(business):
    llm = FakeLLM()
    visit(business.id, utc_to_local(DAY_UTC, business.timezone) - timedelta(hours=3), chat="704")
    say(business.id, "704", "5", llm, "r4")
    assert len(llm.calls) == 1


def test_kyrgyz_customer_gets_kyrgyz_request(business, rt):
    enable(business.id, review_requests=True)
    _, conv = visit(business.id, utc_to_local(DAY_UTC, business.timezone) - timedelta(hours=3), chat="705")
    with db.new_session() as s:
        s.add(Message(business_id=business.id, conversation_id=conv, role="customer", text="Тиш тазалоого жазылгым келет"))
        s.commit()
        run_due_jobs(s, rt, s.get(Business, business.id), DAY_UTC)
        s.commit()
    assert "баалаңыз" in rt.tg.sent[0][1]


def test_return_invites(business, rt):
    with db.new_session() as s:
        svc = s.exec(select(Service).where(Service.business_id == business.id)).first()
        svc.repeat_days = 21
        s.add(svc)
        s.commit()
        name = svc.name
    enable(business.id, return_invites=True, reminder_hour=15, admin_chat_ids="900")
    local = utc_to_local(DAY_UTC, business.timezone)
    due, _ = visit(business.id, local - timedelta(days=21), chat="801", service=name.lower(), phone="0555 801 801")
    back, _ = visit(business.id, local - timedelta(days=22), chat="802", service=name, phone="0555 802 802")
    visit(business.id, local + timedelta(days=2), chat="899", service=name, phone="+996 555 802 802")  # booked again
    early, _ = visit(business.id, local - timedelta(days=10), chat="803", service=name, phone="0555 803 803")
    wa, _ = visit(business.id, local - timedelta(days=21), channel="whatsapp", chat="996555804", service=name, phone="0555 804 804")
    with db.new_session() as s:
        report = run_due_jobs(s, rt, s.get(Business, business.id), DAY_UTC)
        s.commit()
        assert report["returns"] == {"sent": 1, "manual": 1}
        assert s.get(Booking, due).return_status == "sent" and s.get(Booking, back).return_status == ""
        assert s.get(Booking, early).return_status == "" and s.get(Booking, wa).return_status == "manual"
    texts = dict(rt.tg.sent)
    assert "прошло 21 день" in texts["801"] and "Записать вас снова" in texts["801"]
    assert any("Пора пригласить снова" in t and "0555 804 804" in t for _, t in rt.tg.sent)
    st = followups.stats(db.new_session(), business.id, DAY_UTC - timedelta(days=30))
    assert st.invited == 2


@pytest.fixture
def client(settings, rt, business):
    with TestClient(create_app(settings, rt, init=False)) as c:
        yield c


def test_panel_saves_settings_and_rejects_foreign_links(client, business):
    token = login(client)
    page = client.get("/panel/followups")
    assert "Отзывы и возврат" in page.text
    with db.new_session() as s:
        sid = s.exec(select(Service).where(Service.business_id == business.id)).first().id
    r = client.post("/panel/followups", data={"review_requests": "1", "review_url": "https://evil.example/x",
                                              f"repeat_{sid}": "180", "csrf": token})
    assert "не сохранена" in r.text
    client.post("/panel/followups", data={"review_requests": "1", "return_invites": "1",
                                          "review_url": "https://2gis.kg/bishkek/firm/70000001", f"repeat_{sid}": "180", "csrf": token})
    with db.new_session() as s:
        b = s.get(Business, business.id)
        assert b.review_requests and b.return_invites and b.review_url.startswith("https://2gis.kg/")
        assert s.get(Service, sid).repeat_days == 180
