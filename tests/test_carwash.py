"""Car washes and detailing (joop/niches/carwash): «можно сейчас?» gets a box in 15 minutes, not in an hour."""

from datetime import timedelta

from sqlmodel import select

from joop import db
from joop.agent.engine import handle_incoming
from joop.agent.llm import AgentReply
from joop.channels.base import IncomingMessage
from joop.models import Business, Slot, Staff
from joop.niches import get_pack
from joop.presets import create_business
from joop.timeutil import utc_to_local

from .conftest import NOW_UTC, FakeLLM

NOW_LOCAL = utc_to_local(NOW_UTC, "Asia/Bishkek").replace(second=0, microsecond=0)


def soon_slot(niche, slug, minutes=30):
    """A business of this niche (its demo is its own) with one free time `minutes` from now."""
    with db.new_session() as s:
        b = create_business(s, slug=slug, name=slug.title(), password="pass-12345", niche=niche, demo=True, now_utc=NOW_UTC)
        b.example_ok = True
        s.flush()
        member = s.exec(select(Staff).where(Staff.business_id == b.id).order_by(Staff.id)).first()
        slot = Slot(business_id=b.id, staff_id=member.id, start=NOW_LOCAL + timedelta(minutes=minutes), duration_min=60)
        s.add(slot)
        s.commit()
        return b, slot


def prompt(business_id, text):
    llm = FakeLLM([AgentReply("Есть окно.")])
    with db.new_session() as s:
        msg = IncomingMessage("telegram", "w1", "text", text, "", f"w-{business_id}-{len(text)}")  # a new message id each time
        handle_incoming(s, s.get(Business, business_id), msg, lambda: llm, NOW_UTC)
        s.commit()
    return llm.calls[0]["system"]


def test_a_car_wash_offers_a_box_in_half_an_hour(engine):
    assert get_pack("carwash").lead_minutes == 15 and get_pack("beauty").lead_minutes == 60
    wash, slot = soon_slot("carwash", "wash")
    assert f"- {slot.id}: " in prompt(wash.id, "Можно сейчас помыть кроссовер?")
    assert "седан 600, кроссовер 700, внедорожник 800" in prompt(wash.id, "Цена комплексной мойки?")
    salon, other = soon_slot("beauty", "salon")
    assert f"- {other.id}: " not in prompt(salon.id, "Можно сейчас на маникюр?")  # a salon still needs an hour's notice
