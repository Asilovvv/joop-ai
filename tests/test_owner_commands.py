"""The owner's numbers by a command in the staff Telegram chat (joop/owner_commands.py)."""

from datetime import datetime, timedelta

from sqlmodel import select

from joop import db
from joop.agent.engine import handle_incoming
from joop.agent.llm import AgentReply
from joop.channels.base import IncomingMessage
from joop.models import Booking, Business, Conversation, Message

from .conftest import NOW_UTC, FakeLLM, first_free_slot


_n = [0]


def _cmd(business_id, rt, text, chat="999", kind="command", llm=None):
    _n[0] += 1
    with db.new_session() as s:
        out = handle_incoming(s, s.get(Business, business_id), IncomingMessage("telegram", chat, kind, text, "Бектур", f"tg:{chat}:{_n[0]}"),
                              (lambda: llm) if llm else rt.get_llm, NOW_UTC)
        s.commit()
        return out


def _link(business_id):
    with db.new_session() as s:
        b = s.get(Business, business_id)
        b.admin_chat_ids = "999"
        s.add(b)
        s.commit()


def test_today_week_and_gaps_answer_only_in_the_staff_chat(business, rt):
    llm = FakeLLM([AgentReply("Это чат для клиентов.")])
    assert _cmd(business.id, rt, "/today", llm=llm).reply == "Это чат для клиентов."  # not linked yet: a customer
    _link(business.id)
    slot = first_free_slot(business.id)
    with db.new_session() as s:
        s.add(Booking(business_id=business.id, customer_name="Айбек", customer_phone="+996555123456", service="Чистка",
                      staff_name="Айгерим Садыкова", start=datetime(2026, 11, 4, 23, 30), channel="telegram", source="ai",
                      reminder_status="sent"))  # today 23:30 Bishkek, reminded, unconfirmed
        s.commit()
    out = _cmd(business.id, rt, "/today", llm=llm)
    assert out.reply.startswith("Сводка «Ак-Тиш Дент» на 04.11") and "Не подтвердили запись: 1 — 23:30 Айбек" in out.reply
    assert "Свободных окон: сегодня" in out.reply
    with db.new_session() as s:  # the command left no messages: only the first exchange, before the chat was linked
        conv = s.exec(select(Conversation).where(Conversation.chat_id == "999")).one()
        assert len(s.exec(select(Message).where(Message.conversation_id == conv.id)).all()) == 2
    out = _cmd(business.id, rt, "/week", llm=llm)
    assert out.reply.startswith("За 7 дней «Ак-Тиш Дент»: ")
    out = _cmd(business.id, rt, "/gaps", llm=llm)
    assert out.reply.startswith("Свободных окон на 7 дней: ") and f"{slot.start:%d.%m}" in out.reply
    assert "/today" in _cmd(business.id, rt, "/help", llm=llm).reply
    assert _cmd(business.id, rt, "/admin wrong", llm=llm).reply.startswith("Код не подошёл")  # the old commands still work
