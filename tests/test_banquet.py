"""Banquet halls and toi halls (joop/niches/banquet): a hall is booked for one date, checked against its capacity."""

from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlmodel import select

from joop import db, stays
from joop.agent.engine import handle_incoming
from joop.agent.llm import AgentReply
from joop.channels.base import IncomingMessage
from joop.models import Business, RoomNight, Staff, Stay
from joop.niches import get_pack
from joop.presets import create_business
from joop.scheduler import digest_text, weekly_report_text
from joop.timeutil import utc_to_local
from joop.web.app import create_app

from .conftest import NOW_UTC, FakeLLM
from .test_web import csrf_of

TODAY = utc_to_local(NOW_UTC, "Asia/Bishkek").date()
EVENT = date(TODAY.year + 1, 9, 14)


def venue():
    with db.new_session() as s:
        b = create_business(s, slug="toi", name="Той-Холл", password="toi-pass-123", niche="banquet", demo=True, now_utc=NOW_UTC)
        b.example_ok = True  # this hall's menu and halls are its own (they equal the banquet example)
        s.commit()
        halls = {r.name: r.id for r in s.exec(select(Staff).where(Staff.business_id == b.id)).all()}
        return b, halls


def hold(hall_id, when=EVENT, guests=250, name="Айгерим", phone="0555123456", check_out=""):
    return AgentReply("Предварительно забронировала зал. Менеджер свяжется насчёт предоплаты.",
                      stay={"room_id": hall_id, "check_in": when.isoformat(), "check_out": check_out, "guests": guests,
                            "name": name, "phone": phone})


def say(business_id, text, llm, ext, chat="t1"):
    with db.new_session() as s:
        out = handle_incoming(s, s.get(Business, business_id), IncomingMessage("telegram", chat, "text", text, "", ext), lambda: llm, NOW_UTC)
        s.commit()
        return out


def test_pack_books_single_dates():
    pack = get_pack("banquet")
    assert pack.has("stay") and pack.has("lead") and pack.by_day and pack.party_size
    assert not get_pack("hotel").by_day


def test_hall_is_held_for_one_date_and_never_given_twice(engine):
    b, halls = venue()
    llm = FakeLLM([hold(halls["Большой зал"], check_out=(EVENT + timedelta(days=5)).isoformat())])
    out = say(b.id, "Большой зал на 14 сентября, 250 гостей. Айгерим, 0555 123 456", llm, "b1")
    assert out.stay_id
    system = llm.calls[0]["system"]
    assert "Залы (номер в квадратных скобках — room_id" in system and "Номера (" not in system
    assert f"[{halls['Большой зал']}] Большой зал, до 300 гостей; занятых дат нет" in system
    assert stays.HALL_RULE in system and stays.HALL_FORMAT in system and stays.STAY_RULE not in system
    assert any(n.startswith("Новая бронь зала через ИИ") and f"Большой зал: {EVENT:%d.%m.%Y}, гостей: 250" in n
               for n in out.admin_notes)
    with db.new_session() as s:
        st = s.get(Stay, out.stay_id)
        assert (st.check_in, st.check_out) == (EVENT, EVENT + timedelta(days=1))  # one date, whatever check_out said
        assert [n.night for n in s.exec(select(RoomNight).where(RoomNight.stay_id == st.id)).all()] == [EVENT]
    # The next customer's prompt shows the date as taken; the code refuses it and offers the hall that fits.
    llm = FakeLLM([hold(halls["Большой зал"], guests=60, name="Эрмек", phone="0700445566")])
    out = say(b.id, "Большой зал на 14 сентября, 60 гостей. Эрмек, 0700 445 566", llm, "b2", chat="t2")
    assert f"занятые даты: {EVENT:%d.%m.%Y}" in llm.calls[0]["system"]
    assert out.stay_id is None and out.reply.startswith(f"На {EVENT:%d.%m.%Y} «Большой зал» уже занят.")
    assert "Малый зал (до 80 гостей)" in out.reply


def test_capacity_and_no_hall_left(engine):
    b, halls = venue()
    llm = FakeLLM([hold(halls["Малый зал"], guests=120)])
    out = say(b.id, "Малый зал на 120 человек, Айгерим 0555 123 456", llm, "c1")
    assert out.stay_id is None and out.reply.startswith("«Малый зал» вмещает до 80 гостей. Свободно на")
    assert "Большой зал (до 300 гостей)" in out.reply and "Малый зал (до" not in out.reply
    say(b.id, "Большой зал, Айгерим 0555 123 456", FakeLLM([hold(halls["Большой зал"], guests=120)]), "c2")
    out = say(b.id, "Нас 200, Бакыт 0700 889 900", FakeLLM([hold(halls["Малый зал"], guests=200, name="Бакыт", phone="0700889900")]),
              "c3", chat="t3")
    assert out.stay_id is None and f"На {EVENT:%d.%m.%Y} свободного зала на 200 гостей нет." in out.reply


