from datetime import timedelta

from sqlmodel import select

from joop import db
from joop.agent.engine import ASK_CONTACTS_REPLY, ERROR_REPLY, TEXT_ONLY_REPLY, handle_incoming
from joop.agent.llm import AgentReply, LLMError
from joop.agent.prompt import build_history
from joop.channels.base import IncomingMessage
from joop.dispatch import process_incoming
from joop.models import Booking, Business, Conversation, Lead, Message, Slot

from .conftest import NOW_UTC, FakeLLM, first_free_slot


def tg(text, kind="text", chat="1001", ext=None, name="Айбек"):
    return IncomingMessage("telegram", chat, kind, text, name, ext or f"tg:{chat}:{text[:10]}")


def run(business, incoming, llm, now=NOW_UTC):
    with db.new_session() as s:
        b = s.get(Business, business.id)
        outcome = handle_incoming(s, b, incoming, lambda: llm, now)
        s.commit()
        return outcome


def test_prompt_has_prices_slots_and_closed_status(business):
    llm = FakeLLM([AgentReply("Здравствуйте!")])
    run(business, tg("Сколько стоит чистка?"), llm)
    system = llm.calls[0]["system"]
    assert "Профессиональная чистка — 3 000 (ультразвук и Air Flow)" in system
    assert "Сейчас нерабочее время" in system
    slot = first_free_slot(business.id)
    assert f"- {slot.id}: Чт 05.11 09:00 — Айгерим Садыкова (терапевт)" in system
    assert "(103)" in system
    assert llm.calls[0]["messages"] == [{"role": "user", "content": "Сколько стоит чистка?"}]


def test_booking_flow(business):
    slot = first_free_slot(business.id)
    llm = FakeLLM([
        AgentReply("Есть завтра в 09:00 у терапевта. Записать?"),
        AgentReply(
            "Записала вас на четверг 05.11 в 09:00 к Айгерим Садыковой.",
            booking={"slot_id": slot.id, "name": "Айбек", "phone": "0555 123 456", "service": "лечение кариеса"},
        ),
    ])
    run(business, tg("Болит зуб, можно завтра?", ext="tg:1001:1"), llm)
    outcome = run(business, tg("Да, Айбек 0555 123 456", ext="tg:1001:2"), llm)

    assert outcome.reply.startswith("Записала вас")
    assert outcome.booking_id is not None
    assert "Новая запись через ИИ (в нерабочее время)" in outcome.admin_notes[0]
    assert "+996555123456" in outcome.admin_notes[0]
    # second call saw the whole conversation, alternating roles
    roles = [m["role"] for m in llm.calls[1]["messages"]]
    assert roles == ["user", "assistant", "user"]
    with db.new_session() as s:
        assert s.get(Slot, slot.id).status == "booked"
        booking = s.get(Booking, outcome.booking_id)
        assert booking.customer_phone == "+996555123456" and booking.created_off_hours
        conv = s.exec(select(Conversation)).one()
        assert conv.customer_name == "Айбек"
        assert [m.role for m in s.exec(select(Message).order_by(Message.id)).all()] == ["customer", "ai", "customer", "ai"]


def test_booking_taken_slot_offers_alternatives(business):
    slot = first_free_slot(business.id)
    with db.new_session() as s:
        s.get(Slot, slot.id).status = "booked"
        s.commit()
    llm = FakeLLM([AgentReply("Записала!", booking={"slot_id": slot.id, "name": "Айбек", "phone": "0555123456", "service": "осмотр"})])
    outcome = run(business, tg("Запишите на 9:00"), llm)
    assert outcome.booking_id is None
    assert outcome.reply.startswith("Извините, это время уже занято. Свободно:")
    assert "Айгерим Садыкова" in outcome.reply
    with db.new_session() as s:
        assert s.exec(select(Booking)).all() == []


def test_booking_unknown_slot_and_bad_phone(business):
    llm = FakeLLM([
        AgentReply("Записала!", booking={"slot_id": 99999, "name": "Айбек", "phone": "0555123456", "service": "осмотр"}),
        AgentReply("Записала!", booking={"slot_id": first_free_slot(business.id).id, "name": "Айбек", "phone": "123", "service": "осмотр"}),
    ])
    assert "уже занято" in run(business, tg("a", ext="e1"), llm).reply
    assert run(business, tg("b", ext="e2"), llm).reply == ASK_CONTACTS_REPLY


def test_handoff_creates_lead(business):
    llm = FakeLLM([AgentReply("Передам администратору, он перезвонит.", handoff="Хочет перенести запись на субботу")])
    outcome = run(business, tg("Хочу перенести запись"), llm)
    assert outcome.lead_id is not None
    assert "Хочет перенести запись на субботу" in outcome.admin_notes[0]
    with db.new_session() as s:
        lead = s.get(Lead, outcome.lead_id)
        assert lead.kind == "handoff" and lead.off_hours and lead.customer_name == "Айбек"


def test_media_message_gets_fixed_reply_without_model(business):
    llm = FakeLLM()
    outcome = run(business, IncomingMessage("whatsapp", "996555000111", "media", "", "", "wa:1", "голосовое сообщение"), llm)
    assert outcome.reply == TEXT_ONLY_REPLY
    assert llm.calls == []
    assert "голосовое сообщение" in outcome.admin_notes[0]


