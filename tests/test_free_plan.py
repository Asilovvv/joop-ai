"""The free plan for a solo master: the AI works for free, signs its replies with Joop (joop/free_plan.py)."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlmodel import select

from joop import billing, db, free_plan
from joop.agent.llm import AgentReply
from joop.models import Business, Payment, Staff, Subscription
from joop.web.app import create_app

from joop.agent.engine import handle_incoming
from joop.channels.base import IncomingMessage

from .conftest import NOW_UTC, FakeLLM
from .test_saas import app_client, owner_login, saas_settings  # noqa: F401  (fixtures)
from .test_web import login

BASE = "https://joop.test"


def say(business_id, rt, text, channel="whatsapp", chat="996555000111", llm=None):
    with db.new_session() as s:
        out = handle_incoming(s, s.get(Business, business_id), IncomingMessage(channel, chat, "text", text, "Айбек", f"{channel}:{chat}:{text[:12]}"),
                              (lambda: llm) if llm else rt.get_llm, NOW_UTC, base_url=BASE)
        s.commit()
        return out


def _one_master(business_id: int) -> None:
    with db.new_session() as s:
        rows = s.exec(select(Staff).where(Staff.business_id == business_id).order_by(Staff.id)).all()
        for row in rows[1:]:
            row.active = False
            s.add(row)
        s.commit()


def test_free_plan_is_for_one_master_never_expires_and_ends_with_a_payment(settings, rt, business):
    with db.new_session() as s:
        billing.start_trial(s, s.get(Business, business.id), 14, NOW_UTC)
        s.commit()
    with TestClient(create_app(settings, rt, init=False)) as c:
        token = login(c)
        page = c.get("/panel/billing").text
        assert "Бесплатный тариф" in page and "Перейти на бесплатный" not in page  # three masters: not offered
        _one_master(business.id)
        assert "Перейти на бесплатный" in c.get("/panel/billing").text
        r = c.post("/panel/billing/free", data={"csrf": token})
        assert "Вы на бесплатном тарифе" in r.text and "Отменить подписку" not in r.text
        with db.new_session() as s:
            sub = s.exec(select(Subscription)).one()
            assert sub.plan == "free"
            st = billing.state(sub, NOW_UTC + timedelta(days=400))
            assert st.active and st.code == "free" and st.label == "Бесплатно: один мастер"
        # a second master needs the paid plan
        r = c.post("/panel/staff", data={"csrf": token, "name": "Второй мастер"})
        assert "На бесплатном тарифе один мастер" in r.text
        with db.new_session() as s:
            assert len(free_plan.active_staff(s, business.id)) == 1
        # paying moves the business to the paid plan: no signature any more
        with db.new_session() as s:
            payment = Payment(business_id=business.id, amount_som=3000, method="manual", period_days=30)
            s.add(payment)
            s.flush()
            billing.mark_paid(s, payment, NOW_UTC)
            s.commit()
            sub = s.exec(select(Subscription)).one()
            assert sub.plan == "pro" and billing.state(sub, NOW_UTC).code == "active"


def test_free_plan_signs_the_first_reply_and_bookings(settings, rt, business):
    _one_master(business.id)
    with db.new_session() as s:
        sub = billing.start_trial(s, s.get(Business, business.id), 14, NOW_UTC)
        free_plan.switch(sub)
        s.commit()
    rt._llm = FakeLLM([AgentReply("Здравствуйте! Консультация — 500 сом."), AgentReply("Да, завтра есть 10:00.")])
    first = say(business.id, rt, "Сколько стоит консультация?")
    assert first.reply.endswith("\n\nКонсультация — 500 сом.\n\n— отвечает Joop AI, ИИ-администратор для бизнеса · https://joop.test")
    assert say(business.id, rt, "А завтра можно?").reply == "Да, завтра есть 10:00."  # only the first reply
    rt._llm = FakeLLM([AgentReply("Саламатсызбы! Консультация 500 сом.")])
    ky = say(business.id, rt, "Саламатсызбы, консультация канча турат?", chat="996555000222")
    assert ky.reply.endswith("\n\n— Joop AI жооп берет, бизнес үчүн ИИ-администратор · https://joop.test")
    rt._llm = FakeLLM([AgentReply("Чем помочь?")])
    assert say(business.id, rt, "Привет", channel="web", chat="web-abc").reply == "Чем помочь?"  # the page carries Joop's name


def test_signature_follows_a_booking_on_the_free_plan(settings, rt, business):
    from .conftest import first_free_slot

    _one_master(business.id)
    with db.new_session() as s:
        free_plan.switch(billing.start_trial(s, s.get(Business, business.id), 14, NOW_UTC))
        s.commit()
    slot = first_free_slot(business.id)
    llm = FakeLLM([AgentReply("Чем помочь?"), AgentReply("Есть завтра в 09:00. Записать?"),
                   AgentReply("Записала вас на четверг 05.11 в 09:00.",
                              booking={"slot_id": slot.id, "name": "Айбек", "phone": "0555 123 456", "service": "лечение кариеса"})])
    assert say(business.id, rt, "Привет", "telegram", "1001", llm).reply.endswith(
        "Чем помочь?\n\n— отвечает Joop AI, ИИ-администратор для бизнеса · https://joop.test")
    assert say(business.id, rt, "Болит зуб, можно завтра?", "telegram", "1001", llm).reply == "Есть завтра в 09:00. Записать?"
    out = say(business.id, rt, "Да, Айбек 0555 123 456", "telegram", "1001", llm)
    assert out.booking_id is not None and out.reply.endswith("· https://joop.test") and "— отвечает Joop AI" in out.reply


def test_owner_console_counts_free_businesses(business, app_client):
    _one_master(business.id)
    with db.new_session() as s:
        free_plan.switch(billing.start_trial(s, s.get(Business, business.id), 14, NOW_UTC))
        s.commit()
    owner_login(app_client)
    page = app_client.get("/owner").text
    assert "<b>1</b><span>бесплатно</span>" in page and "Бесплатно: один мастер" in page
