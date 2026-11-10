"""Exam preparation and tutors (joop/niches/examprep): a trial lesson with the exam and grade, no promised scores."""

from sqlmodel import select

from joop import db
from joop.agent.engine import handle_incoming
from joop.agent.llm import AgentReply
from joop.channels.base import IncomingMessage
from joop.models import Booking, Business, Slot, Staff
from joop.niches import get_pack
from joop.presets import create_business

from .conftest import NOW_UTC, FakeLLM


def test_trial_lesson_carries_the_exam_and_grade(engine):
    pack = get_pack("examprep")
    assert "level_test" in pack.features and "memberships" in pack.features
    with db.new_session() as s:
        b = create_business(s, slug="ort", name="ОРТ", password="ort-pass-123", niche="examprep", demo=True, now_utc=NOW_UTC)
        b.example_ok = True  # its courses and groups are its own
        s.commit()
        slot = s.exec(select(Slot).join(Staff).where(Staff.business_id == b.id, Staff.name == "Группа ОРТ (вечер)")
                      .order_by(Slot.start)).first()
    llm = FakeLLM([AgentReply("Записала на пробный урок.", booking={
        "slot_id": slot.id, "name": "Айгерим", "phone": "0555525626", "service": "пробный урок, ОРТ, 10 класс",
        "preferred_time": "", "party_size": 0})])
    with db.new_session() as s:
        out = handle_incoming(s, s.get(Business, b.id), IncomingMessage("telegram", "e1", "text", "Пробный. Айгерим, 0555 525 626", "", "e1"),
                              lambda: llm, NOW_UTC)
        s.commit()
        assert s.get(Booking, out.booking_id).service == "пробный урок, ОРТ, 10 класс"
    system = llm.calls[0]["system"]
    assert "Не обещай баллы, поступление или грант" in system and "к какому экзамену готовится, класс или текущий уровень" in system