def test_duplicates_paused_and_disabled(business):
    llm = FakeLLM([AgentReply("Ответ 1"), AgentReply("Ответ 2")])
    assert run(business, tg("Привет", ext="dup"), llm).reply == "Ответ 1"
    assert run(business, tg("Привет", ext="dup"), llm).skipped == "duplicate"

    with db.new_session() as s:
        conv = s.exec(select(Conversation)).one()
        conv.ai_paused_until = NOW_UTC + timedelta(hours=1)
        s.commit()
    assert run(business, tg("Есть кто?", ext="p1"), llm).skipped == "paused"

    with db.new_session() as s:
        conv = s.exec(select(Conversation)).one()
        conv.ai_paused_until = None
        s.get(Business, business.id).bot_enabled = False
        s.commit()
    assert run(business, tg("Алло", ext="p2"), llm).skipped == "bot_disabled"
    assert len(llm.calls) == 1


def test_echo_from_staff_pauses_ai_but_own_echo_does_not(business):
    llm = FakeLLM([AgentReply("Свободно завтра в 10:00.")])
    run(business, IncomingMessage("instagram", "igsid-1", "text", "Здравствуйте", "", "ig:m1"), llm)
    own = run(business, IncomingMessage("instagram", "igsid-1", "echo", "Свободно  завтра в 10:00.", "", "ig:m2"), llm)
    assert own.skipped == "own_echo"
    staff = run(business, IncomingMessage("instagram", "igsid-1", "echo", "Я вам перезвоню, Айгерим", "", "ig:m3"), llm)
    assert staff.skipped == "staff_reply"
    after = run(business, IncomingMessage("instagram", "igsid-1", "text", "Хорошо", "", "ig:m4"), llm)
    assert after.skipped == "paused"
    with db.new_session() as s:
        conv = s.exec(select(Conversation)).one()
        assert conv.ai_paused_until == NOW_UTC + timedelta(hours=12)


def test_commands(business):
    llm = FakeLLM()
    start = run(business, tg("/start", kind="command", ext="c1"), llm)
    assert "Ак-Тиш Дент" in start.reply
    wrong = run(business, tg("/admin 00000000", kind="command", chat="-5001", ext="c2"), llm)
    assert wrong.reply.startswith("Код не подошёл")
    ok = run(business, tg(f"/admin@joop_bot {business.admin_link_code}", kind="command", chat="-5001", ext="c3"), llm)
    assert ok.reply.startswith("Готово")
    with db.new_session() as s:
        assert s.get(Business, business.id).admin_chat_ids == "-5001"
    assert llm.calls == []


def test_model_failure_falls_back(business):
    llm = FakeLLM([LLMError("boom")])
    outcome = run(business, tg("Здравствуйте"), llm)
    assert outcome.reply == ERROR_REPLY
    with db.new_session() as s:
        assert s.get(Lead, outcome.lead_id).kind == "error"


def test_build_history_merges_and_trims():
    def m(role, text):
        return Message(business_id=1, conversation_id=1, role=role, text=text)

    turns = build_history([m("ai", "hi"), m("customer", "a"), m("customer", "b"), m("staff", "c"), m("customer", "d"), m("ai", "e")])
    assert turns == [
        {"role": "user", "content": "a\nb"},
        {"role": "assistant", "content": "(ответ живого администратора) c"},
        {"role": "user", "content": "d"},
    ]


def test_dispatch_delivers_reply_and_admin_notes(business, rt):
    with db.new_session() as s:
        s.get(Business, business.id).admin_chat_ids = "-5001,777"
        s.commit()
    slot = first_free_slot(business.id)
    rt._llm = FakeLLM([AgentReply("Записала!", booking={"slot_id": slot.id, "name": "Айбек", "phone": "0555123456", "service": "осмотр"})])
    outcome = process_incoming(rt, business.id, tg("Айбек 0555123456, на 9:00"), NOW_UTC)
    assert outcome.booking_id
    assert rt.tg.sent[0] == ("1001", "Записала!")
    assert {chat for chat, _ in rt.tg.sent[1:]} == {"-5001", "777"}


def test_booking_needs_a_name_the_customer_gave(business):
    """Eval run 25: "Запишите на стрижку, 0555 123 456, завтра в 11" was booked under an invented name."""
    from joop.agent.engine import ASK_CONTACTS_REPLY, _fold

    slot = first_free_slot(business.id)
    llm = FakeLLM([
        AgentReply("Вы записаны.", booking={"slot_id": slot.id, "name": "Клиент", "phone": "0555123456", "service": "чистка"}),
        AgentReply("Вы записаны.", booking={"slot_id": slot.id, "name": "Айгерим", "phone": "0555123456", "service": "чистка"}),
    ])
    with db.new_session() as s:
        b = s.get(Business, business.id)
        out = handle_incoming(s, b, IncomingMessage("telegram", "n1", "text", "Запишите, 0555 123 456", "", "n1"), lambda: llm, NOW_UTC)
        s.commit()
        assert out.booking_id is None and out.reply == ASK_CONTACTS_REPLY
        out = handle_incoming(s, b, IncomingMessage("telegram", "n1", "text", "Aigerim", "", "n2"), lambda: llm, NOW_UTC)
        s.commit()
        assert out.booking_id  # Latin spelling of the same name counts
    assert _fold("Жаңыл") == _fold("Zhanyl")


def test_outage_sends_one_note_then_summaries(business):
    notes = []
    for i in range(10):
        llm = FakeLLM([LLMError("boom")])
        outcome = run(business, tg("Здравствуйте", chat=str(7000 + i), ext=f"o{i}"), llm)
        assert outcome.reply == ERROR_REPLY and outcome.lead_id
        notes.append(outcome.admin_notes)
    assert "Заявка администратору" in notes[0][0] and "отдельных уведомлений не будет" in notes[0][0]
    assert all(n == [] for n in notes[1:9])
    assert "без ответа остались 10 сообщений" in notes[9][0]
    with db.new_session() as s:
        assert len(s.exec(select(Lead).where(Lead.business_id == business.id, Lead.kind == "error")).all()) == 10