def test_past_month_rolls_to_next_year_and_bad_dates(engine):
    b, halls = venue()
    llm = FakeLLM([hold(halls["Малый зал"], when=date(TODAY.year, 6, 20), guests=50)])
    out = say(b.id, "Малый зал на 20 июня, 50 гостей, Айгерим 0555 123 456", llm, "d1")
    with db.new_session() as s:
        assert s.get(Stay, out.stay_id).check_in == date(TODAY.year + 1, 6, 20)
    bad = AgentReply("Готово", stay={"room_id": halls["Малый зал"], "check_in": "", "check_out": "", "guests": 50,
                                     "name": "Айгерим", "phone": "0555123456"})
    assert say(b.id, "Малый зал, Айгерим 0555 123 456", FakeLLM([bad]), "d2").reply == "Уточните, пожалуйста, дату мероприятия."


def test_panel_dashboard_and_reports_speak_of_halls(settings, rt, engine):
    b, halls = venue()
    out = say(b.id, "Большой зал сегодня, 180 гостей. Нургуль, 0555 000 999", FakeLLM([
        hold(halls["Большой зал"], when=TODAY, guests=180, name="Нургуль", phone="0555000999")]), "p1")
    assert out.stay_id
    with db.new_session() as s:
        business = s.get(Business, b.id)
        digest = digest_text(s, business, NOW_UTC)
        weekly = weekly_report_text(s, business, NOW_UTC)
    assert "Сегодня мероприятия:" in digest and "Большой зал — Нургуль, +996555000999, гостей: 180" in digest
    assert "броней залов через ИИ 1" in digest and "заезжают" not in digest
    assert "броней залов 1" in weekly and "номеров" not in weekly
    with TestClient(create_app(settings, rt, init=False)) as c:
        token = csrf_of(c.get("/login").text)
        c.post("/login", data={"slug": "toi", "password": "toi-pass-123", "csrf": token})
        page = c.get("/panel/stays").text
        assert "<h1>Брони залов</h1>" in page and "<th>Зал</th>" in page and f"{TODAY:%d.%m.%Y}" in page
        dash = c.get("/panel").text
        assert "Брони залов" in dash and "броней залов сделал ИИ" in dash and "номер" not in dash.split("Ближайшие брони")[1][:600]
        staff = c.get("/panel/staff").text
        assert "Каждая строка — зал" in staff and "Номеров этого типа" not in staff


def test_hotel_keeps_its_words(engine):
    with db.new_session() as s:
        b = create_business(s, slug="h", name="Дом", password="hotel-pass", niche="hotel", demo=True, now_utc=NOW_UTC)
        b.example_ok = True
        s.commit()
        room = s.exec(select(Staff).where(Staff.business_id == b.id, Staff.name == "Коттедж")).one().id
    d = TODAY + timedelta(days=10)
    llm = FakeLLM([AgentReply("Забронировала.", stay={"room_id": room, "check_in": d.isoformat(),
                                                       "check_out": (d + timedelta(days=2)).isoformat(), "guests": 4,
                                                       "name": "Алмаз", "phone": "0555667788"})])
    out = say(b.id, "Коттедж, Алмаз 0555 667 788", llm, "h1")
    assert out.stay_id and stays.STAY_RULE in llm.calls[0]["system"] and "Залы (" not in llm.calls[0]["system"]
    assert any(n.startswith("Новая бронь номера") for n in out.admin_notes)


def test_launch_checklist_and_example_banner_name_halls(settings, rt, engine):
    from joop.web.saas import checklist

    with db.new_session() as s:
        b = create_business(s, slug="toi2", name="Той", password="toi-pass-123", niche="banquet", demo=True, now_utc=NOW_UTC)
        s.commit()
        hint = next(i["hint"] for i in checklist(s, b, NOW_UTC) if i["key"] == "try")
    assert hint.endswith("спросите цену, забронируйте зал на дату.")
    with TestClient(create_app(settings, rt, init=False)) as c:
        token = csrf_of(c.get("/login").text)
        c.post("/login", data={"slug": "toi2", "password": "toi-pass-123", "csrf": token})
        assert "Настоящим клиентам ИИ эти залы не называет" in c.get("/panel/staff").text


def test_full_dates_use_theme_colours(settings, rt, engine):
    """The taken cell had a fixed cream background: in the dark theme its light text could not be read."""
    b, halls = venue()
    say(b.id, "Большой зал на завтра, Айгерим 0555 123 456", FakeLLM([hold(halls["Большой зал"], when=TODAY + timedelta(days=1))]), "f1")
    with TestClient(create_app(settings, rt, init=False)) as c:
        token = csrf_of(c.get("/login").text)
        c.post("/login", data={"slug": "toi", "password": "toi-pass-123", "csrf": token})
        page = c.get("/panel/stays").text
        assert '<td class="mono small full">1/1</td>' in page and "#f9eeda" not in page
