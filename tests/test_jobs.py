import re

from fastapi.testclient import TestClient
from sqlmodel import select

from joop import db, jobs
from joop.agent.engine import handle_incoming
from joop.channels.base import IncomingMessage
from joop.models import Business, Job
from joop.presets import create_business
from joop.web.app import create_app

from .conftest import NOW_UTC, FakeLLM
from .test_web import csrf_of


def shop():
    with db.new_session() as s:
        b = create_business(s, slug="clean", name="Чисто", password="clean-pass", niche="repair", demo=True, now_utc=NOW_UTC)
        b.telegram_bot_token = "123:TEST"
        s.add(b)
        s.commit()
        return b


def ask(business_id, channel, chat, text, ext):
    llm = FakeLLM()
    with db.new_session() as s:
        handle_incoming(s, s.get(Business, business_id), IncomingMessage(channel, chat, "text", text, "", ext), lambda: llm, NOW_UTC)
        s.commit()
    return llm.calls[-1]["system"]


def test_demo_jobs_and_numbers(engine):
    b = shop()
    with db.new_session() as s:
        assert {j.number for j in s.exec(select(Job).where(Job.business_id == b.id)).all()} == {"1042", "1043"}
        n = jobs.next_number(s, b.id)
        assert len(n) == 5 and n.isdigit() and n not in {"1042", "1043"}


def test_receipt_and_phone_unlock_the_status(engine):
    b = shop()
    system = ask(b.id, "telegram", "t1", "Квитанция 1042, телефон 0555 121 212 — готово?", "j1")
    assert "№1042: Пальто, химчистка — готов, можно забирать, стоимость 600 сом" in system
    # Without the right phone, nothing.
    system = ask(b.id, "telegram", "t2", "Квитанция 1042, телефон 0555 999 888 — готово?", "j2")
    assert "№1042" not in system and "попроси номер квитанции" in system
    system = ask(b.id, "telegram", "t3", "Мой заказ готов?", "j3")
    assert "№1042" not in system


def test_whatsapp_number_is_enough(engine):
    b = shop()
    system = ask(b.id, "whatsapp", "996700343434", "Когда будет готов телефон?", "j4")
    assert "№1043: iPhone 12, замена экрана — в работе, срок готовности" in system and "ждём запчасть" in system


def test_ready_notice_goes_to_the_chat_that_asked(engine, settings, rt):
    b = shop()
    ask(b.id, "telegram", "t9", "Квитанция 1043, мой номер 0700 343 434", "j5")
    with TestClient(create_app(settings, rt, init=False)) as c:
        token = csrf_of(c.get("/login").text)
        c.post("/login", data={"slug": "clean", "password": "clean-pass", "csrf": token})
        token = csrf_of(c.get("/panel/jobs").text)
        with db.new_session() as s:
            job = s.exec(select(Job).where(Job.business_id == b.id, Job.number == "1043")).one()
        r = c.post(f"/panel/jobs/{job.id}", data={"status": "ready", "note": "", "price": "4 500 сом", "csrf": token})
        assert "Клиенту отправлено" in r.text
        assert rt.tg.sent[-1][0] == "t9" and "№1043 готов" in rt.tg.sent[-1][1] and "Московская 150" in rt.tg.sent[-1][1]
        # A job of a customer who never wrote: staff are told to call.
        r = c.post("/panel/jobs", data={"customer_phone": "0555 404 404", "item": "Куртка, химчистка", "csrf": token})
        assert re.search(r"№\d{5} принят", r.text)
        with db.new_session() as s:
            new = s.exec(select(Job).where(Job.business_id == b.id, Job.item == "Куртка, химчистка")).one()
        r = c.post(f"/panel/jobs/{new.id}", data={"status": "ready", "csrf": token})
        assert "позвоните" in r.text


def test_jobs_panel_only_for_packs_with_jobs(engine, settings, rt, business):
    with TestClient(create_app(settings, rt, init=False)) as c:
        token = csrf_of(c.get("/login").text)
        c.post("/login", data={"slug": "aktish", "password": "secret-pass", "csrf": token})
        assert c.get("/panel/jobs").status_code == 404


def test_guessing_many_receipt_numbers_finds_nothing(engine):
    """Security review: one message with many numbers and the victim's phone must not unlock the job."""
    b = shop()
    guesses = " ".join(str(n) for n in range(1030, 1050))
    system = ask(b.id, "telegram", "x1", f"{guesses} телефон 0555 121 212", "g1")
    assert "№1042" not in system


def test_a_second_chat_cannot_take_over_the_ready_notice(engine):
    b = shop()
    ask(b.id, "telegram", "owner-chat", "Квитанция 1043, мой номер 0700 343 434", "o1")
    ask(b.id, "telegram", "other-chat", "Квитанция 1043, номер 0700 343 434", "o2")
    with db.new_session() as s:
        from joop.models import Conversation

        job = s.exec(select(Job).where(Job.business_id == b.id, Job.number == "1043")).one()
        assert s.get(Conversation, job.conversation_id).chat_id == "owner-chat"
