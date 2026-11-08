"""Fixes from the independent review of PRs #146-#150."""

from datetime import date, datetime, time, timedelta

from fastapi.testclient import TestClient
from sqlmodel import select

from joop import db
from joop.agent.engine import handle_incoming
from joop.agent.llm import AgentReply
from joop.channels.base import IncomingMessage
from joop.models import Business, Order, Service, Slot, Staff, Stay
from joop.presets import create_business
from joop.scheduler import digest_text
from joop.slots import generate_slots
from joop.timeutil import utc_to_local
from joop.web.app import create_app

from .conftest import NOW_UTC, FakeLLM
from .test_web import csrf_of

TODAY = utc_to_local(NOW_UTC, "Asia/Bishkek").date()


def make(niche, slug, real=False):
    with db.new_session() as s:
        b = create_business(s, slug=slug, name=slug.title(), password="pass-12345", niche=niche, demo=True, now_utc=NOW_UTC)
        b.example_ok = real
        s.commit()
        return b


def say(business_id, text, llm, ext, channel="telegram", chat="c1", staff_test=False):
    with db.new_session() as s:
        msg = IncomingMessage(channel, chat, "text", text, "", ext, staff_test=staff_test)
        out = handle_incoming(s, s.get(Business, business_id), msg, lambda: llm, NOW_UTC)
        s.commit()
        return out


def staff(business_id):
    with db.new_session() as s:
        return {r.name: r for r in s.exec(select(Staff).where(Staff.business_id == business_id)).all()}


def login(c, slug):
    token = csrf_of(c.get("/login").text)
    c.post("/login", data={"slug": slug, "password": "pass-12345", "csrf": token})


def test_example_hours_are_not_told_to_real_customers(engine):
    """Sign-up cleared the example address but the prompt still gave customers the example's opening hours."""
    b = make("banquet", "hall")
    llm = FakeLLM([AgentReply("Уточню."), AgentReply("Уточню.")])
    say(b.id, "До скольки вы работаете?", llm, "h1")
    say(b.id, "До скольки вы работаете?", llm, "h2", channel="console", chat="t1")
    assert "- Часы работы: уточняет администратор" in llm.calls[0]["system"]
    assert "- Часы работы: Ежедневно 10:00–24:00" in llm.calls[1]["system"]  # the test chat keeps the example on purpose


def test_a_hall_with_its_real_capacity_is_no_longer_the_example(settings, rt, engine):
    """An owner who typed the real capacity of the example hall still had it hidden: «залов в данных нет»."""
    b = make("banquet", "hall2")
    big = staff(b.id)["Большой зал"]
    with TestClient(create_app(settings, rt, init=False)) as c:
        login(c, "hall2")
        token = csrf_of(c.get("/panel/staff").text)
        c.post(f"/panel/staff/{big.id}", data={"name": big.name, "role": big.role, "handles": "", "capacity": "150", "csrf": token})
    llm = FakeLLM([AgentReply("Свободно.")])
    say(b.id, "Большой зал на 14 сентября свободен?", llm, "s1")
    system = llm.calls[0]["system"]
    assert f"[{big.id}] Большой зал, до 150 гостей" in system and "Малый зал" not in system  # untouched: still the example


def test_real_masters_times_are_not_cut_by_the_examples(engine):
    """The example masters' times took the 200 places before they were filtered out."""
    b = make("beauty", "salon")
    with db.new_session() as s:
        business = s.get(Business, b.id)
        real = Staff(business_id=b.id, name="Алина", role="мастер")
        s.add(real)
        s.flush()
        generate_slots(s, business, real.id, TODAY + timedelta(days=1), TODAY + timedelta(days=9), time(9, 0), time(21, 0), 60)  # 108 times, the example has 126
        s.commit()
        last = s.exec(select(Slot).where(Slot.staff_id == real.id).order_by(Slot.start.desc())).first()
    llm = FakeLLM([AgentReply("Есть время.")])
    say(b.id, "Когда можно на маникюр?", llm, "m1")
    assert f"- {last.id}: " in llm.calls[0]["system"]


def test_florist_dashboard_shows_orders_not_bookings(settings, rt, engine):
    b = make("florist", "flowers", real=True)
    with db.new_session() as s:
        s.add(Order(business_id=b.id, customer_name="Айпери", customer_phone="+996700334455", total=2500, channel="telegram",
                    created_at=NOW_UTC))
        s.commit()
    with TestClient(create_app(settings, rt, init=False)) as c:
        login(c, "flowers")
        page = c.get("/panel").text
    assert "Последние заказы" in page and "Айпери" in page and "Ближайшие записи" not in page
    assert "уведомлений о заказах и заявках" in page


