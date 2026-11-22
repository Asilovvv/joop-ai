"""Fixes from the independent review of #276–#284."""

from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
from sqlmodel import select

from joop import db
from joop.agent.llm import AgentReply
from joop.models import Booking, Business, Conversation, Slot, WaitlistEntry
from joop.web.app import create_app

from .test_mobile import TOMORROW, tomorrow_slots
from .test_mobile import auth, client, sign_in  # noqa: F401 - the client fixture

FORM = {"name": "Салон", "niche": "beauty", "phone": "0555 123 456", "password": "aigerim-2026", "contact_name": "Айгерим"}


def test_parallel_sign_ups_from_one_address_stop_at_the_hourly_limit(engine, settings, rt):
    """The check and the reservation are one step: twelve requests at once used to make twelve businesses."""
    with TestClient(create_app(settings, rt, init=False)) as c:
        with ThreadPoolExecutor(12) as pool:
            codes = list(pool.map(lambda i: c.post("/api/mobile/signup", json={**FORM, "name": f"Салон {i}"}).status_code,
                                  range(12)))
    assert sorted(codes) == [200] * 3 + [429] * 9
    with db.new_session() as s:
        assert len(s.exec(select(Business).where(Business.name.startswith("Салон "))).all()) == 3


def test_a_refused_sign_up_does_not_use_up_the_hour(engine, settings, rt):
    with TestClient(create_app(settings, rt, init=False)) as c:
        for _ in range(4):
            assert c.post("/api/mobile/signup", json={**FORM, "password": "1"}).status_code == 422
        assert c.post("/api/mobile/signup", json=FORM).status_code == 200


def test_a_new_test_dialogue_offers_the_freed_time_after_it_is_saved(client, business, rt, llm):
    """«Новый диалог» saves the whole reset first (bookings cancelled, times freed, a fresh chat), then offers the
    freed time to the waiting list. Before, the offer ran in the middle and the messenger's own commit (db.free) split
    the reset in two; the send itself was never under the lock, so this guards the order and that the offer still goes."""
    slot = tomorrow_slots(business.id)[0]
    with db.new_session() as s:
        conv = Conversation(business_id=business.id, channel="telegram", chat_id="w1", customer_name="Айбек")
        s.add(conv)
        s.flush()
        s.add(WaitlistEntry(business_id=business.id, conversation_id=conv.id, customer_name="Айбек", channel="telegram",
                            chat_id="w1", day=TOMORROW.date(), service="чистка"))
        s.commit()
    h = auth(sign_in(client).json()["token"])
    llm.replies.append(AgentReply("Записала вас!", booking={"slot_id": slot.id, "name": "Тест", "phone": "0555 123 456"}))
    assert client.post("/api/mobile/try", headers=h, json={"text": "Запишите на завтра, Тест, 0555 123 456"}).status_code == 200
    assert client.post("/api/mobile/try/reset", headers=h).json()["cancelled"] == 1
    with db.new_session() as s:
        assert s.exec(select(Booking)).one().status == "cancelled" and s.get(Slot, slot.id).status == "free"
        assert s.exec(select(WaitlistEntry).where(WaitlistEntry.chat_id == "w1")).one().status == "notified"
    assert any(chat == "w1" and "освободилось время" in text for chat, text, *_ in rt.tg.sent)
