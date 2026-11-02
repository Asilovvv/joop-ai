"""Staff answer a customer from the panel through the customer's channel (joop/staff_reply.py)."""

import re
from datetime import timedelta

from sqlmodel import select

from joop import db
from joop.channels.base import IncomingMessage
from joop.dispatch import process_incoming
from joop.models import Business, Conversation, Lead, Message
from joop.timeutil import utcnow

from .test_web import client, csrf_of, login  # noqa: F401  (client is a fixture)


def chat(business_id, channel="telegram", chat_id="c1", wrote_hours_ago=1.0, lead=True):
    with db.new_session() as s:
        b = s.get(Business, business_id)
        b.wa_phone_number_id, b.wa_access_token, b.admin_chat_ids = "555", "wa-test", "999"
        s.add(b)
        conv = Conversation(business_id=business_id, channel=channel, chat_id=chat_id, customer_name="Айбек",
                            customer_phone="0555 123 456", last_customer_at=utcnow() - timedelta(hours=wrote_hours_ago))
        s.add(conv)
        s.flush()
        if lead:
            s.add(Lead(business_id=business_id, conversation_id=conv.id, kind="handoff", summary="Жалоба"))
        s.commit()
        return conv.id


def reply(client, conv_id, text="Здравствуйте! Это администратор, разберёмся.", follow=True):  # noqa: F811
    page = client.get(f"/panel/conversations/{conv_id}").text
    return client.post(f"/panel/conversations/{conv_id}/reply", data={"csrf": csrf_of(page), "text": text}, follow_redirects=follow)


def test_telegram_reply_goes_through_the_bot_pauses_the_ai_and_closes_requests(client, business, rt):  # noqa: F811
    login(client)
    conv_id = chat(business.id)
    page = reply(client, conv_id).text
    assert "Ответ отправлен" in page and "Здравствуйте! Это администратор" in page
    assert ("c1", "Здравствуйте! Это администратор, разберёмся.") in rt.tg.sent
    with db.new_session() as s:
        conv = s.get(Conversation, conv_id)
        assert conv.ai_paused_until > utcnow() + timedelta(hours=11)
        assert s.exec(select(Message.role).where(Message.conversation_id == conv_id)).all() == ["staff"]
        assert s.exec(select(Lead.status).where(Lead.conversation_id == conv_id)).one() == "done"
    assert "Напишите текст ответа" in reply(client, conv_id, text="  ").text


def test_whatsapp_only_within_24_hours(client, business, rt):  # noqa: F811
    login(client)
    late = chat(business.id, channel="whatsapp", chat_id="996555000111", wrote_hours_ago=30)
    page = client.get(f"/panel/conversations/{late}").text
    assert "только в течение суток" in page and "0555 123 456" in page and f"/panel/conversations/{late}/reply" not in page
    assert "только в течение суток" in client.post(f"/panel/conversations/{late}/reply", data={"csrf": csrf_of(page), "text": "Привет"}).text
    assert rt.wa.sent == []
    fresh = chat(business.id, channel="whatsapp", chat_id="996555000222", wrote_hours_ago=2)
    assert "Ответ отправлен" in reply(client, fresh).text and rt.wa.sent[0][0] == "996555000222"


def test_web_chat_visitor_sees_the_reply(client, business):  # noqa: F811
    login(client)
    visitor = "ab" * 12
    conv_id = chat(business.id, channel="web", chat_id=f"web-{visitor}")
    assert "клиент увидит его в чате на сайте" in client.get(f"/panel/conversations/{conv_id}").text
    assert "Ответ отправлен" in reply(client, conv_id, text="Ждём вас в 15:00").text
    got = client.get(f"/c/aktish/updates?visitor={visitor}&after=0")
    assert got.headers["cache-control"] == "no-store"
    [m] = got.json()["messages"]
    assert m["text"] == "Ждём вас в 15:00"
    assert client.get(f"/c/aktish/updates?visitor={visitor}&after={m['id']}").json() == {"messages": []}
    assert client.get("/c/aktish/updates?visitor=../etc&after=0").json() == {"messages": []}
    assert client.get(f"/c/aktish/updates?visitor={'cd' * 12}&after=0").json() == {"messages": []}  # another visitor
    assert client.get(f"/c/nope/updates?visitor={visitor}").status_code == 404
    page = client.get("/c/aktish").text
    assert "/updates?visitor=" in page and re.search(r"setInterval\(poll, 15000\)", page)


def test_test_chat_cannot_be_answered(client, business):  # noqa: F811
    login(client)
    conv_id = chat(business.id, channel="console", chat_id="panel-1")
    assert "это тестовый чат" in client.get(f"/panel/conversations/{conv_id}").text


def test_customer_writing_while_staff_answer_reaches_staff(business, rt):
    conv_id = chat(business.id)
    with db.new_session() as s:
        conv = s.get(Conversation, conv_id)
        conv.ai_paused_until = utcnow() + timedelta(hours=12)
        s.add(conv)
        s.commit()
    out = process_incoming(rt, business.id, IncomingMessage("telegram", "c1", "text", "А во сколько можно прийти?", "Айбек", "tg:c1:9"))
    assert out.skipped == "paused" and not out.reply
    [note] = [t for chat_id, t in rt.tg.sent if chat_id == "999"]
    assert note == ("Айбек пишет в диалог, где отвечаете вы (Telegram): «А во сколько можно прийти?»\n"
                    f"Ответить: https://joop.test/panel/conversations/{conv_id}")
    wa = chat(business.id, channel="whatsapp", chat_id="996555000333")
    with db.new_session() as s:
        conv = s.get(Conversation, wa)
        conv.ai_paused_until = utcnow() + timedelta(hours=12)
        s.add(conv)
        s.commit()
    out = process_incoming(rt, business.id, IncomingMessage("whatsapp", "996555000333", "text", "Ау", "", "wa:9"))
    assert out.skipped == "paused" and out.admin_notes == []  # staff see WhatsApp in their own app