def test_shop_digest_counts_orders_and_marks_owner_tests(engine):
    shop = make("shop", "shop", real=True)
    with db.new_session() as s:
        s.add(Order(business_id=shop.id, customer_name="Асель", customer_phone="+996555112233", total=3400, channel="telegram",
                    created_at=NOW_UTC - timedelta(hours=1)))
        s.commit()
    say(shop.id, "Платье есть?", FakeLLM([AgentReply("Есть.")]), "d1")
    with db.new_session() as s:
        text = digest_text(s, s.get(Business, shop.id), NOW_UTC)
    assert "заказов через ИИ 1" in text and "записей" not in text.lower()
    hall = make("banquet", "hall3", real=True)
    big = staff(hall.id)["Большой зал"]
    booking = AgentReply("Забронировала.", stay={"room_id": big.id, "check_in": TODAY.isoformat(), "check_out": "", "guests": 100,
                                                 "name": "Айгерим", "phone": "0555123456"})
    out = say(hall.id, "Большой зал сегодня, Айгерим 0555 123 456", FakeLLM([booking]), "d2", staff_test=True)
    assert out.stay_id
    with db.new_session() as s:
        text = digest_text(s, s.get(Business, hall.id), NOW_UTC)
    # Listed (it holds the real date until someone frees it), marked, and not counted as the AI's work.
    assert "Большой зал — Айгерим, +996555123456, гостей: 100 (тест)" in text and "броней залов через ИИ 0" in text


def test_a_hall_is_one_hall_whatever_room_count_it_kept(engine):
    """A hotel switched to banquet kept «6 rooms» per type: the prompt and the booking disagreed."""
    b = make("banquet", "hall4", real=True)
    big = staff(b.id)["Большой зал"]
    with db.new_session() as s:
        row = s.get(Staff, big.id)
        row.group_size = 6
        s.add(row)
        s.commit()
    when = date(TODAY.year + 1, 9, 14)

    def hold(name, phone):
        return AgentReply("Забронировала.", stay={"room_id": big.id, "check_in": when.isoformat(), "check_out": "", "guests": 100,
                                                  "name": name, "phone": phone})

    assert say(b.id, "Большой зал, Айгерим 0555 123 456", FakeLLM([hold("Айгерим", "0555123456")]), "u1").stay_id
    llm = FakeLLM([hold("Бакыт", "0700889900")])
    second = say(b.id, "Большой зал, Бакыт 0700 889 900", llm, "u2", chat="c2")
    assert f"занятые даты: {when:%d.%m.%Y}" in llm.calls[0]["system"]
    assert second.stay_id is None and second.reply.startswith(f"На {when:%d.%m.%Y} «Большой зал» уже занят.")


def test_yesterdays_event_is_not_upcoming(settings, rt, engine):
    b = make("banquet", "hall5", real=True)
    big = staff(b.id)["Большой зал"]
    with db.new_session() as s:
        for name, day in (("Вчерашняя", TODAY - timedelta(days=1)), ("Сегодняшняя", TODAY)):
            s.add(Stay(business_id=b.id, staff_id=big.id, room_name=big.name, check_in=day, check_out=day + timedelta(days=1),
                       guests=50, customer_name=name, customer_phone="+996555000000", channel="telegram",
                       created_at=datetime.combine(day, time(9))))
        s.commit()
    with TestClient(create_app(settings, rt, init=False)) as c:
        login(c, "hall5")
        page = c.get("/panel/stays").text
    assert "Сегодняшняя" in page and "Вчерашняя" not in page


def test_an_example_item_cannot_be_ordered_by_a_real_customer(engine):
    """The prompt hid the example catalog, but an order naming its id was accepted at the fictional price."""
    b = make("shop", "shop2")
    with db.new_session() as s:
        hoodie = s.exec(select(Service).where(Service.business_id == b.id, Service.name == "Худи чёрное, размер M")).one()

    def order():
        return AgentReply("Оформила.", order={"lines": [{"item_id": hoodie.id, "quantity": 1, "note": ""}], "mode": "pickup",
                                              "address": "", "time": "", "name": "Асель", "phone": "0555112233", "comment": ""})

    out = say(b.id, "Худи M, Асель 0555 112 233", FakeLLM([order()]), "o1")
    assert out.order_id is None and "одной позиции нет в списке" in out.reply
    with db.new_session() as s:
        assert s.get(Service, hoodie.id).stock == 4
    assert say(b.id, "Худи M, Асель 0555 112 233", FakeLLM([order()]), "o2", channel="console", chat="t1").order_id  # the test chat may
