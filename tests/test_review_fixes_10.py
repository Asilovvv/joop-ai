"""Independent review of PRs #222-#231: each test failed before its fix."""
from .test_niches import item, make, say
from .conftest import FakeLLM
from joop.agent.llm import AgentReply


def _order(b):
    plov = item(b, "Плов")
    return {"address": "Киевская 1", "time": "", "name": "Айбек", "phone": "0555123456", "comment": "",
            "mode": "delivery", "lines": [{"item_id": plov.id, "quantity": 2, "note": ""}]}


def test_order_sentence_without_claim_word_keeps_a_wrong_sum(engine):
    """2 × Плов + delivery = 850. «Стоимость заказа 1 500 сом» names a sum the order does not have."""
    b = make("restaurant")
    llm = FakeLLM([AgentReply("Готовим! Стоимость заказа 1 500 сом, курьер позвонит.", order=_order(b))])
    out = say(b, "2 плова на Киевскую 1", llm, "r1")
    assert "1 500" not in out.reply, out.reply


def test_order_summa_names_the_items_total_not_the_order_total(engine):
    """«Сумма 700 сом» for an 850 order: the customer reads two different totals."""
    b = make("restaurant")
    llm = FakeLLM([AgentReply("Оформила заказ. Сумма 700 сом.", order=_order(b))])
    out = say(b, "2 плова на Киевскую 1", llm, "r2")
    assert "700" not in out.reply.split("\n")[0], out.reply


def test_order_total_with_comma_thousands_is_not_checked(engine):
    """«итого 1,200 сом» for an 850 order."""
    b = make("restaurant")
    llm = FakeLLM([AgentReply("Оформила, итого 1,200 сом.", order=_order(b))])
    out = say(b, "2 плова на Киевскую 1", llm, "r3")
    assert "1,200" not in out.reply, out.reply


from datetime import timedelta as _td
from .test_stays import TODAY, hotel, say as stay_say  # noqa: E402


def _family(rooms, d, guests=2):
    return {"room_id": rooms["Семейный номер"].id, "check_in": d.isoformat(), "check_out": (d + _td(days=3)).isoformat(),
            "guests": guests, "name": "Алмаз", "phone": "0555667788"}


def test_stay_claim_with_a_wrong_total_reaches_the_customer(engine):
    """Семейный номер: 6 000 за ночь × 3 = 18 000. The model's «итого 15 000 сом» is never checked for a stay."""
    b, rooms = hotel()
    d = TODAY + _td(days=10)
    reply = f"Забронировала «Семейный номер» с {d:%d.%m} по {d + _td(days=3):%d.%m}, итого 15 000 сом."
    out = stay_say(b.id, "Семейный, Алмаз 0555667788", FakeLLM([AgentReply(reply, stay=_family(rooms, d))]), "x1", chat="x1")
    assert "15 000" not in out.reply, out.reply


def test_stay_claim_with_the_wrong_year_reaches_the_customer(engine):
    """Booked for a date ~200 days ahead; the model's sentence names the same day.month a year later."""
    b, rooms = hotel()
    booked = TODAY + _td(days=200)
    wrong = booked.replace(year=booked.year + 1)
    reply = f"Забронировала «Семейный номер» на {wrong:%d.%m.%Y}–{wrong + _td(days=3):%d.%m.%Y}."
    out = stay_say(b.id, f"Семейный на {booked:%d.%m.%Y}, Алмаз 0555667788",
                   FakeLLM([AgentReply(reply, stay=_family(rooms, booked))]), "x2", chat="x2")
    assert out.stay_id
    assert f"{wrong:%d.%m.%Y}" not in out.reply, out.reply


def test_stay_claim_with_other_guests_than_booked(engine):
    b, rooms = hotel()
    d = TODAY + _td(days=10)
    reply = f"Забронировала «Семейный номер» с {d:%d.%m} по {d + _td(days=3):%d.%m}, гостей: 4."
    out = stay_say(b.id, "Семейный, Алмаз 0555667788", FakeLLM([AgentReply(reply, stay=_family(rooms, d, guests=2))]), "x3", chat="x3")
    assert "гостей: 4" not in out.reply, out.reply


