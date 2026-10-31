from datetime import timedelta

from fastapi.testclient import TestClient
from sqlmodel import select

from joop import db, stays
from joop.agent.engine import ASK_CONTACTS_REPLY, handle_incoming
from joop.agent.llm import AgentReply, coerce_reply, response_schema
from joop.channels.base import IncomingMessage
from joop.models import Business, RoomNight, Staff, Stay
from joop.presets import create_business
from joop.timeutil import utc_to_local
from joop.web.app import create_app

from .conftest import NOW_UTC, FakeLLM
from .test_web import csrf_of

TODAY = utc_to_local(NOW_UTC, "Asia/Bishkek").date()


def hotel():
    with db.new_session() as s:
        b = create_business(s, slug="hotel", name="Гостевой дом", password="hotel-pass", niche="hotel", demo=True, now_utc=NOW_UTC)
        s.commit()
        rooms = {r.name: r for r in s.exec(select(Staff).where(Staff.business_id == b.id)).all()}
        return b, rooms


def stay(room_id, days_from=10, nights=3, guests=2, name="Алмаз", phone="0555667788"):
    d = TODAY + timedelta(days=days_from)
    return AgentReply("Забронировала номер.", stay={"room_id": room_id, "check_in": d.isoformat(),
                      "check_out": (d + timedelta(days=nights)).isoformat(), "guests": guests, "name": name, "phone": phone})


def say(business_id, text, llm, ext, chat="h1"):
    with db.new_session() as s:
        out = handle_incoming(s, s.get(Business, business_id), IncomingMessage("telegram", chat, "text", text, "", ext), lambda: llm, NOW_UTC)
        s.commit()
        return out


def test_schema_and_coercion():
    assert "stay" in response_schema({"stay", "handoff"})["properties"]
    r = coerce_reply({"reply": "ok", "stay": {"room_id": "3", "check_in": "2027-07-10", "check_out": "2027-07-13", "guests": "2", "name": "А", "phone": "1"}})
    assert r.stay["room_id"] == 3 and r.stay["guests"] == 2


def test_last_cottage_cannot_be_sold_twice(engine):
    b, rooms = hotel()
    cottage = rooms["Коттедж"].id
    llm = FakeLLM([stay(cottage, guests=5)])
    out = say(b.id, "Коттедж на 5 человек, Алмаз, 0555 667 788", llm, "s1")
    assert out.stay_id and "Номера (номер в квадратных скобках" in llm.calls[0]["system"]
    assert any("Новая бронь номера" in n for n in out.admin_notes)
    # Overlapping dates: the only cottage is taken; the AI gets alternatives instead.
    out = say(b.id, "Коттедж, Айдай 0700 111 222", FakeLLM([stay(cottage, days_from=12, guests=2, name="Айдай", phone="0700111222")]), "s2", chat="h2")
    assert out.stay_id is None and "уже занят" in out.reply and "Стандартный номер" in out.reply
    # Check-out day is free for a new arrival.
    out = say(b.id, "Коттедж, Айдай 0700 111 222", FakeLLM([stay(cottage, days_from=13, guests=2, name="Айдай", phone="0700111222")]), "s3", chat="h2")
    assert out.stay_id
    with db.new_session() as s:
        assert len(s.exec(select(RoomNight).where(RoomNight.staff_id == cottage)).all()) == 6


def test_rules(engine):
    b, rooms = hotel()
    family = rooms["Семейный номер"].id
    assert "рассчитан на 4 гостей" in say(b.id, "Нас 6, Алмаз 0555667788", FakeLLM([stay(family, guests=6)]), "r1").reply
    assert "даты" in say(b.id, "Алмаз 0555667788", FakeLLM([stay(family, days_from=-3)]), "r2").reply
    out = say(b.id, "Номер на троих", FakeLLM([stay(family, guests=3, name="Клиент")]), "r3", chat="r3")
    assert out.reply == ASK_CONTACTS_REPLY and out.stay_id is None


def test_panel_grid_and_cancel(engine, settings, rt):
    b, rooms = hotel()
    out = say(b.id, "Стандарт, Алмаз 0555667788", FakeLLM([stay(rooms["Стандартный номер"].id, days_from=1, nights=2)]), "p1")
    with TestClient(create_app(settings, rt, init=False)) as c:
        token = csrf_of(c.get("/login").text)
        c.post("/login", data={"slug": "hotel", "password": "hotel-pass", "csrf": token})
        page = c.get("/panel/stays")
        assert "Брони номеров" in page.text and "1/6" in page.text and "Алмаз" in page.text
        r = c.post(f"/panel/stays/{out.stay_id}/cancel", data={"csrf": csrf_of(page.text)})
        assert "отменена" in r.text
    with db.new_session() as s:
        assert s.get(Stay, out.stay_id).status == "cancelled"
        assert not s.exec(select(RoomNight).where(RoomNight.stay_id == out.stay_id)).all()


def test_free_rooms_counts_every_night(engine):
    b, rooms = hotel()
    std = rooms["Стандартный номер"]
    with db.new_session() as s:
        assert stays.free_rooms(s, std, TODAY + timedelta(days=1), TODAY + timedelta(days=3)) == 6


def test_past_date_without_year_means_next_year(engine):
    b, rooms = hotel()
    family = rooms["Семейный номер"].id
    last_year = TODAY - timedelta(days=90)  # "с 1 августа" written in October, model chose this year
    reply = AgentReply(f"Забронировала на {last_year:%d.%m.%Y}.", stay={
        "room_id": family, "check_in": last_year.isoformat(), "check_out": (last_year + timedelta(days=3)).isoformat(),
        "guests": 2, "name": "Нурлан", "phone": "0700889900"})
    out = say(b.id, "Семейный номер с 1 по 4 августа, Нурлан 0700 889 900", FakeLLM([reply]), "y1", chat="y1")
    assert out.stay_id and str(last_year.year) not in out.reply
    with db.new_session() as s:
        st = s.get(Stay, out.stay_id)
        assert st.check_in == stays._next_year(last_year) and (st.check_out - st.check_in).days == 3
    # The customer wrote a year: no guessing, the dates are refused as past.
    reply.stay["check_in"], reply.stay["check_out"] = last_year.isoformat(), (last_year + timedelta(days=3)).isoformat()
    out = say(b.id, f"Семейный номер с 1 по 4 августа {last_year.year}, Нурлан 0700 889 900", FakeLLM([reply]), "y2", chat="y2")
    assert out.stay_id is None and "даты" in out.reply
