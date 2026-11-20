"""Fixes from the independent review of #260-#265 (20.11.2026)."""

import logging
import threading
import time

from sqlmodel import select

from joop import db
from joop.agent import engine
from joop.agent.llm import AgentReply
from joop.channels.base import IncomingMessage
from joop.dispatch import process_incoming
from joop.models import Business, Message

from .conftest import NOW_UTC, FakeLLM
from .test_saas import app_client, owner_login, saas_settings  # noqa: F401  (fixtures)
from .test_voice import tg_voice, wire

# --- #260: the chat's turn ---------------------------------------------------------------------------------------


def test_a_stuck_chat_is_waited_out_once_not_twice(business, rt, monkeypatch, caplog):
    """dispatch took the chat's turn and handle_incoming asked for it again: after a wait that ran out, the second
    request waited the whole CHAT_WAIT once more (300 s for a stuck chat, a server thread held all that time)."""
    monkeypatch.setattr(engine, "CHAT_WAIT", 0.2)
    stuck, release = threading.Event(), threading.Event()

    def holder():
        with engine.chat_turn(business.id, "telegram", "700"):
            stuck.set()
            release.wait(10)

    t = threading.Thread(target=holder)
    t.start()
    assert stuck.wait(5)
    try:
        with caplog.at_level(logging.WARNING, logger="joop.agent.engine"):
            out = process_incoming(rt, business.id, IncomingMessage("telegram", "700", "text", "Здравствуйте", "", "tg:700:1"), NOW_UTC)
    finally:
        release.set()
        t.join()
    assert out.reply  # late and out of order beats never
    assert len([r for r in caplog.records if "goes ahead" in r.getMessage()]) == 1
    assert engine._turns == {}


def test_a_text_sent_right_after_a_voice_message_is_answered_after_it(business, rt):
    """Recognition ran before the chat's turn was taken, so the text overtook the voice message."""
    stt = wire(rt, "Сколько стоит консультация?")
    heard = stt.transcribe

    def slow(audio):
        time.sleep(0.5)
        return heard(audio)

    stt.transcribe = slow
    rt._llm = FakeLLM([AgentReply("Консультация — 500 сом."), AgentReply("Завтра свободно в 10:00.")])
    voice_first = threading.Thread(target=process_incoming, args=(rt, business.id, tg_voice(), NOW_UTC))
    voice_first.start()
    time.sleep(0.15)
    process_incoming(rt, business.id, IncomingMessage("telegram", "42", "text", "А завтра есть время?", "Айбек", "tg:42:9"), NOW_UTC)
    voice_first.join()
    assert [text for chat, text in rt.tg.sent if chat == "42"] == ["Консультация — 500 сом.", "Завтра свободно в 10:00."]
    with db.new_session() as s:
        stored = s.exec(select(Message.text).where(Message.role == "customer").order_by(Message.id)).all()
    assert stored == ["[голосовое] Сколько стоит консультация?", "А завтра есть время?"]


def test_notes_to_staff_go_out_after_the_customers_turn(business, rt):
    """The turn was held through every send: the reply, each note to staff, each offer to the waiting list. A slow
    alerts chat kept the customer's next message waiting."""
    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.admin_chat_ids = "-5001"
        s.add(b)
        s.commit()
    held: dict[str, bool] = {}
    plain = rt.tg.send_text

    def watching(chat_id, text):
        held[str(chat_id)] = (business.id, "telegram", "701") in engine._turns
        return plain(chat_id, text)

    rt.tg.send_text = watching
    rt._llm = FakeLLM([AgentReply("Передала администратору.", handoff="Клиент просит перезвонить")])
    out = process_incoming(rt, business.id, IncomingMessage("telegram", "701", "text", "Позовите человека", "Айбек", "tg:701:1"), NOW_UTC)
    assert out.admin_notes and held == {"701": True, "-5001": False}


# --- #263: what the privacy page says, the code does -------------------------------------------------------------