def test_a_test_chat_stay_holds_the_room_but_the_app_hides_it(engine, settings, rt):
    """The owner tries the AI in the panel's test chat and books the only cottage: the nights are really taken (as the
    digest says, «a test booking holds a real date»), but «Брони» in the app does not list it, so staff on the phone
    see the cottage as full with no booking to cancel."""
    from fastapi.testclient import TestClient
    from joop.agent.engine import handle_incoming
    from joop.channels.base import IncomingMessage
    from joop.models import Business
    from joop.web.app import create_app
    from joop import db
    from .conftest import NOW_UTC
    from .test_stays import stay

    b, rooms = hotel()
    cottage = rooms["Коттедж"].id
    with db.new_session() as s:
        out = handle_incoming(s, s.get(Business, b.id), IncomingMessage("console", "panel", "text", "Коттедж, Алмаз 0555667788",
                              "", "t1"), lambda: FakeLLM([stay(cottage, days_from=5, nights=2, guests=2)]), NOW_UTC)
        s.commit()
    assert out.stay_id
    d1, d2 = (TODAY + _td(days=5)).isoformat(), (TODAY + _td(days=7)).isoformat()
    with TestClient(create_app(settings, rt, init=False)) as c:
        token = c.post("/api/mobile/login", json={"company": "hotel", "password": "hotel-pass", "user": ""}).json()["token"]
        h = {"Authorization": f"Bearer {token}"}
        free = {r["id"]: r["free"] for r in c.get(f"/api/mobile/stays/rooms?check_in={d1}&check_out={d2}", headers=h).json()["rooms"]}
        listed = [x["id"] for x in c.get("/api/mobile/stays", headers=h).json()["stays"]]
    assert free[cottage] == 0  # the test booking holds the cottage...
    assert out.stay_id in listed  # ...so the app must show it (to cancel it)


def test_a_wrong_hour_survives_the_kyrgyz_rewrite_and_the_booking_check(business):
    """The booked slot is H:00; the model's draft says (H+1):00. In Russian the claim sentence is removed
    (confirmations.with_booking); in a Kyrgyz chat same_numbers lets «саат {H+1}до» stand for «{H+1}:00» (#231), and
    with_booking reads only «HH:MM» clock times, so the wrong hour reaches the customer next to the code's line."""
    from sqlmodel import select
    from joop import db
    from joop.models import Slot
    from .test_kyrgyz_and_cost import say as ky_say

    with db.new_session() as s:
        slot = s.exec(select(Slot).where(Slot.status == "free").order_by(Slot.start)).first()
    wrong = slot.start.hour + 1
    booking = {"slot_id": slot.id, "name": "Гүлнара", "phone": "0555321654", "service": "чистка", "preferred_time": ""}
    llm = FakeLLM([AgentReply(f"Записала вас на {wrong}:00.", booking=booking)],
                  rewrites=[f"Сизди саат {wrong}де жазып койдум. Рахмат!"])
    out = ky_say(business, "Атым Гүлнара, 0555 321 654, эртең тиш тазалоо", llm, "kx1")
    assert out.booking_id
    assert f"саат {wrong}де" not in out.reply, out.reply


def test_a_hall_date_at_the_end_of_the_calendar_is_a_500(engine, settings, rt):
    from fastapi.testclient import TestClient
    from sqlmodel import select
    from joop import db
    from joop.models import Staff
    from joop.presets import create_business
    from joop.web.app import create_app
    from .conftest import NOW_UTC

    with db.new_session() as s:
        b = create_business(s, slug="hall", name="Зал", password="hall-pass", niche="banquet", demo=True, now_utc=NOW_UTC)
        b.example_ok = True
        s.commit()
        hall = s.exec(select(Staff).where(Staff.business_id == b.id)).first().id
    with TestClient(create_app(settings, rt, init=False), raise_server_exceptions=False) as c:
        token = c.post("/api/mobile/login", json={"company": "hall", "password": "hall-pass", "user": ""}).json()["token"]
        h = {"Authorization": f"Bearer {token}"}
        rooms = c.get("/api/mobile/stays/rooms?check_in=9999-12-31", headers=h)
        new = c.post("/api/mobile/stays", headers=h, json={"room_id": hall, "check_in": "9999-12-31", "name": "А", "phone": ""})
    assert (rooms.status_code, new.status_code) == (400, 409)
