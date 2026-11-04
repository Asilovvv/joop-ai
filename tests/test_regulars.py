"""A returning customer: the AI knows the last visits and the upcoming one (joop/regulars.py)."""

from datetime import datetime, timedelta

from sqlmodel import select

from joop import db, regulars
from joop.agent.engine import handle_incoming
from joop.agent.llm import AgentReply
from joop.channels.base import IncomingMessage
from joop.models import Booking, Business, Conversation

from .conftest import NOW_UTC, FakeLLM


def _say(business_id, rt, text, chat="1001", llm=None):
    with db.new_session() as s:
        out = handle_incoming(s, s.get(Business, business_id), IncomingMessage("telegram", chat, "text", text, "Айбек", f"tg:{chat}:{text[:12]}"),
                              (lambda: llm) if llm else rt.get_llm, NOW_UTC)
        s.commit()
        return out


def _past(business_id, phone, days_ago, service, staff, chat_conv_id=None):
    with db.new_session() as s:
        s.add(Booking(business_id=business_id, conversation_id=chat_conv_id, customer_name="Айбек", customer_phone=phone,
                      service=service, staff_name=staff, start=datetime(2026, 11, 4, 12, 0) - timedelta(days=days_ago),
                      channel="telegram", source="ai", created_at=NOW_UTC - timedelta(days=days_ago + 1)))
        s.commit()


def test_prompt_names_the_last_visits_of_a_known_phone(business, rt):
    _past(business.id, "+996555123456", 40, "Маникюр", "Айгерим Садыкова")
    _past(business.id, "+996555123456", 20, "Маникюр", "Айгерим Садыкова")
    _past(business.id, "+996555123456", 5, "Педикюр", "Элина Ким")
    _past(business.id, "+996555000999", 3, "Стрижка", "Нурлан")  # somebody else
    llm = FakeLLM([AgentReply("Чем помочь?"), AgentReply("Записать как в прошлый раз?")])
    _say(business.id, rt, "Привет", llm=llm)
    assert "Постоянный клиент" not in llm.calls[0]["system"]  # the phone is not known yet in this chat
    with db.new_session() as s:
        conv = s.exec(select(Conversation)).one()
        conv.customer_phone = "0555 123 456"
        s.add(conv)
        s.commit()
    _say(business.id, rt, "Хочу записаться", llm=llm)
    system = llm.calls[1]["system"]
    assert ("Постоянный клиент: 3 визита, последний — Педикюр у Элина Ким 30.10, до этого Маникюр у Айгерим Садыкова (2 раза). "
            "Если не называет услугу или мастера, можно предложить как в прошлый раз, не настаивая.") in system


def test_prompt_mentions_the_upcoming_booking_so_it_is_not_doubled(business, rt):
    with db.new_session() as s:
        conv = Conversation(business_id=business.id, channel="telegram", chat_id="1001", customer_phone="+996555123456")
        s.add(conv)
        s.flush()
        s.add(Booking(business_id=business.id, conversation_id=conv.id, customer_name="Айбек", customer_phone="+996555123456",
                      service="Чистка", staff_name="Айгерим Садыкова", start=datetime(2026, 11, 6, 15, 0), channel="telegram", source="ai"))
        s.commit()
    llm = FakeLLM([AgentReply("Вы записаны на пятницу.")])
    _say(business.id, rt, "Когда я записан?", llm=llm)
    assert "Уже записан(а): Пт 06.11 15:00 — Чистка у Айгерим Садыкова. Второй раз не записывай, если не просит ещё одну запись." in llm.calls[0]["system"]
    with db.new_session() as s:
        assert regulars.prompt_hint(s, s.get(Business, business.id), Conversation(business_id=business.id, channel="telegram", chat_id="x"),
                                    datetime(2026, 11, 4, 12, 0)) == ""
