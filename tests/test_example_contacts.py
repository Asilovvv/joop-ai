"""The sign-up example's description, address and phone are fictional: no real customer reads them (joop/samples.py)."""

from datetime import timedelta

from fastapi.testclient import TestClient

from joop import db, quick_replies, samples
from joop.agent.llm import AgentReply
from joop.models import Booking, Business
from joop.presets import create_business
from joop.scheduler import reminder_text
from joop.web.app import create_app

from .conftest import NOW_UTC, FakeLLM

DEMO_ADDRESS = "Бишкек, проспект Чуй 150 (демо-адрес)"


def fresh(**changes) -> int:
    with db.new_session() as s:
        b = create_business(s, slug="fresh", name="Свежая", password="fresh-pass", niche="restaurant", demo=True, now_utc=NOW_UTC)
        for k, v in changes.items():
            setattr(b, k, v)
        s.commit()
        return b.id


def test_a_fresh_sign_up_tells_real_customers_no_fictional_address_or_phone(settings, rt, engine):
    fresh()
    llm = FakeLLM([AgentReply("Здравствуйте"), AgentReply("Здравствуйте")])
    rt._llm = llm
    with TestClient(create_app(settings, rt, init=False)) as c:
        place = c.get("/api/mobile/places/fresh").json()
        c.post("/c/fresh/chat", json={"text": "Где вы находитесь?", "visitor": ""})
    assert (place["address"], place["phone"], place["description"]) == ("", "", "")
    system = llm.calls[0]["system"]
    assert "демо-адрес" not in system and "555 000 002" not in system and "(демо)" not in system
    assert "- Адрес: уточняет администратор" in system and "- Телефон: уточняет администратор" in system


def test_the_test_chat_keeps_the_example_and_the_owner_s_own_contacts_are_shown(settings, rt, engine):
    business_id = fresh()
    with db.new_session() as s:
        b = s.get(Business, business_id)
        assert samples.example_contacts(b) == {"description", "address", "phone"}
        assert not samples.hidden_from_customers(s, b, "console").contacts  # the owner tries the example there
        b.address = "Бишкек, Киевская 10"  # the owner wrote the real address; the phone is still the example's
        assert samples.example_contacts(b) == {"description", "phone"}
        assert samples.customer_contact(b, "address") == "Бишкек, Киевская 10"
        b.example_ok = True  # «this is my real data»
        assert samples.example_contacts(b) == frozenset()


def test_reminders_and_ready_answers_leave_out_the_example_address(engine):
    business_id = fresh()
    with db.new_session() as s:
        b = s.get(Business, business_id)
        booking = Booking(business_id=b.id, start=NOW_UTC + timedelta(days=1), service="Стол")
        assert DEMO_ADDRESS not in reminder_text(b, booking) and "Дарек" not in reminder_text(b, booking, kyrgyz=True)
        filled = quick_replies.fill("Мы по адресу: {адрес}. Тел.: {телефон}", b)
        assert "демо-адрес" not in filled and "555 000" not in filled
        b.address = "Бишкек, Киевская 10"
        assert "Адрес: Бишкек, Киевская 10" in reminder_text(b, booking)
