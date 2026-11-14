"""Optics (joop/niches/optics): eye exams on free windows, glasses in work with their own page words."""

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from joop import db, jobs
from joop.agent.engine import handle_incoming
from joop.agent.llm import AgentReply
from joop.channels.base import IncomingMessage
from joop.models import Booking, Business, Job, Slot, Staff
from joop.niches import _job_words, get_pack
from joop.presets import create_business
from joop.web.app import create_app

from .conftest import NOW_UTC, FakeLLM
from .test_web import csrf_of


def optics(slug="koz"):
    with db.new_session() as s:
        b = create_business(s, slug=slug, name="Көз", password="koz-pass-123", niche="optics", demo=True, now_utc=NOW_UTC)
        b.example_ok = True  # its price list, optometrist and orders are its own
        b.telegram_bot_token = "123:TEST"
        s.commit()
        return b


def test_exam_booking_and_safety_rules(engine):
    pack = get_pack("optics")
    assert pack.has("booking") and pack.offers("jobs") and not pack.jobs_delivered
    b = optics()
    with db.new_session() as s:
        slot = s.exec(select(Slot).join(Staff).where(Staff.business_id == b.id, Staff.name == "Айнура").order_by(Slot.start)).first()
    llm = FakeLLM([AgentReply("Записала.", booking={"slot_id": slot.id, "name": "Айжан", "phone": "0555909090",
                                                    "service": "проверка зрения, очки для дали", "preferred_time": "", "party_size": 0})])
    with db.new_session() as s:
        out = handle_incoming(s, s.get(Business, b.id), IncomingMessage("telegram", "o1", "text", "Проверка зрения, Айжан 0555 909 090", "", "o1"),
                              lambda: llm, NOW_UTC)
        s.commit()
        assert s.get(Booking, out.booking_id).staff_name == "Айнура"
    system = llm.calls[0]["system"]
    assert "не советуй диоптрии" in system and "вызвать скорую по номеру 103" in system


def test_glasses_ready_notice_and_page_words(settings, rt, engine):
    b = optics()
    with db.new_session() as s:
        job = s.exec(select(Job).where(Job.business_id == b.id, Job.number == "3106")).one()
        text = jobs.ready_text(s.get(Business, b.id), job, False)
    assert text.startswith("Ваш заказ №3106 готов") and "Можно забирать" in text
    with TestClient(create_app(settings, rt, init=False)) as c:
        token = csrf_of(c.get("/login").text)
        c.post("/login", data={"slug": "koz", "password": "koz-pass-123", "csrf": token})
        page = c.get("/panel/jobs").text
    assert "Принимаете заказ на очки или линзы — запишите здесь." in page
    assert 'placeholder="Очки для дали: оправа, линзы 1.6 с антибликом"' in page and "Пальто, химчистка" not in page


def test_repair_and_furniture_keep_their_words_and_unknown_keys_fail():
    assert get_pack("repair").job_words["item_placeholder"] == "Пальто, химчистка"
    assert get_pack("furniture").job_words["intro"] == "Изготавливаете на заказ — запишите заказ здесь."
    with pytest.raises(ValueError, match="unknown job_words"):
        _job_words("x", {"intro": "a", "button": "b"})