def test_stop_also_stops_rating_requests_and_invitations_to_come_again(business, rt):
    """«стоп» stopped broadcasts, reorder reminders and stock notices, but a customer who wrote it was still asked to
    rate the visit and invited to come again, and staff were told to call them when the message could not go."""
    from datetime import timedelta

    from joop.models import Booking, Conversation, Service
    from joop.scheduler import run_due_jobs
    from joop.timeutil import utc_to_local

    from .test_followups import DAY_UTC, enable, visit

    with db.new_session() as s:
        svc = s.exec(select(Service).where(Service.business_id == business.id)).first()
        svc.repeat_days = 21
        s.add(svc)
        s.commit()
        name = svc.name
    enable(business.id, review_requests=True, return_invites=True, reminder_hour=15, admin_chat_ids="900")
    local = utc_to_local(DAY_UTC, business.timezone)
    rated, _ = visit(business.id, local - timedelta(hours=3), chat="901")
    quiet_rated, quiet_conv = visit(business.id, local - timedelta(hours=3), chat="902")
    invited, _ = visit(business.id, local - timedelta(days=21), chat="903", service=name, phone="0555 903 903")
    quiet_invited, quiet_conv_2 = visit(business.id, local - timedelta(days=21), chat="904", service=name, phone="0555 904 904")
    blocked, blocked_conv = visit(business.id, local - timedelta(days=21), channel="whatsapp", chat="996555905", service=name,
                                  phone="0555 905 905")
    with db.new_session() as s:
        for conv_id in (quiet_conv, quiet_conv_2):
            conv = s.get(Conversation, conv_id)
            conv.broadcast_opt_out = True  # «стоп» after a broadcast, or «отписаться» at any time
            s.add(conv)
        spammer = s.get(Conversation, blocked_conv)
        spammer.blocked_at = DAY_UTC  # on the staff's block list: unreachable by WhatsApp, and not to be phoned either
        s.add(spammer)
        s.commit()
    with db.new_session() as s:
        report = run_due_jobs(s, rt, s.get(Business, business.id), DAY_UTC)
        s.commit()
        assert report["reviews"] == 1 and report["returns"] == {"sent": 1, "manual": 0}
        assert (s.get(Booking, rated).review_status, s.get(Booking, quiet_rated).review_status) == ("asked", "skipped")
        assert s.get(Booking, invited).return_status == "sent"
        assert s.get(Booking, quiet_invited).return_status == s.get(Booking, blocked).return_status == "off"
    assert sorted(chat for chat, _ in rt.tg.sent) == ["901", "903"]  # nothing to 902, 904, and no «свяжитесь сами» to staff


# --- #261: the provider in use, in the founder's pitch too -------------------------------------------------------


def test_the_pitch_names_the_provider_in_use(settings, engine):
    """A Gemini server still told the founder to check the Anthropic balance when the pitch demo failed."""
    import dataclasses

    from joop import health, pitch
    from joop.models import Prospect
    from joop.runtime import Runtime

    Runtime(dataclasses.replace(settings, llm_provider="openai", llm_api_key="k",
                                llm_base_url="https://generativelanguage.googleapis.com/v1beta/openai"))
    silent = FakeLLM([])
    silent.write = lambda *a: None  # the model did not answer
    with db.new_session() as s:
        prospect = Prospect(name="Кафе", niche="restaurant")
        s.add(prospect)
        s.flush()
        made, problem = pitch.build(s, silent, prospect, "Кофе 150", 14, NOW_UTC)
    assert made is None and problem == "ИИ не смог разобрать текст. Проверьте баланс и ключ Gemini API и попробуйте снова."
    assert health.check_hint(sentence=True) == "Проверьте баланс и ключ Gemini API"


def test_the_pitch_page_without_a_dialogue_names_the_provider_too(engine, app_client):
    from joop import health
    from joop.models import Prospect
    from joop.presets import create_business

    with db.new_session() as s:
        demo = create_business(s, slug="demo-kafe", name="Кафе", password="pass-12345", niche="restaurant", now_utc=NOW_UTC)
        prospect = Prospect(name="Кафе", niche="restaurant", demo_business_id=demo.id)
        s.add(prospect)
        s.commit()
        pid = prospect.id
    owner_login(app_client)
    health.use_provider("Gemini API")
    page = app_client.get(f"/owner/prospects/{pid}/pitch").text
    assert "Диалога ещё нет: ИИ не ответил. Проверьте баланс и ключ Gemini API и нажмите «Сделать демо» снова." in page


def test_the_provider_name_does_not_leak_into_the_next_test():
    from joop import health

    assert health.check_hint() == "проверьте баланс и ключ Anthropic API"  # conftest resets it before every test
