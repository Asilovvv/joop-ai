"""The test chat in the owner's app: the panel's «Тестовый чат» (joop/try_chat.py), so an owner who signed up on the
phone checks the AI there too; the test is counted nowhere and «Новый диалог» frees what it booked."""

from datetime import timedelta

from sqlmodel import select

from joop import db, stats, try_chat
from joop.agent.llm import AgentReply
from joop.models import Booking, Business, Conversation, PanelUser, Slot
from joop.security import hash_password
from joop.timeutil import utc_to_local, utcnow

from .test_mobile import auth, client, sign_in  # noqa: F401 - the client fixture


def _slot(business_id: int) -> Slot:
    with db.new_session() as s:
        b = s.get(Business, business_id)
        now_local = utc_to_local(utcnow(), b.timezone)
        return s.exec(select(Slot).where(Slot.business_id == b.id, Slot.status == "free",
                                         Slot.start > now_local + timedelta(hours=3)).order_by(Slot.start)).first()


def test_the_owner_tries_the_ai_and_a_new_dialogue_cancels_the_test_booking(client, business, llm):
    h = auth(sign_in(client).json()["token"])
    assert client.get("/api/mobile/try", headers=h).json() == {"messages": []}
    slot = _slot(business.id)
    llm.replies.append(AgentReply("Записала вас!", booking={"slot_id": slot.id, "name": "Тест", "phone": "0555 123 456"}))
    r = client.post("/api/mobile/try", headers=h, json={"text": "Запишите меня, Тест, 0555 123 456"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert [m["role"] for m in data["messages"]] == ["customer", "ai"]
    assert data["messages"][1]["text"].startswith("Записала вас!\nВаша запись:")
    assert any("Это тестовая запись" in n["text"] for n in data["notes"])
    assert client.get("/api/mobile/try", headers=h).json()["messages"] == data["messages"]
    with db.new_session() as s:
        conv = s.exec(select(Conversation).where(Conversation.chat_id == try_chat.CHAT_ID)).one()
        assert conv.channel == "console" and stats.is_test(conv)  # counted nowhere
        assert s.get(Slot, slot.id).status == "booked"
    # the app's own summary of what the AI did does not count it
    assert client.get("/api/mobile/ai-results", headers=h).json()["figures"]["conversations"] == 0
    # the launch list's «Проверьте ИИ» step is done
    steps = client.get("/api/mobile/setup", headers=h).json()["steps"]
    assert next(x for x in steps if x["key"] == "try")["done"] is True

    r = client.post("/api/mobile/try/reset", headers=h)
    assert r.json() == {"cancelled": 1, "messages": []}
    assert client.get("/api/mobile/try", headers=h).json() == {"messages": []}
    with db.new_session() as s:
        assert s.exec(select(Booking)).one().status == "cancelled" and s.get(Slot, slot.id).status == "free"


def test_an_empty_message_and_the_daily_limit(client, business, monkeypatch):
    h = auth(sign_in(client).json()["token"])
    assert client.post("/api/mobile/try", headers=h, json={"text": "  "}).status_code == 422
    monkeypatch.setattr(try_chat, "DAILY_LIMIT", 1)
    assert client.post("/api/mobile/try", headers=h, json={"text": "Привет"}).json()["notes"] == []
    second = client.post("/api/mobile/try", headers=h, json={"text": "Ещё раз"}).json()
    assert second["notes"][0]["ok"] is False and "не больше 1 сообщений" in second["notes"][0]["text"]
    assert len(second["messages"]) == 2  # the second one did not reach the AI


def test_only_the_owner_uses_the_test_chat(client, business):
    with db.new_session() as s:
        s.add(PanelUser(business_id=business.id, login="admin1", name="Админ", password_hash=hash_password("staff-pass-1")))
        s.commit()
    h = auth(sign_in(client, user="admin1", password="staff-pass-1").json()["token"])
    assert client.get("/api/mobile/try", headers=h).status_code == 403
    assert client.post("/api/mobile/try", headers=h, json={"text": "Привет"}).status_code == 403
    assert client.post("/api/mobile/try/reset", headers=h).status_code == 403
    assert client.get("/api/mobile/try").status_code == 401
