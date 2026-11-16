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
        b.example_ok = True  # this guest house's rooms are its own (they equal the hotel example)
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


def test_a_hotels_numbers_reports_and_dashboard_count_the_stays(engine, settings, rt):
    """A hotel's AI books rooms (Stay), but every number counted only Booking: the dashboard, the morning and weekly
    reports and the pilot table showed «0 записей» for a hotel whose AI had booked rooms."""
    from joop import pilot
    from joop.scheduler import digest_text, weekly_report_text
    from joop.stats import activity

    b, rooms = hotel()
    out = say(b.id, "Коттедж на 5 человек, Алмаз, 0555 667 788", FakeLLM([stay(rooms["Коттедж"].id, days_from=1, guests=5)]), "n1")
    assert out.stay_id
    with db.new_session() as s:
        biz = s.get(Business, b.id)
        n = activity(s, b.id, NOW_UTC - timedelta(days=1))
        assert n["stays"] == 1 and n["off_hours_stays"] in (0, 1) and n["bookings"] == 0
        assert "броней номеров 1" in weekly_report_text(s, biz, NOW_UTC + timedelta(hours=1))
        digest = digest_text(s, biz, NOW_UTC + timedelta(hours=1))
        assert "броней номеров через ИИ 1" in digest and "Сегодня заезжают:" in digest and "Алмаз" in digest
        rows, total = pilot.report(s, NOW_UTC - timedelta(days=1), NOW_UTC + timedelta(hours=1), NOW_UTC)
        assert total.stays == 1 and total.completed == 1 and "stays" in pilot.to_csv(rows, total).splitlines()[0]
    with TestClient(create_app(settings, rt, init=False)) as c:
        c.post("/login", data={"slug": "hotel", "password": "hotel-pass", "csrf": csrf_of(c.get("/login").text)})
        page = c.get("/panel").text
        assert "броней номеров сделал ИИ" in page and "Ближайшие брони" in page and "Алмаз" in page
        assert "заявок на запись" not in page  # a hotel takes no booking requests
        assert "Номеров этого типа" in c.get("/panel/staff").text and "удаление зубов" not in c.get("/panel/staff").text


def test_the_booked_dates_in_the_reply_come_from_the_booking(engine):
    b, rooms = hotel()
    family = rooms["Семейный номер"].id
    d = TODAY + timedelta(days=10)
    data = {"room_id": family, "check_in": d.isoformat(), "check_out": (d + timedelta(days=3)).isoformat(),
            "guests": 2, "name": "Алмаз", "phone": "0555667788"}
    dates = f"{d:%d.%m.%Y}–{d + timedelta(days=3):%d.%m.%Y}"
    wrong = say(b.id, "Семейный, Алмаз 0555667788", FakeLLM([AgentReply("Забронировала с 01.01 по 04.01!", stay=dict(data))]), "d1", chat="d1")
    assert wrong.reply == f"Забронировала «Семейный номер» на {dates}, гостей: 2. Администратор свяжется с вами насчёт оплаты."
    plain = say(b.id, "Семейный, Алмаз 0555667788", FakeLLM([AgentReply("Забронировала!", stay=dict(data))]), "d2", chat="d2")
    assert plain.reply == f"Забронировала!\nБронь: «Семейный номер», {dates}, гостей: 2."
    right_text = f"Ждём вас с {d:%d.%m} по {d + timedelta(days=3):%d.%m}."
    right = say(b.id, "Семейный, Алмаз 0555667788", FakeLLM([AgentReply(right_text + " Мы в 2.5 км от центра.", stay=dict(data))]),
                "d3", chat="d3")
    assert right.reply == f"{right_text} Мы в 2.5 км от центра.\nБронь: «Семейный номер», {dates}, гостей: 2."
    d = TODAY + timedelta(days=30)
    one = dict(data, check_in=d.isoformat(), check_out=(d + timedelta(days=1)).isoformat())
    night = say(b.id, "Семейный на ночь, Алмаз 0555667788",
                FakeLLM([AgentReply(f"Забронировала с {d:%d.%m} по {d + timedelta(days=5):%d.%m}!", stay=one)]), "d4", chat="d4")
    assert night.reply.startswith(f"Забронировала «Семейный номер» на {d:%d.%m.%Y}–{d + timedelta(days=1):%d.%m.%Y}")



def test_a_kyrgyz_chat_reads_the_stay_line_in_kyrgyz_and_no_rewrite_touches_it(engine):
    """The model's Russian reply in a Kyrgyz chat is rewritten by the model: the code's dates are added only after that."""
    b, rooms = hotel()
    d = TODAY + timedelta(days=10)
    data = {"room_id": rooms["Семейный номер"].id, "check_in": d.isoformat(), "check_out": (d + timedelta(days=3)).isoformat(),
            "guests": 2, "name": "Алмаз", "phone": "0555667788"}
    llm = FakeLLM([AgentReply("Забронировала!", stay=data)], rewrites=["Рахмат, бөлмөнү сиз үчүн брондоп койдум, күтөбүз."])
    out = say(b.id, "Саламатсызбы, үй-бүлөлүк бөлмө керек, Алмаз 0555667788", llm, "k1", chat="k1")
    assert llm.rewrite_calls == ["Забронировала!"]  # the model rewrote its own words only
    dates = f"{d:%d.%m.%Y}–{d + timedelta(days=3):%d.%m.%Y}"
    assert out.reply == f"Рахмат, бөлмөнү сиз үчүн брондоп койдум, күтөбүз.\nБрон: «Семейный номер», {dates}, конок саны: 2."


def test_the_panel_books_a_guest_who_phoned(engine, settings, rt):
    """«Забронировать гостя» on the panel's page: the app's rules, marked «вручную»; a full room is refused."""
    b, rooms = hotel()
    cottage = rooms["Коттедж"]  # one cottage
    d1, d2 = TODAY + timedelta(days=4), TODAY + timedelta(days=6)
    form = {"room_id": cottage.id, "check_in": d1.isoformat(), "check_out": d2.isoformat(), "guests": 2,
            "name": "Нурлан", "phone": "0555 101 202"}
    with TestClient(create_app(settings, rt, init=False)) as c:
        token = csrf_of(c.get("/login").text)
        c.post("/login", data={"slug": "hotel", "password": "hotel-pass", "csrf": token})
        page = c.get("/panel/stays").text
        assert "Забронировать гостя" in page and f'value="{cottage.id}"' in page
        r = c.post("/panel/stays/new", data=dict(form, csrf=csrf_of(page)))
        assert f"Забронировано: Нурлан, «Коттедж», {d1:%d.%m}–{d2:%d.%m}." in r.text and "вручную" in r.text
        again = c.post("/panel/stays/new", data=dict(form, name="Бакыт", csrf=csrf_of(r.text)))
        assert "«Коттедж» на эти даты уже занят." in again.text
        nameless = c.post("/panel/stays/new", data=dict(form, name=" ", csrf=csrf_of(again.text)))
        assert "Укажите имя клиента." in nameless.text
        assert c.post("/panel/stays/new", data=dict(form, csrf="wrong")).status_code in (400, 403)
    with db.new_session() as s:
        made = s.exec(select(Stay).where(Stay.business_id == b.id)).all()
        assert [(x.customer_name, x.source, x.customer_phone) for x in made] == [("Нурлан", "staff", "+996555101202")]
