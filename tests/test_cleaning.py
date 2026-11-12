"""Cleaning companies (joop/niches/cleaning): the code multiplies the price per m² by the area, the model repeats it."""

from sqlmodel import select

from joop import area_price, db
from joop.agent.engine import handle_incoming
from joop.agent.llm import AgentReply
from joop.channels.base import IncomingMessage
from joop.models import Booking, Business, Service, Slot, Staff
from joop.niches import get_pack
from joop.presets import create_business

from .conftest import NOW_UTC, FakeLLM


def company(niche="cleaning", slug="clean"):
    with db.new_session() as s:
        b = create_business(s, slug=slug, name="Клининг", password="clean-pass-1", niche=niche, demo=True, now_utc=NOW_UTC)
        b.example_ok = True  # its price list and crews are its own
        s.commit()
        return b


def say(business_id, text, llm, ext, chat="c1"):
    with db.new_session() as s:
        out = handle_incoming(s, s.get(Business, business_id), IncomingMessage("telegram", chat, "text", text, "", ext), lambda: llm, NOW_UTC)
        s.commit()
        return out


def test_area_is_read_from_the_customers_words():
    assert area_price.area_in(["Квартира 70 м², генеральная"]) == 70
    assert area_price.area_in(["двушка, 54 кв.м"]) == 54
    assert area_price.area_in(["120 квадратов дом"]) == 120
    assert area_price.area_in(["50 чарчы метр батир"]) == 50
    assert area_price.area_in(["Да, давайте", "у меня 45 м2"]) == 45  # named a message earlier
    assert area_price.area_in(["Асанбай 12, кв. 40, телефон 0555 334 455"]) is None  # a flat number is not an area
    assert area_price.area_in(["5 м²"]) is None and area_price.area_in(["9000 м²"]) is None


def test_the_code_multiplies_and_keeps_the_minimal_order(engine):
    pack = get_pack("cleaning")
    assert pack.offers("area_price") and pack.has("booking") and not pack.has("order")
    b = company()
    llm = FakeLLM([AgentReply("Уточните площадь."), AgentReply("От 8 400 сом."), AgentReply("От 2 500 сом.")])
    say(b.id, "Сколько стоит генеральная уборка?", llm, "c1")
    say(b.id, "Квартира 70 м²", llm, "c2")
    say(b.id, "Студия 25 м², поддерживающая", llm, "s1", chat="c2")
    asked, counted, small = (c["system"] for c in llm.calls)
    assert "Спроси площадь в квадратных метрах" in asked and "Расчёт по площади" not in asked
    assert "Расчёт по площади 70 м² (посчитано системой по прайсу):" in counted
    assert "- Генеральная уборка: от 8 400 сом" in counted and "- Уборка после ремонта: от 10 500 сом" in counted
    assert "- Химчистка ковра: 10 500 сом" in counted  # an exact price stays exact
    assert "Мойка окон:" not in counted.split("Расчёт по площади")[1]  # priced per window, not per m²
    assert "- Поддерживающая уборка: от 2 500 сом (минимальный заказ 2 500 сом)" in small  # 25 × 60 = 1 500 is below it
    assert "сам не умножай и не округляй" in counted


def test_other_niches_get_no_area_estimate(engine):
    b = company("renovation", "remont")  # «от 4 000 за м²», but its total comes from the measurer's estimate
    llm = FakeLLM([AgentReply("Нужен замер.")])
    say(b.id, "Сколько стоит косметический ремонт 40 м²?", llm, "r1")
    assert "Расчёт по площади" not in llm.calls[0]["system"] and "Спроси площадь в квадратных метрах" not in llm.calls[0]["system"]


def test_crew_booking_carries_the_kind_area_and_address(engine):
    b = company()
    with db.new_session() as s:
        slot = s.exec(select(Slot).join(Staff).where(Staff.business_id == b.id, Staff.name == "Бригада 1").order_by(Slot.start)).first()
        assert s.exec(select(Service).where(Service.business_id == b.id, Service.name == "Мойка окон")).one().price == "250 за створку"
    llm = FakeLLM([AgentReply("Записала бригаду.", booking={
        "slot_id": slot.id, "name": "Жылдыз", "phone": "0555334455", "service": "генеральная уборка, 60 м², Асанбай 12, кв. 40",
        "preferred_time": "", "party_size": 0})])
    out = say(b.id, "Генеральная, 60 м², Асанбай 12, кв. 40. Жылдыз, 0555 334 455", llm, "b1")
    with db.new_session() as s:
        booking = s.get(Booking, out.booking_id)
    assert booking.service == "генеральная уборка, 60 м², Асанбай 12, кв. 40" and booking.staff_name == "Бригада 1"
    system = llm.calls[0]["system"]
    assert "сумму бери только из расчёта системы" in system and "- Генеральная уборка: от 7 200 сом" in system
