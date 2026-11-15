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


def test_a_restart_does_not_repeat_the_message_and_the_weekly_report_shows_what_calls_became(business, rt):
    from joop.models import Booking, MissedCall
    from joop.scheduler import weekly_report_text

    _setup(business.id, template="missed_call")
    assert missed_calls.process(rt, business.id, "+996700112233", NOW_UTC).sent == "template"
    missed_calls.reset()  # the server restarted: the table still knows the call
    assert missed_calls.process(rt, business.id, "+996700112233", NOW_UTC + timedelta(minutes=10)).skipped == "duplicate"
    assert missed_calls.process(rt, business.id, "+996777000111", NOW_UTC).sent == "template"
    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.wa_missed_call_template = ""
        s.add(b)
        s.commit()
    assert missed_calls.process(rt, business.id, "+996555999888", NOW_UTC).sent == ""  # staff told to call back
    with db.new_session() as s:
        b = s.get(Business, business.id)
        rows = s.exec(select(MissedCall).where(MissedCall.business_id == b.id)).all()
        assert sorted(r.sent for r in rows) == ["", "template", "template"]
        conv = s.exec(select(Conversation).where(Conversation.chat_id == "996700112233")).one()
        # the first caller wrote back and booked; the second never answered
        s.add(Message(business_id=b.id, conversation_id=conv.id, role="customer", text="Здравствуйте, хотел записаться",
                      created_at=NOW_UTC + timedelta(minutes=20)))
        s.add(Booking(business_id=b.id, conversation_id=conv.id, customer_name="Бакыт", start=NOW_UTC + timedelta(days=1),
                      channel="whatsapp", source="ai", created_at=NOW_UTC + timedelta(minutes=25)))
        s.commit()
        assert missed_calls.results(s, b, NOW_UTC - timedelta(days=1)) == (3, 2, 1, 1)
        text = weekly_report_text(s, b, NOW_UTC + timedelta(days=1))
    assert "Пропущенных звонков: 3; Joop написал звонившим в WhatsApp: 2, ответили: 1, записались или заказали: 1." in text


def test_calls_only_passed_to_staff_are_reported_as_such(business, rt):
    _setup(business.id, wa=False)
    missed_calls.process(rt, business.id, "+996555999888", NOW_UTC)
    with db.new_session() as s:
        assert missed_calls.results(s, s.get(Business, business.id), NOW_UTC - timedelta(days=1)) == (1, 0, 0, 0)


def test_a_leaked_code_cannot_turn_whatsapp_into_a_mailer(business, rt, monkeypatch):
    _setup(business.id, template="missed_call")
    monkeypatch.setattr(missed_calls, "PER_HOUR", 3)
    for i in range(3):
        assert missed_calls.process(rt, business.id, f"+99670011220{i}", NOW_UTC).sent == "template"
    flood = missed_calls.process(rt, business.id, "+996700112299", NOW_UTC + timedelta(minutes=1))
    assert flood.sent == "" and "смените код" in flood.notes[0] and len(rt.wa.templates) == 3
    again = missed_calls.process(rt, business.id, "+996700112298", NOW_UTC + timedelta(minutes=2))
    assert again.sent == "" and len(again.notes) == 1 and "смените код" not in again.notes[0]  # the warning once per flood
    assert missed_calls.process(rt, business.id, "+996700112297", NOW_UTC + timedelta(hours=2)).sent == "template"


