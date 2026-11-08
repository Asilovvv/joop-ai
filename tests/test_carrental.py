"""Car rental (joop/niches/carrental): cars booked by days like hotel rooms, in the words of a car hire."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlmodel import select

from joop import db, stays
from joop.agent.engine import handle_incoming
from joop.agent.llm import AgentReply
from joop.channels.base import IncomingMessage
from joop.models import Business, Staff
from joop.niches import get_pack
from joop.presets import create_business
from joop.scheduler import digest_text
from joop.timeutil import utc_to_local
from joop.web.app import create_app

from .conftest import NOW_UTC, FakeLLM
from .test_web import csrf_of

TODAY = utc_to_local(NOW_UTC, "Asia/Bishkek").date()


def rental():
    with db.new_session() as s:
        b = create_business(s, slug="cars", name="Прокат", password="cars-pass-1", niche="carrental", demo=True, now_utc=NOW_UTC)
        b.example_ok = True  # its cars are its own
        s.commit()
        return b, {r.name: r.id for r in s.exec(select(Staff).where(Staff.business_id == b.id)).all()}


def book(business_id, car_id, start, days, chat, name="Тимур", phone="0555101202"):
    llm = FakeLLM([AgentReply("Забронировала.", stay={"room_id": car_id, "check_in": start.isoformat(),
                                                       "check_out": (start + timedelta(days=days)).isoformat(), "guests": 1,
                                                       "name": name, "phone": phone})])
    with db.new_session() as s:
        out = handle_incoming(s, s.get(Business, business_id), IncomingMessage("telegram", chat, "text", f"Бронь. {name}, {phone}", "", f"m-{chat}"),
                              lambda: llm, NOW_UTC)
        s.commit()
    return out, llm.calls[0]["system"]


def test_cars_are_booked_by_days_in_car_hire_words(engine):
    assert get_pack("carrental").rental and get_pack("carrental").stay_noun == "машин" and get_pack("hotel").stay_noun == "номеров"
    b, cars = rental()
    start = TODAY + timedelta(days=5)
    out, system = book(b.id, cars["Toyota Land Cruiser Prado"], start, 3, "c1")
    assert out.stay_id
    assert "Машины (номер в квадратных скобках — room_id" in system and "Номера (" not in system
    assert f"[{cars['Toyota Camry 70']}] Toyota Camry 70, мест: 5, машин этой модели: 3" in system
    assert stays.CAR_RULE in system and stays.CAR_FORMAT in system and stays.STAY_RULE not in system
    note = next(n for n in out.admin_notes if n.startswith("Новая бронь машины через ИИ"))
    assert f"Toyota Land Cruiser Prado: {start:%d.%m} – {start + timedelta(days=3):%d.%m}" in note and "гостей" not in note
    second, _ = book(b.id, cars["Toyota Land Cruiser Prado"], start + timedelta(days=1), 2, "c2", "Нурбек", "0700303404")
    dates = f"{start + timedelta(days=1):%d.%m.%Y}–{start + timedelta(days=3):%d.%m.%Y}"
    assert second.stay_id is None and second.reply.startswith(f"На {dates} свободных «Toyota Land Cruiser Prado» нет. Свободно на {dates}:")
    assert second.reply.endswith("Какую выбираете?") and "Toyota Camry 70" in second.reply


def test_panel_and_digest_speak_of_cars(settings, rt, engine):
    b, cars = rental()
    out, _ = book(b.id, cars["Hyundai Elantra"], TODAY, 2, "p1", "Айдай", "0555777888")
    assert out.stay_id
    with db.new_session() as s:
        text = digest_text(s, s.get(Business, b.id), NOW_UTC)
    assert "Сегодня выдаём машины:" in text and f"Айдай, +996555777888 — Hyundai Elantra, до {TODAY + timedelta(days=2):%d.%m}" in text
    assert "броней машин через ИИ 1" in text and "заезжают" not in text
    with TestClient(create_app(settings, rt, init=False)) as c:
        token = csrf_of(c.get("/login").text)
        c.post("/login", data={"slug": "cars", "password": "cars-pass-1", "csrf": token})
        page = c.get("/panel/stays").text
        assert "<h1>Брони машин</h1>" in page and "<th>Машина</th>" in page and "Брони номеров" not in page
        assert "броней машин сделал ИИ" in c.get("/panel").text
        staff = c.get("/panel/staff").text
        assert "Каждая строка — модель машины" in staff and 'aria-label="Машин этой модели"' in staff
