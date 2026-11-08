"""The owner or staff writing to their own bot is a test: answered like a customer, counted nowhere (joop/stats.py)."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlmodel import select

from joop import db, pilot
from joop.agent.llm import AgentReply
from joop.models import Booking, Business, Conversation, Lead
from joop.stats import activity
from joop.web.app import create_app
from joop.web.saas import checklist

from .conftest import NOW_UTC, FakeLLM, first_free_slot
from .test_engine import run, tg
from .test_web import login

SINCE = NOW_UTC - timedelta(days=1)


def numbers(business_id):
    with db.new_session() as s:
        return activity(s, business_id, SINCE)


def conv_of(business_id, chat):
    with db.new_session() as s:
        return s.exec(select(Conversation).where(Conversation.business_id == business_id, Conversation.chat_id == chat)).one()


def test_the_alerts_chat_gets_answers_but_is_not_a_customer(business):
    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.admin_chat_ids = "777"
        s.add(b)
        s.commit()
    slot = first_free_slot(business.id)
    llm = FakeLLM([
        AgentReply("Чистка — 2 500 сом. Записать?"),
        AgentReply("Записала вас.", booking={"slot_id": slot.id, "name": "Айбек", "phone": "0555 123 456", "service": "чистка"}),
        AgentReply("Передам администратору.", handoff="Спрашивает про рассрочку"),
        AgentReply("Записала вас.", booking={"slot_id": None, "name": "Нурлан", "phone": "0555 222 333", "service": "чистка",
                                             "preferred_time": "в пятницу"}),
    ])
    assert run(business, tg("Сколько стоит чистка?", chat="777", ext="o1"), llm).reply.startswith("Чистка")
    booked = run(business, tg("Айбек 0555 123 456", chat="777", ext="o2"), llm)
    assert booked.booking_id is not None  # the owner sees the whole flow work in the real bot
    run(business, tg("А рассрочка есть?", chat="777", ext="o3"), llm)
    assert conv_of(business.id, "777").staff_test

    n = numbers(business.id)
    assert n["customer_messages"] == n["conversations"] == n["bookings"] == n["leads"] == n["ai_replies"] == 0

    run(business, tg("Запишите на чистку в пятницу", chat="1001", ext="c1"), llm)  # a real customer still counts
    n = numbers(business.id)
    assert n["customer_messages"] == 1 and n["conversations"] == 1 and not conv_of(business.id, "1001").staff_test
    with db.new_session() as s:
        b = s.get(Business, business.id)
        assert next(i for i in checklist(s, b, NOW_UTC) if i["key"] == "real")["done"]
        rows, total = pilot.report(s, SINCE, NOW_UTC + timedelta(minutes=1), NOW_UTC)  # the thesis's pilot table
        assert (total.conversations, total.customer_messages, total.bookings, total.handoffs) == (1, 1, 0, 0)
        assert s.exec(select(Booking).where(Booking.business_id == b.id)).all()  # test bookings stay visible in the panel
        assert s.exec(select(Lead).where(Lead.business_id == b.id, Lead.kind == "handoff")).all()


def test_the_panel_link_marks_a_test_chat_and_linking_alerts_marks_earlier_tries(business):
    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.test_link_code = "Ab3-x_9Qz"
        s.add(b)
        s.commit()
    llm = FakeLLM([AgentReply("Чистка — 2 500 сом.")] * 3)
    greeting = run(business, tg("/start test_Ab3-x_9Qz", kind="command", chat="555", ext="s1"), llm)
    assert greeting.reply  # the usual greeting
    run(business, tg("Сколько стоит чистка?", chat="555", ext="s2"), llm)
    assert conv_of(business.id, "555").staff_test
    with db.new_session() as s:
        b = s.get(Business, business.id)
        assert not next(i for i in checklist(s, b, NOW_UTC) if i["key"] == "real")["done"]
        assert next(i for i in checklist(s, b, NOW_UTC) if i["key"] == "try")["done"]  # trying the real bot is a try

    for chat, payload in (("401", "/start test"), ("402", "/start test_wrong"), ("403", "/start test_")):
        run(business, tg(payload, kind="command", chat=chat, ext=f"x{chat}"), llm)
        assert not conv_of(business.id, chat).staff_test  # the link's code is secret: a customer cannot mark their own chat
    run(business, tg("Сколько стоит чистка?", chat="888", ext="e1"), llm)  # the owner tries the bot first...
    assert numbers(business.id)["conversations"] == 4  # the three wrong links and this one
    with db.new_session() as s:
        code = s.get(Business, business.id).admin_link_code
    run(business, tg(f"/start admin_{code}", kind="command", chat="888", ext="e2"), llm)  # ...then links the alerts
    assert conv_of(business.id, "888").staff_test and numbers(business.id)["conversations"] == 3
    assert run(business, tg("/start", kind="command", chat="999", ext="p1"), llm).reply
    assert not conv_of(business.id, "999").staff_test  # a plain /start is a customer


def test_channels_page_offers_to_write_to_the_bot(business, rt, settings):
    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.telegram_bot_username = "aktish_bot"
        s.add(b)
        s.commit()
    with TestClient(create_app(settings, rt, init=False)) as c:
        login(c)
        page = c.get("/panel/channels").text
        with db.new_session() as s:
            code = s.get(Business, business.id).test_link_code
        assert len(code) >= 12 and "@aktish_bot" in page and f'href="https://t.me/aktish_bot?start=test_{code}"' in page
        c.get("/panel/channels")
        with db.new_session() as s:
            assert s.get(Business, business.id).test_link_code == code  # made once


def test_web_chat_from_a_browser_logged_in_to_the_panel_is_a_test(business, rt, llm, settings):
    from joop.web import webchat

    webchat.reset_limits()
    llm.replies = [AgentReply("Чистка — 2 500 сом.")] * 2
    with TestClient(create_app(settings, rt, init=False)) as visitor:
        page = visitor.get("/c/aktish")
        assert "этот чат — тест" not in page.text and "set-cookie" not in page.headers
        v = visitor.post("/c/aktish/chat", json={"text": "Сколько стоит чистка?"}).json()["visitor"]
        assert "set-cookie" not in visitor.get("/c/aktish").headers
    with TestClient(create_app(settings, rt, init=False)) as owner:
        login(owner)
        assert "этот чат — тест" in owner.get("/c/aktish").text
        o = owner.post("/c/aktish/chat", json={"text": "Сколько стоит чистка?"}).json()["visitor"]
    webchat.reset_limits()
    assert not conv_of(business.id, f"web-{v}").staff_test and conv_of(business.id, f"web-{o}").staff_test
    n = numbers(business.id)
    assert n["conversations"] == 1 and n["customer_messages"] == 1  # only the visitor


def test_a_test_chat_stays_out_of_altegio_broadcasts_and_week_one_but_its_slot_rules_still_apply(business, rt):
    """Review of #138: tests must not reach the salon's Altegio journal, broadcasts or the week-one numbers; but a
    test booking holds a real slot, so a prepayment deadline still releases it."""
    from joop import broadcasts, deposits, trust
    from joop.agent.engine import handle_incoming
    from joop.channels.base import IncomingMessage

    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.admin_chat_ids, b.altegio_location_id = "777", 55
        b.deposit_amount, b.deposit_details, b.deposit_hours, b.deposit_auto_cancel = 500, "MBank 0555 000 111", 2, True
        s.add(b)
        s.commit()
    slot = first_free_slot(business.id)
    llm = FakeLLM([AgentReply("Записала!", booking={"slot_id": slot.id, "name": "Айбек", "phone": "0555 123 456",
                                                     "service": "консультация"})])
    asked = []
    with db.new_session() as s:
        out = handle_incoming(s, s.get(Business, business.id), IncomingMessage("telegram", "777", "text", "Запишите, Айбек, 0555 123 456", "Я", "a1"),
                              lambda: llm, NOW_UTC, get_altegio=lambda biz: asked.append(biz) or None)
        s.commit()
    assert out.booking_id and asked == []  # no Altegio client was even asked for
    with db.new_session() as s:
        b = s.get(Business, business.id)
        booking = s.get(Booking, out.booking_id)
        assert booking.deposit_status == "awaiting"
        assert deposits.check_deadlines(s, rt, b, booking.deposit_deadline + timedelta(minutes=1))["released"] == 1
        s.commit()
        assert trust.first_live_at(s, b) is None
        assert broadcasts._group(s, b, "all", "", NOW_UTC) == []


def test_staff_can_say_a_test_chat_is_a_real_customer(business, rt, settings):
    from .test_web import csrf_of

    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.test_link_code = "Ab3-x_9Qz"
        s.add(b)
        s.commit()
    run(business, tg("/start test_Ab3-x_9Qz", kind="command", chat="321", ext="r1"), FakeLLM())
    run(business, tg("Сколько стоит чистка?", chat="321", ext="r2"), FakeLLM())
    conv = conv_of(business.id, "321")
    assert conv.staff_test and numbers(business.id)["conversations"] == 0
    with TestClient(create_app(settings, rt, init=False)) as c:
        login(c)
        page = c.get(f"/panel/conversations/{conv.id}").text
        assert "считать клиентом" in page
        c.post(f"/panel/conversations/{conv.id}/real", data={"csrf": csrf_of(page)})
    assert not conv_of(business.id, "321").staff_test and numbers(business.id)["conversations"] == 1