def test_strangers_abroad_and_silent_callers_are_not_written_to_again(business, rt):
    _setup(business.id, template="missed_call")
    abroad = missed_calls.process(rt, business.id, "+8613800138000", NOW_UTC)
    assert abroad.sent == "" and "другой страны" in abroad.notes[0] and rt.wa.templates == []
    assert missed_calls.process(rt, business.id, "+996700112233", NOW_UTC).sent == "template"
    second = missed_calls.process(rt, business.id, "+996700112233", NOW_UTC + timedelta(hours=1))
    assert second.sent == "" and "снова" in second.notes[0] and len(rt.wa.templates) == 1
    with db.new_session() as s:
        conv = s.exec(select(Conversation).where(Conversation.chat_id == "996700112233")).one()
        s.add(Message(business_id=business.id, conversation_id=conv.id, role="customer", text="Да, слушаю",
                      created_at=NOW_UTC + timedelta(hours=2)))
        conv.last_customer_at = NOW_UTC + timedelta(hours=2)
        s.add(conv)
        s.commit()
    # they answered, then called again later: written to (within the 24-hour window, as free text)
    assert missed_calls.process(rt, business.id, "+996700112233", NOW_UTC + timedelta(hours=3)).sent == "text"


def test_results_credit_the_latest_call_and_leave_out_tests_and_the_owners_own_number(business, rt):
    from joop.models import Booking

    _setup(business.id, template="missed_call")
    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.phone = "0555 000 111"
        conv = Conversation(business_id=b.id, channel="whatsapp", chat_id="996700112233", last_customer_at=NOW_UTC - timedelta(hours=1))
        test = Conversation(business_id=b.id, channel="whatsapp", chat_id="996777000999", last_customer_at=NOW_UTC - timedelta(hours=1),
                            staff_test=True)
        s.add_all([b, conv, test])
        s.commit()
    assert missed_calls.process(rt, business.id, "+996700112233", NOW_UTC).sent == "text"
    with db.new_session() as s:
        conv = s.exec(select(Conversation).where(Conversation.chat_id == "996700112233")).one()
        s.add(Message(business_id=business.id, conversation_id=conv.id, role="customer", text="?", created_at=NOW_UTC + timedelta(minutes=5)))
        s.commit()
    assert missed_calls.process(rt, business.id, "+996700112233", NOW_UTC + timedelta(hours=2)).sent == "text"  # called again
    assert missed_calls.process(rt, business.id, "+996777000999", NOW_UTC).sent == "text"  # the owner's test chat
    assert missed_calls.process(rt, business.id, "+996555000111", NOW_UTC).sent == "template"  # the business's own phone
    with db.new_session() as s:
        b = s.get(Business, business.id)
        s.add(Message(business_id=b.id, conversation_id=conv.id, role="customer", text="Записываюсь", created_at=NOW_UTC + timedelta(hours=3)))
        s.add(Booking(business_id=b.id, conversation_id=conv.id, customer_name="Бакыт", start=NOW_UTC + timedelta(days=1),
                      channel="whatsapp", source="ai", created_at=NOW_UTC + timedelta(hours=3)))
        s.commit()
        assert missed_calls.results(s, b, NOW_UTC - timedelta(days=1)) == (2, 2, 2, 1)  # one booking, not two


def test_unreadable_numbers_still_reach_staff_and_a_stray_character_is_a_refusal(web, business, rt):
    assert missed_calls.raw_caller({"phone": " 998901234567"}) == "+998901234567"  # an unencoded "+" in a form body
    assert missed_calls.caller({"phone": " 998901234567"}) == "+998901234567"
    assert "номер не определился (Unknown)" in missed_calls.unknown_note("Unknown")
    _setup(business.id)
    url = f"/webhooks/missed-call/{business.slug}"
    assert web.post(url, data={"phone": "Unknown"}, headers={"X-Joop-Token": "secret-token"}).json()["phone"] is False
    assert rt.tg.sent[-1] == ("555", "Пропущенный звонок: номер не определился (Unknown). Проверьте журнал звонков на телефоне.")
    assert web.post(url, data={"phone": "1"}, headers={"X-Joop-Token": "sécret".encode()}).status_code == 403
    assert web.post(f"/webhooks/telegram/{business.slug}", json={}, headers={"X-Telegram-Bot-Api-Secret-Token": "é".encode()}).status_code == 403
