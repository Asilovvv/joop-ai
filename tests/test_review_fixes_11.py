"""Fixes from the independent review of PRs #158-#162."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlmodel import select

from joop import db
from joop.agent.engine import handle_incoming
from joop.agent.llm import AgentReply
from joop.channels.base import IncomingMessage
from joop.models import Business, Service, Staff
from joop.owner_commands import answer
from joop.presets import create_business
from joop.timeutil import utc_to_local
from joop.web.app import create_app

from .conftest import NOW_UTC, FakeLLM
from .test_web import csrf_of

TODAY = utc_to_local(NOW_UTC, "Asia/Bishkek").date()


def make(niche, slug):
    with db.new_session() as s:
        b = create_business(s, slug=slug, name=slug.title(), password="pass-12345", niche=niche, demo=True, now_utc=NOW_UTC)
        b.example_ok = True
        s.commit()
        return b


def say(business_id, text, reply, ext):
    with db.new_session() as s:
        out = handle_incoming(s, s.get(Business, business_id), IncomingMessage("telegram", ext, "text", text, "", ext),
                              lambda: FakeLLM([reply]), NOW_UTC)
        s.commit()
        return out


def test_a_fractional_weight_is_never_rounded_into_a_price(engine):
    """«Медовик 2,5 кг» became 2 kg at 3 200 сом; the string "2.5" crashed the order."""
    b = make("bakery", "tort")
    with db.new_session() as s:
        cake = s.exec(select(Service).where(Service.business_id == b.id, Service.name == "Торт «Медовик», за 1 кг")).one()
    for qty in (2.5, "2.5"):
        out = say(b.id, "Медовик 2,5 кг. Айгуль, 0555 212 323", AgentReply("Оформила.", order={
            "lines": [{"item_id": cake.id, "quantity": qty, "note": ""}], "mode": "pickup", "address": "", "time": "суббота",
            "name": "Айгуль", "phone": "0555212323", "comment": ""}), f"q{qty}")
        assert out.order_id is None


def test_bakery_delivery_is_in_the_total(engine):
    b = make("bakery", "tort2")
    with db.new_session() as s:
        cake = s.exec(select(Service).where(Service.business_id == b.id, Service.name == "Торт «Медовик», за 1 кг")).one()
    out = say(b.id, "Медовик 2 кг с доставкой. Нурай, 0700 434 545", AgentReply("Оформила.", order={
        "lines": [{"item_id": cake.id, "quantity": 2, "note": ""}], "mode": "delivery", "address": "Ахунбаева 120", "time": "суббота",
        "name": "Нурай", "phone": "0700434545", "comment": ""}), "d1")
    assert out.order_id and out.reply.endswith("Сумма заказа: 3 500 сом, включая доставку 300 сом.")


def test_car_rental_pages_have_no_guests_and_today_has_no_windows(settings, rt, engine):
    b = make("carrental", "cars")
    with db.new_session() as s:
        car = s.exec(select(Staff).where(Staff.business_id == b.id, Staff.name == "Hyundai Elantra")).one()
    out = say(b.id, "Элантра. Айдай, 0555 777 888", AgentReply("Забронировала.", stay={
        "room_id": car.id, "check_in": TODAY.isoformat(), "check_out": (TODAY + timedelta(days=2)).isoformat(), "guests": 1,
        "name": "Айдай", "phone": "0555777888"}), "r1")
    assert out.stay_id
    with TestClient(create_app(settings, rt, init=False)) as c:
        token = csrf_of(c.get("/login").text)
        c.post("/login", data={"slug": "cars", "password": "pass-12345", "csrf": token})
        assert "гостей" not in c.get("/panel/stays").text.split("Предстоящие брони")[1]
        assert "гостей" not in c.get("/panel").text.split("Ближайшие брони")[1][:800]
    with db.new_session() as s:
        today = answer(s, s.get(Business, b.id), "/today", NOW_UTC)
    assert "Свободных окон" not in today and "Сегодня выдаём машины:" in today
