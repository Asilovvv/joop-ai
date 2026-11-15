"""The mobile app's JSON API (/api/mobile): sign-in with the panel's credentials, bookings, cancelling, services."""

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from joop import cash, db
from joop.models import Booking, Business, PanelUser, Service, Slot, Staff
from joop.security import hash_password
from joop.stats import activity
from joop.web.app import _login_fails, create_app

# NOW_UTC in conftest is Wednesday 4 November 2026, 23:14 in Bishkek: "today" is 4 Nov, "tomorrow" 5 Nov.
TOMORROW = datetime(2026, 11, 5)


@pytest.fixture
def client(settings, rt, business):
    _login_fails.clear()
    with TestClient(create_app(settings, rt, init=False)) as c:
        yield c
    _login_fails.clear()


def sign_in(c, company="aktish", password="secret-pass", user=""):
    return c.post("/api/mobile/login", json={"company": company, "password": password, "user": user})


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def book(business_id, slot: Slot, name="Айгуль", channel="whatsapp") -> int:
    with db.new_session() as s:
        slot = s.get(Slot, slot.id)
        member = s.get(Staff, slot.staff_id)
        slot.taken, slot.status = 1, "booked"
        row = Booking(business_id=business_id, slot_id=slot.id, staff_id=member.id, staff_name=member.name, start=slot.start,
                      service="Консультация", customer_name=name, customer_phone="+996700000001", channel=channel)
        s.add(slot)
        s.add(row)
        s.commit()
        return row.id


def tomorrow_slots(business_id):
    with db.new_session() as s:
        return s.exec(select(Slot).where(Slot.business_id == business_id, Slot.status == "free", Slot.start >= TOMORROW,
                                         Slot.start < TOMORROW + timedelta(days=1)).order_by(Slot.start)).all()


def test_owner_signs_in_and_a_wrong_password_does_not(client, business):
    r = sign_in(client)
    assert r.status_code == 200
    data = r.json()
    assert data["role"] == "owner" and data["business"]["slug"] == "aktish" and data["business"]["name"] == "Ак-Тиш Дент"
    assert client.get("/api/mobile/me", headers=auth(data["token"])).json()["who"] == "Владелец"
    assert sign_in(client, password="wrong").status_code == 401
    assert client.get("/api/mobile/me").status_code == 401
    assert client.get("/api/mobile/me", headers=auth("forged.token")).status_code == 401


def test_repeated_wrong_passwords_are_throttled(client, business):
    for _ in range(5):
        assert sign_in(client, password="wrong").status_code == 401
    assert sign_in(client).status_code == 429  # even the right password waits now


def test_a_new_password_ends_old_tokens(client, business):
    token = sign_in(client).json()["token"]
    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.admin_password_hash = hash_password("another-pass-1")
        s.add(b)
        s.commit()
    assert client.get("/api/mobile/me", headers=auth(token)).status_code == 401


def test_bookings_of_a_day_summary_and_cancel(client, business):
    slots = tomorrow_slots(business.id)
    first, second = book(business.id, slots[0]), book(business.id, slots[1], name="Бакыт", channel="telegram")
    book(business.id, slots[2], name="Тест", channel="console")  # the panel's test chat stays out
    token = sign_in(client).json()["token"]

    day = client.get("/api/mobile/bookings", params={"day": "2026-11-05"}, headers=auth(token)).json()
    assert [b["id"] for b in day["bookings"]] == [first, second]
    assert day["bookings"][0]["customer"]["name"] == "Айгуль" and day["bookings"][1]["channel"] == "telegram"
    assert client.get("/api/mobile/bookings", headers=auth(token)).json()["bookings"] == []  # today, 4 Nov
    assert client.get("/api/mobile/bookings", params={"day": "5 Nov"}, headers=auth(token)).status_code == 400

    summary = client.get("/api/mobile/summary", headers=auth(token)).json()
    assert summary["today"] == 0 and summary["tomorrow"] == 2 and summary["week"] == 2 and summary["next"]["id"] == first

    r = client.post(f"/api/mobile/bookings/{first}/cancel", headers=auth(token))
    assert r.status_code == 200 and r.json()["booking"]["status"] == "cancelled"
    with db.new_session() as s:
        assert s.get(Slot, slots[0].id).status == "free"  # the time is free again, as after cancelling in the panel
    assert client.post(f"/api/mobile/bookings/{first}/cancel", headers=auth(token)).status_code == 409
    assert client.get("/api/mobile/summary", headers=auth(token)).json()["tomorrow"] == 1


def test_another_business_cannot_see_or_cancel(client, business):
    from joop.presets import create_business

    from .conftest import NOW_UTC

    with db.new_session() as s:
        create_business(s, slug="other", name="Другая клиника", password="other-pass-1", demo=True, now_utc=NOW_UTC)
        s.commit()
    mine = book(business.id, tomorrow_slots(business.id)[0])
    stranger = sign_in(client, company="other", password="other-pass-1").json()["token"]
    assert client.get("/api/mobile/bookings", params={"day": "2026-11-05"}, headers=auth(stranger)).json()["bookings"] == []
    assert client.post(f"/api/mobile/bookings/{mine}/cancel", headers=auth(stranger)).status_code == 404


def test_a_master_sees_and_cancels_only_her_own_bookings(client, business):
    slots = tomorrow_slots(business.id)
    a = slots[0]
    b = next(x for x in slots if x.staff_id != a.staff_id)
    hers, other = book(business.id, a), book(business.id, b, name="Бакыт")
    with db.new_session() as s:
        s.add(PanelUser(business_id=business.id, name="Айгерим", login="aigerim", password_hash=hash_password("staff-pass-1"),
                        staff_id=a.staff_id))
        s.commit()
    r = sign_in(client, user="aigerim", password="staff-pass-1")
    assert r.status_code == 200 and r.json()["role"] == "master" and r.json()["who"] == "Айгерим"
    token = r.json()["token"]
    day = client.get("/api/mobile/bookings", params={"day": "2026-11-05"}, headers=auth(token)).json()
    assert [x["id"] for x in day["bookings"]] == [hers]
    assert client.post(f"/api/mobile/bookings/{other}/cancel", headers=auth(token)).status_code == 404
    with db.new_session() as s:
        user = s.exec(select(PanelUser).where(PanelUser.login == "aigerim")).one()
        user.active = False
        s.add(user)
        s.commit()
    assert client.get("/api/mobile/me", headers=auth(token)).status_code == 401  # a switched-off login ends at once


def test_services_list(client, business):
    token = sign_in(client).json()["token"]
    services = client.get("/api/mobile/services", headers=auth(token)).json()["services"]
    assert services and all({"id", "name", "price", "available"} <= set(x) for x in services)


def test_a_customer_opens_a_business_card_by_its_code(client, business):
    card = client.get("/api/mobile/places/AkTish").json()  # the code as a customer may type it
    assert card["name"] == "Ак-Тиш Дент" and card["booking"] is True
    assert card["services"] and all(set(x) == {"id", "name", "price", "category"} for x in card["services"])
    assert client.get("/api/mobile/places/nobody").status_code == 404
    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.bot_enabled = False
        s.add(b)
        s.commit()
    assert client.get("/api/mobile/places/aktish").status_code == 404  # a switched-off chat is not offered


def test_the_sign_up_example_is_not_shown_to_customers(client, business):
    from joop.presets import create_business

    from .conftest import NOW_UTC

    with db.new_session() as s:
        create_business(s, slug="fresh", name="Новая клиника", password="fresh-pass-1", demo=True, now_utc=NOW_UTC)
        s.commit()
    card = client.get("/api/mobile/places/fresh").json()
    assert card["name"] == "Новая клиника" and card["services"] == []  # example prices are not the clinic's real ones


def test_a_customer_chats_through_the_web_chat(client, business, llm):
    from joop.agent.llm import AgentReply

    llm.replies.append(AgentReply("Здравствуйте! Консультация стоит 500 сом."))
    r = client.post("/c/aktish/chat", json={"text": "Сколько стоит консультация?", "visitor": "a" * 24})
    assert r.status_code == 200 and "500 сом" in r.json()["reply"] and r.json()["visitor"] == "a" * 24


def _cafe_with_order_and_request():
    from joop.models import Conversation, Lead, Order, OrderLine
    from joop.presets import create_business

    from .conftest import NOW_UTC

    with db.new_session() as s:
        cafe = create_business(s, slug="navat", name="Нават", password="cafe-pass-1", niche="restaurant", demo=True,
                               now_utc=NOW_UTC)
        cafe.telegram_bot_token = "456:CAFE"
        s.add(cafe)
        s.flush()
        conv = Conversation(business_id=cafe.id, channel="telegram", chat_id="777")
        s.add(conv)
        s.flush()
        order = Order(business_id=cafe.id, conversation_id=conv.id, customer_name="Азамат", customer_phone="+996555000111",
                      mode="delivery", address="Токтогула 1", total=1200, channel="telegram", chat_id="777")
        s.add(order)
        s.flush()
        s.add(OrderLine(order_id=order.id, name="Плов", quantity=2, unit_price=600))
        s.add(Lead(business_id=cafe.id, conversation_id=conv.id, kind="handoff", summary="Можно ли банкет на 40 человек?",
                   customer_name="Азамат", channel="telegram", chat_id="777"))
        s.add(Lead(business_id=cafe.id, kind="handoff", summary="Тест из панели", channel="console", chat_id="t"))
        s.commit()
        return order.id


def test_a_cafe_owner_moves_orders_and_closes_requests(client, business, rt):
    order_id = _cafe_with_order_and_request()
    r = sign_in(client, company="navat", password="cafe-pass-1").json()
    assert r["sections"] == {"bookings": True, "orders": True, "leads": True, "cash": True}
    token = r["token"]

    orders = client.get("/api/mobile/orders", headers=auth(token)).json()["orders"]
    assert [o["id"] for o in orders] == [order_id]
    assert orders[0]["label"] == "Новый" and orders[0]["lines"][0]["name"] == "Плов"
    assert [x["status"] for x in orders[0]["next"]] == ["accepted", "cancelled"]

    moved = client.post(f"/api/mobile/orders/{order_id}/status", json={"status": "accepted"}, headers=auth(token)).json()
    assert moved["order"]["status"] == "accepted" and moved["customer_told"] is True
    assert rt.tg.sent and "777" == rt.tg.sent[-1][0]  # the customer heard it in Telegram, as from the panel
    assert [x["label"] for x in moved["order"]["next"]] == ["В пути", "Выполнен", "Отменить"]
    assert client.post(f"/api/mobile/orders/{order_id}/status", json={"status": "new"}, headers=auth(token)).status_code == 409

    leads = client.get("/api/mobile/leads", headers=auth(token)).json()["leads"]
    assert [x["summary"] for x in leads] == ["Можно ли банкет на 40 человек?"]  # the panel's test chat stays out
    done = client.post(f"/api/mobile/leads/{leads[0]['id']}/done", headers=auth(token)).json()["lead"]
    assert done["status"] == "done" and done["closed_by"] == "Владелец"


def test_orders_and_requests_are_not_a_masters_or_another_business(client, business):
    order_id = _cafe_with_order_and_request()
    clinic = sign_in(client).json()
    assert clinic["sections"]["orders"] is False  # a clinic takes bookings, not orders
    assert client.post(f"/api/mobile/orders/{order_id}/status", json={"status": "accepted"},
                       headers=auth(clinic["token"])).status_code == 404
    with db.new_session() as s:
        member = s.exec(select(Staff).where(Staff.business_id == business.id)).first()
        s.add(PanelUser(business_id=business.id, name="Айгерим", login="aigerim", password_hash=hash_password("staff-pass-1"),
                        staff_id=member.id))
        s.commit()
    master = sign_in(client, user="aigerim", password="staff-pass-1").json()
    assert master["sections"] == {"bookings": True, "orders": False, "leads": False, "cash": True}
    assert client.get("/api/mobile/leads", headers=auth(master["token"])).status_code == 403
    assert client.get("/api/mobile/orders", headers=auth(master["token"])).status_code == 403


def _handed_off(channel: str, chat_id: str, last_customer_hours_ago: float):
    from joop.models import Conversation, Lead, Message

    from .conftest import NOW_UTC

    with db.new_session() as s:
        b = s.exec(select(Business).where(Business.slug == "aktish")).one()
        conv = Conversation(business_id=b.id, channel=channel, chat_id=chat_id, customer_name="Айгуль",
                            last_customer_at=NOW_UTC - timedelta(hours=last_customer_hours_ago))
        s.add(conv)
        s.flush()
        s.add(Message(business_id=b.id, conversation_id=conv.id, role="customer", text="Можно ли лечить зуб под наркозом?"))
        s.add(Message(business_id=b.id, conversation_id=conv.id, role="ai", text="Передаю вопрос администратору."))
        s.add(Lead(business_id=b.id, conversation_id=conv.id, kind="handoff", summary="Лечение под наркозом",
                   customer_name="Айгуль", channel=channel, chat_id=chat_id))
        s.commit()
        return conv.id


def test_the_owner_answers_a_handed_off_customer(client, business, rt):
    conv_id = _handed_off("telegram", "5551", last_customer_hours_ago=2)
    token = sign_in(client).json()["token"]
    lead = client.get("/api/mobile/leads", headers=auth(token)).json()["leads"][0]
    assert lead["conversation_id"] == conv_id

    dialogue = client.get(f"/api/mobile/conversations/{conv_id}", headers=auth(token)).json()
    assert [m["role"] for m in dialogue["messages"]] == ["customer", "ai"] and dialogue["reply_blocked"] == ""

    r = client.post(f"/api/mobile/conversations/{conv_id}/reply", json={"text": "Да, можно. Позвоним вам сегодня."},
                    headers=auth(token))
    assert r.status_code == 200
    after = r.json()
    assert after["messages"][-1] == {**after["messages"][-1], "role": "staff", "author": "Владелец"}
    assert after["ai_paused"] is True  # the AI stays out of this chat, as after a reply from the panel
    assert after["takeover_minutes"] == 720 and after["ai_paused_until"].endswith("Z")
    assert rt.tg.sent[-1][:2] == ("5551", "Да, можно. Позвоним вам сегодня.")
    assert client.get("/api/mobile/leads", headers=auth(token)).json()["leads"][0]["status"] == "done"
    with db.new_session() as s:
        from joop.models import Conversation

        assert s.get(Conversation, conv_id).reviewed_at is not None


def test_whatsapp_after_a_day_cannot_be_answered_and_says_why(client, business):
    conv_id = _handed_off("whatsapp", "996700000001", last_customer_hours_ago=30)
    token = sign_in(client).json()["token"]
    dialogue = client.get(f"/api/mobile/conversations/{conv_id}", headers=auth(token)).json()
    assert "в течение суток" in dialogue["reply_blocked"]
    r = client.post(f"/api/mobile/conversations/{conv_id}/reply", json={"text": "Здравствуйте"}, headers=auth(token))
    assert r.status_code == 422 and "в течение суток" in r.json()["error"]
    assert client.post(f"/api/mobile/conversations/{conv_id}/reply", json={"text": "  "}, headers=auth(token)).status_code == 422


def test_a_master_or_another_business_cannot_read_or_answer(client, business):
    from joop.presets import create_business

    from .conftest import NOW_UTC

    conv_id = _handed_off("telegram", "5552", last_customer_hours_ago=1)
    with db.new_session() as s:
        create_business(s, slug="other", name="Другая", password="other-pass-1", demo=True, now_utc=NOW_UTC)
        member = s.exec(select(Staff).where(Staff.business_id == business.id)).first()
        s.add(PanelUser(business_id=business.id, name="Айгерим", login="aigerim", password_hash=hash_password("staff-pass-1"),
                        staff_id=member.id))
        s.commit()
    stranger = sign_in(client, company="other", password="other-pass-1").json()["token"]
    master = sign_in(client, user="aigerim", password="staff-pass-1").json()["token"]
    assert client.get(f"/api/mobile/conversations/{conv_id}", headers=auth(stranger)).status_code == 404
    assert client.post(f"/api/mobile/conversations/{conv_id}/reply", json={"text": "x"}, headers=auth(stranger)).status_code == 404
    assert client.get(f"/api/mobile/conversations/{conv_id}", headers=auth(master)).status_code == 403


# --- a booking made by staff from the app ---------------------------------------------------------------


def test_the_owner_books_a_phoned_customer_into_a_free_time(client, business):
    token = sign_in(client).json()["token"]
    free = client.get("/api/mobile/slots", params={"day": "2026-11-05"}, headers=auth(token)).json()
    assert free["day"] == "2026-11-05" and free["slots"]
    first = free["slots"][0]
    r = client.post("/api/mobile/bookings", json={"slot_id": first["id"], "name": "Нурлан", "phone": "0555 123 456",
                                                  "service": "Консультация"}, headers=auth(token))
    assert r.status_code == 200, r.text
    made = r.json()["booking"]
    assert made["customer"] == {"name": "Нурлан", "phone": "+996555123456"} and made["source"] == "staff"
    assert made["start_local"] == first["start_local"] and made["staff"] == first["staff"] and made["channel"] == ""
    again = client.get("/api/mobile/slots", params={"day": "2026-11-05"}, headers=auth(token)).json()["slots"]
    assert first["id"] not in [x["id"] for x in again]  # the time is taken, as when the AI books it
    r = client.post("/api/mobile/bookings", json={"slot_id": first["id"], "name": "Бакыт"}, headers=auth(token))
    assert r.status_code == 409 and "занято" in r.json()["error"]
    day = client.get("/api/mobile/bookings", params={"day": "2026-11-05"}, headers=auth(token)).json()["bookings"]
    assert [x["customer"]["name"] for x in day] == ["Нурлан"]
    with db.new_session() as s:  # the AI's figures count only what the AI booked
        assert activity(s, business.id, datetime(2026, 1, 1))["bookings"] == 0


def test_a_staff_booking_needs_a_name_and_a_real_phone_and_a_future_time(client, business):
    token = sign_in(client).json()["token"]
    slot = tomorrow_slots(business.id)[0]
    post = lambda body: client.post("/api/mobile/bookings", json={"slot_id": slot.id, **body}, headers=auth(token))  # noqa: E731
    assert post({"name": "  "}).status_code == 422
    assert post({"name": "Нурлан", "phone": "12"}).json()["error"].startswith("Телефон")
    assert post({"name": "Нурлан"}).status_code == 200  # a walk-in without a phone is fine
    past = client.get("/api/mobile/slots", params={"day": "2026-11-04"}, headers=auth(token)).json()["slots"]
    assert all(x["start_local"] > "2026-11-04T23:14" for x in past)  # NOW is 23:14 Bishkek: nothing earlier is offered


def test_a_master_books_only_into_her_own_times_and_another_business_into_none(client, business):
    slots = tomorrow_slots(business.id)
    mine = slots[0]
    other = next(x for x in slots if x.staff_id != mine.staff_id)
    with db.new_session() as s:
        s.add(PanelUser(business_id=business.id, name="Айгерим", login="aigerim", password_hash=hash_password("staff-pass-1"),
                        staff_id=mine.staff_id))
        s.add(Business(slug="other", name="Другая", admin_password_hash=hash_password("other-pass-1")))
        s.commit()
    token = sign_in(client, user="aigerim", password="staff-pass-1").json()["token"]
    offered = client.get("/api/mobile/slots", params={"day": "2026-11-05"}, headers=auth(token)).json()["slots"]
    assert offered and {x["staff_id"] for x in offered} == {mine.staff_id}
    assert client.post("/api/mobile/bookings", json={"slot_id": other.id, "name": "Нурлан"}, headers=auth(token)).status_code == 404
    stranger = sign_in(client, company="other", password="other-pass-1").json()["token"]
    assert client.post("/api/mobile/bookings", json={"slot_id": mine.id, "name": "Нурлан"}, headers=auth(stranger)).status_code == 404
    assert client.get("/api/mobile/slots", params={"day": "2026-11-05"}, headers=auth(stranger)).json()["slots"] == []


def test_a_staff_booking_goes_to_altegio_too(client, business, rt):
    from .test_altegio import FakeAltegio, make_client

    from .conftest import NOW_UTC
    from joop.timeutil import utc_to_local

    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.altegio_location_id = 4242
        member = s.get(Staff, tomorrow_slots(business.id)[0].staff_id)
        member.external_id = "7"
        s.add(b)
        s.add(member)
        s.commit()
        slot_id = tomorrow_slots(business.id)[0].id
    fake = FakeAltegio(utc_to_local(NOW_UTC, "Asia/Bishkek"))
    rt.altegio = lambda _b: make_client(fake)
    token = sign_in(client).json()["token"]
    assert client.post("/api/mobile/bookings", json={"slot_id": slot_id, "name": "Нурлан"}, headers=auth(token)).status_code == 422
    fake.record_status = 502
    r = client.post("/api/mobile/bookings", json={"slot_id": slot_id, "name": "Нурлан", "phone": "0555123456"}, headers=auth(token))
    assert r.status_code == 502
    with db.new_session() as s:
        assert s.get(Slot, slot_id).status == "free"  # Altegio was down: the time is free again
    fake.record_status = 201
    r = client.post("/api/mobile/bookings", json={"slot_id": slot_id, "name": "Нурлан", "phone": "0555123456"}, headers=auth(token))
    assert r.status_code == 200 and fake.paths("POST")[-1] == "book_record/4242"
    with db.new_session() as s:
        assert s.exec(select(Booking).where(Booking.slot_id == slot_id)).one().external_id == "987654"


# --- payment after the visit ----------------------------------------------------------------------------


def test_the_owner_records_a_payment_and_sees_the_days_takings(client, business):
    slot = tomorrow_slots(business.id)[0]
    paid_id, unpaid_id = book(business.id, slot), book(business.id, tomorrow_slots(business.id)[0], name="Бакыт")
    token = sign_in(client).json()["token"]
    assert sign_in(client).json()["sections"]["cash"] is True  # a clinic has the panel's Касса
    rows = client.get("/api/mobile/bookings", params={"day": "2026-11-05"}, headers=auth(token)).json()["bookings"]
    with db.new_session() as s:
        expected = cash.suggested(s, s.get(Booking, paid_id))
    assert rows[0]["suggested_som"] == expected
    r = client.post(f"/api/mobile/bookings/{paid_id}/pay", json={"amount": 1500, "method": "card"}, headers=auth(token))
    assert r.status_code == 200
    made = r.json()["booking"]
    assert made["paid"]["som"] == 1500 and made["paid"]["method"] == "card" and made["suggested_som"] == 0
    day = client.get("/api/mobile/cash", params={"day": "2026-11-05"}, headers=auth(token)).json()
    assert day["total"] == 1500 and day["by_method"] == {"card": 1500} and day["visits"] == 2
    assert day["unpaid"] == []  # tomorrow's visits have not passed yet: nothing to ask about
    assert day["month"] == {"total": 1500, "paid_visits": 1}
    assert client.post(f"/api/mobile/bookings/{paid_id}/pay", json={"amount": 0}, headers=auth(token)).status_code == 200
    assert client.get("/api/mobile/cash", params={"day": "2026-11-05"}, headers=auth(token)).json()["total"] == 0
    assert unpaid_id


def test_a_payment_is_checked_and_stays_within_the_business_and_the_master(client, business):
    slots = tomorrow_slots(business.id)
    mine = slots[0]
    other = next(x for x in slots if x.staff_id != mine.staff_id)
    hers, theirs = book(business.id, mine), book(business.id, other, name="Бакыт")
    token = sign_in(client).json()["token"]
    pay = lambda bid, body, t=token: client.post(f"/api/mobile/bookings/{bid}/pay", json=body, headers=auth(t))  # noqa: E731
    assert pay(hers, {"amount": 100, "method": "crypto"}).status_code == 422
    assert pay(hers, {"amount": -5}).status_code == 422
    assert pay(hers, {"amount": 10_000_001}).status_code == 422
    client.post(f"/api/mobile/bookings/{theirs}/cancel", headers=auth(token))
    assert pay(theirs, {"amount": 100}).status_code == 409
    with db.new_session() as s:
        s.add(PanelUser(business_id=business.id, name="Айгерим", login="aigerim", password_hash=hash_password("staff-pass-1"),
                        staff_id=mine.staff_id))
        s.add(Business(slug="other", name="Другая", admin_password_hash=hash_password("other-pass-1")))
        s.commit()
    master = sign_in(client, user="aigerim", password="staff-pass-1").json()["token"]
    assert pay(theirs, {"amount": 100}, master).status_code == 404
    assert pay(hers, {"amount": 700}, master).status_code == 200
    stranger = sign_in(client, company="other", password="other-pass-1").json()["token"]
    assert pay(hers, {"amount": 1}, stranger).status_code == 404
    assert client.get("/api/mobile/cash", params={"day": "2026-11-05"}, headers=auth(master)).json()["total"] == 700


def test_a_visit_that_passed_without_a_payment_is_listed(client, business):
    with db.new_session() as s:
        member = s.exec(select(Staff).where(Staff.business_id == business.id)).first()
        s.add(Booking(business_id=business.id, staff_id=member.id, staff_name=member.name, start=datetime(2026, 11, 4, 10),
                      service="Консультация", customer_name="Нурлан", channel=""))
        s.commit()
    token = sign_in(client).json()["token"]
    day = client.get("/api/mobile/cash", params={"day": "2026-11-04"}, headers=auth(token)).json()
    assert [x["customer"]["name"] for x in day["unpaid"]] == ["Нурлан"]


# --- the stop list ----------------------------------------------------------------------------------------


def _first_service(business_id):
    with db.new_session() as s:
        return s.exec(select(Service).where(Service.business_id == business_id).order_by(Service.id)).first()


def test_the_owner_puts_an_item_on_the_stop_list_and_back(client, business):
    item = _first_service(business.id)
    token = sign_in(client).json()["token"]
    stop = lambda on: client.post(f"/api/mobile/services/{item.id}/available", json={"available": on}, headers=auth(token))  # noqa: E731
    r = stop(False)
    assert r.status_code == 200 and r.json()["service"]["available"] is False
    with db.new_session() as s:
        assert s.get(Service, item.id).available is False  # the AI no longer offers it
    listed = {x["id"]: x for x in client.get("/api/mobile/services", headers=auth(token)).json()["services"]}
    assert listed[item.id]["available"] is False and listed[item.id]["sold_out"] is False
    assert stop(True).json()["service"]["available"] is True


def test_sold_out_or_altegio_items_are_not_switched_from_the_app(client, business):
    item = _first_service(business.id)
    with db.new_session() as s:
        row = s.get(Service, item.id)
        row.stock, row.available, row.sold_out = 0, False, True
        s.add(row)
        s.commit()
    token = sign_in(client).json()["token"]
    r = client.post(f"/api/mobile/services/{item.id}/available", json={"available": True}, headers=auth(token))
    assert r.status_code == 409 and "Склад" in r.json()["error"]
    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.altegio_location_id = 4242
        s.add(b)
        s.commit()
    r = client.post(f"/api/mobile/services/{item.id}/available", json={"available": False}, headers=auth(token))
    assert r.status_code == 409 and "Altegio" in r.json()["error"]
    assert client.get("/api/mobile/services", headers=auth(token)).json()["services"][0]["from_altegio"] is True


def test_a_master_or_another_business_cannot_change_the_stop_list(client, business):
    item = _first_service(business.id)
    with db.new_session() as s:
        member = s.exec(select(Staff).where(Staff.business_id == business.id)).first()
        s.add(PanelUser(business_id=business.id, name="Айгерим", login="aigerim", password_hash=hash_password("staff-pass-1"),
                        staff_id=member.id))
        s.add(Business(slug="other", name="Другая", admin_password_hash=hash_password("other-pass-1")))
        s.commit()
    master = sign_in(client, user="aigerim", password="staff-pass-1").json()["token"]
    stranger = sign_in(client, company="other", password="other-pass-1").json()["token"]
    body = {"available": False}
    assert client.post(f"/api/mobile/services/{item.id}/available", json=body, headers=auth(master)).status_code == 403
    assert client.post(f"/api/mobile/services/{item.id}/available", json=body, headers=auth(stranger)).status_code == 404
    with db.new_session() as s:
        assert s.get(Service, item.id).available is True


def test_the_dialogue_names_the_pause_the_owner_chose(client, business):
    conv_id = _handed_off("telegram", "5552", last_customer_hours_ago=1)
    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.takeover_minutes = 15
        s.add(b)
        s.commit()
    token = sign_in(client).json()["token"]
    after = client.post(f"/api/mobile/conversations/{conv_id}/reply", json={"text": "Сейчас уточню."}, headers=auth(token)).json()
    assert after["takeover_minutes"] == 15
    until = datetime.fromisoformat(after["ai_paused_until"].rstrip("Z"))
    with db.new_session() as s:
        from joop.models import Conversation

        assert s.get(Conversation, conv_id).ai_paused_until == until


# --- the customer card -----------------------------------------------------------------------------------


def test_a_booking_opens_the_customers_card_with_history_and_a_note(client, business):
    slots = tomorrow_slots(business.id)
    first = book(business.id, slots[0])
    with db.new_session() as s:  # an earlier visit of the same phone, paid
        member = s.exec(select(Staff).where(Staff.business_id == business.id)).first()
        s.add(Booking(business_id=business.id, staff_id=member.id, staff_name=member.name, start=datetime(2026, 10, 1, 10),
                      service="Консультация", customer_name="Айгуль", customer_phone="0700 000 001", channel="",
                      paid_som=900, paid_method="cash"))
        s.commit()
    token = sign_in(client).json()["token"]
    row = client.get("/api/mobile/bookings", params={"day": "2026-11-05"}, headers=auth(token)).json()["bookings"][0]
    assert row["id"] == first and row["customer_key"] == "700000001"
    card = client.get("/api/mobile/customers/700000001", headers=auth(token)).json()["customer"]
    assert card["name"] == "Айгуль" and card["visits"] == 1 and card["spend_som"] >= 900
    assert card["upcoming"]["id"] == first and [b["id"] for b in card["bookings"]][0] == first
    r = client.post("/api/mobile/customers/700000001", json={"note": "Боится уколов", "tags": "VIP, VIP, постоянный"},
                    headers=auth(token))
    assert r.json() == {"note": "Боится уколов", "tags": ["VIP", "постоянный"]}
    again = client.get("/api/mobile/customers/700000001", headers=auth(token)).json()["customer"]
    assert again["note"] == "Боится уколов" and again["tags"] == ["VIP", "постоянный"]
    assert client.get("/api/mobile/customers/700999999", headers=auth(token)).status_code == 404


def test_a_master_sees_only_her_visits_of_a_customer_and_another_business_nothing(client, business):
    slots = tomorrow_slots(business.id)
    mine = slots[0]
    other = next(x for x in slots if x.staff_id != mine.staff_id)
    book(business.id, other)  # the customer came to another doctor only
    with db.new_session() as s:
        s.add(PanelUser(business_id=business.id, name="Айгерим", login="aigerim", password_hash=hash_password("staff-pass-1"),
                        staff_id=mine.staff_id))
        s.add(Business(slug="other", name="Другая", admin_password_hash=hash_password("other-pass-1")))
        s.commit()
    master = sign_in(client, user="aigerim", password="staff-pass-1").json()["token"]
    assert client.get("/api/mobile/customers/700000001", headers=auth(master)).status_code == 404
    assert client.post("/api/mobile/customers/700000001", json={"note": "x"}, headers=auth(master)).status_code == 404
    hers = book(business.id, mine)
    card = client.get("/api/mobile/customers/700000001", headers=auth(master)).json()["customer"]
    assert [b["id"] for b in card["bookings"]] == [hers] and card["orders"] == []
    stranger = sign_in(client, company="other", password="other-pass-1").json()["token"]
    assert client.get("/api/mobile/customers/700000001", headers=auth(stranger)).status_code == 404


# --- the chats list --------------------------------------------------------------------------------------


def test_the_owner_sees_the_latest_real_chats_and_finds_one(client, business):
    from joop.models import Conversation

    older = _handed_off("telegram", "6001", last_customer_hours_ago=5)
    newer = _handed_off("whatsapp", "996555123456", last_customer_hours_ago=1)
    with db.new_session() as s:
        b = s.get(Business, business.id)
        a, z = s.get(Conversation, older), s.get(Conversation, newer)
        a.last_message_at, z.last_message_at = datetime(2026, 11, 4, 10), datetime(2026, 11, 4, 15)
        z.customer_name, z.customer_phone = "Бакыт", "+996555123456"
        s.add(Conversation(business_id=b.id, channel="telegram", chat_id="7", customer_name="Сотрудник", staff_test=True))
        s.add_all([a, z])
        s.commit()
    token = sign_in(client).json()["token"]
    rows = client.get("/api/mobile/conversations", headers=auth(token)).json()["conversations"]
    assert [r["id"] for r in rows] == [newer, older]  # newest first; the staff's own test chat left out
    assert rows[0]["last"] == {"role": "ai", "text": "Передаю вопрос администратору."}
    assert rows[0]["customer"] == {"name": "Бакыт", "phone": "+996555123456"} and rows[0]["ai_paused"] is False
    found = client.get("/api/mobile/conversations", params={"q": "0555 123"}, headers=auth(token)).json()["conversations"]
    assert [r["id"] for r in found] == [newer]
    found = client.get("/api/mobile/conversations", params={"q": "айгуль"}, headers=auth(token)).json()["conversations"]
    assert [r["id"] for r in found] == [older]


def test_a_master_or_another_business_does_not_see_the_chats(client, business):
    _handed_off("telegram", "6002", last_customer_hours_ago=1)
    with db.new_session() as s:
        member = s.exec(select(Staff).where(Staff.business_id == business.id)).first()
        s.add(PanelUser(business_id=business.id, name="Айгерим", login="aigerim", password_hash=hash_password("staff-pass-1"),
                        staff_id=member.id))
        s.add(Business(slug="other", name="Другая", admin_password_hash=hash_password("other-pass-1")))
        s.commit()
    master = sign_in(client, user="aigerim", password="staff-pass-1").json()["token"]
    assert client.get("/api/mobile/conversations", headers=auth(master)).status_code == 403
    stranger = sign_in(client, company="other", password="other-pass-1").json()["token"]
    assert client.get("/api/mobile/conversations", headers=auth(stranger)).json()["conversations"] == []


def test_staff_switch_the_ai_off_in_a_chat_and_back_on(client, business):
    from joop.models import Conversation

    from .conftest import NOW_UTC

    conv_id = _handed_off("telegram", "6003", last_customer_hours_ago=1)
    token = sign_in(client).json()["token"]
    off = client.post(f"/api/mobile/conversations/{conv_id}/ai", json={"on": False}, headers=auth(token)).json()
    assert off["ai_paused"] is True
    with db.new_session() as s:
        assert s.get(Conversation, conv_id).ai_paused_until == NOW_UTC.replace(tzinfo=None) + timedelta(hours=24)
    week = client.post(f"/api/mobile/conversations/{conv_id}/ai", json={"on": False, "hours": 10_000}, headers=auth(token))
    with db.new_session() as s:  # capped at 30 days, as the panel
        assert s.get(Conversation, conv_id).ai_paused_until == NOW_UTC.replace(tzinfo=None) + timedelta(days=30)
    assert week.status_code == 200
    on = client.post(f"/api/mobile/conversations/{conv_id}/ai", json={"on": True}, headers=auth(token)).json()
    assert on["ai_paused"] is False and on["ai_paused_until"] is None
    with db.new_session() as s:
        member = s.exec(select(Staff).where(Staff.business_id == business.id)).first()
        s.add(PanelUser(business_id=business.id, name="Айгерим", login="aigerim", password_hash=hash_password("staff-pass-1"),
                        staff_id=member.id))
        s.commit()
    master = sign_in(client, user="aigerim", password="staff-pass-1").json()["token"]
    assert client.post(f"/api/mobile/conversations/{conv_id}/ai", json={"on": False}, headers=auth(master)).status_code == 403


# --- what the AI did -------------------------------------------------------------------------------------


def test_the_owner_sees_what_the_ai_did_in_two_weeks(client, business):
    from joop.models import Conversation, Message

    from .conftest import NOW_UTC

    slot = tomorrow_slots(business.id)[0]
    with db.new_session() as s:
        conv = Conversation(business_id=business.id, channel="telegram", chat_id="8001", customer_name="Нурлан")
        s.add(conv)
        s.flush()
        s.add(Message(business_id=business.id, conversation_id=conv.id, role="customer", text="Можно записаться?",
                      created_at=NOW_UTC.replace(tzinfo=None) - timedelta(days=1), off_hours=True))
        s.add(Message(business_id=business.id, conversation_id=conv.id, role="customer", text="Давно",
                      created_at=NOW_UTC.replace(tzinfo=None) - timedelta(days=20)))
        member = s.get(Staff, slot.staff_id)
        s.add(Booking(business_id=business.id, staff_id=member.id, staff_name=member.name, start=slot.start, source="ai",
                      customer_name="Нурлан", channel="telegram", conversation_id=conv.id,
                      created_at=NOW_UTC.replace(tzinfo=None) - timedelta(days=1)))
        s.add(Booking(business_id=business.id, staff_id=member.id, staff_name=member.name, start=slot.start, source="staff",
                      customer_name="Бакыт", channel="", created_at=NOW_UTC.replace(tzinfo=None) - timedelta(days=1)))
        s.commit()
    token = sign_in(client).json()["token"]
    r = client.get("/api/mobile/ai-results", headers=auth(token)).json()
    assert r["days"] == 14
    f = r["figures"]
    assert f["conversations"] == 1 and f["off_hours_conversations"] == 1
    assert f["bookings"] == 1  # the staff's own booking is not the AI's
    assert "orders" not in f  # a clinic takes no orders
    with db.new_session() as s:
        member = s.exec(select(Staff).where(Staff.business_id == business.id)).first()
        s.add(PanelUser(business_id=business.id, name="Айгерим", login="aigerim", password_hash=hash_password("staff-pass-1"),
                        staff_id=member.id))
        s.commit()
    master = sign_in(client, user="aigerim", password="staff-pass-1").json()["token"]
    assert client.get("/api/mobile/ai-results", headers=auth(master)).status_code == 403


# --- moving a booking ------------------------------------------------------------------------------------


def _chat_booking(business_id, slot: Slot) -> int:
    """A booking the AI made in a Telegram chat, reminded and confirmed."""
    from joop.models import Conversation

    with db.new_session() as s:
        conv = Conversation(business_id=business_id, channel="telegram", chat_id="9001", customer_name="Айгуль")
        s.add(conv)
        s.flush()
        slot = s.get(Slot, slot.id)
        member = s.get(Staff, slot.staff_id)
        slot.taken, slot.status = 1, "booked"
        row = Booking(business_id=business_id, slot_id=slot.id, staff_id=member.id, staff_name=member.name, start=slot.start,
                      service="Консультация", customer_name="Айгуль", channel="telegram", chat_id="9001",
                      conversation_id=conv.id, reminder_status="sent", confirmed_at=datetime(2026, 11, 4, 12))
        s.add_all([slot, row])
        s.commit()
        return row.id


def test_the_owner_moves_a_booking_and_the_customer_is_told(client, business, rt):
    slots = tomorrow_slots(business.id)
    old, new = slots[0], slots[3]
    booking_id = _chat_booking(business.id, old)
    token = sign_in(client).json()["token"]
    r = client.post(f"/api/mobile/bookings/{booking_id}/move", json={"slot_id": new.id}, headers=auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["told"] is True and r.json()["booking"]["start_local"] == new.start.isoformat(timespec="seconds")
    assert r.json()["booking"]["movable"] is True
    assert rt.tg.sent[-1][0] == "9001" and "перенесена" in rt.tg.sent[-1][1]
    with db.new_session() as s:
        moved = s.get(Booking, booking_id)
        assert (moved.slot_id, moved.status, moved.reminder_status, moved.confirmed_at) == (new.id, "booked", "", None)
        assert s.get(Slot, old.id).status == "free" and s.get(Slot, new.id).status == "booked"
    again = client.post(f"/api/mobile/bookings/{booking_id}/move", json={"slot_id": new.id}, headers=auth(token))
    assert again.status_code == 409


def test_a_move_is_refused_for_a_taken_time_altegio_a_cancelled_booking_or_a_stranger(client, business):
    slots = tomorrow_slots(business.id)
    booking_id, other = _chat_booking(business.id, slots[0]), book(business.id, slots[1], name="Бакыт")
    token = sign_in(client).json()["token"]
    move = lambda bid, sid, t=token: client.post(f"/api/mobile/bookings/{bid}/move", json={"slot_id": sid}, headers=auth(t))  # noqa: E731
    assert "занято" in move(booking_id, slots[1].id).json()["error"]
    with db.new_session() as s:
        row = s.get(Booking, other)
        row.external_id = "123"
        s.add(row)
        s.commit()
    assert "Altegio" in move(other, slots[4].id).json()["error"]
    client.post(f"/api/mobile/bookings/{booking_id}/cancel", headers=auth(token))
    assert move(booking_id, slots[4].id).status_code == 409
    with db.new_session() as s:
        s.add(Business(slug="other", name="Другая", admin_password_hash=hash_password("other-pass-1")))
        s.commit()
    stranger = sign_in(client, company="other", password="other-pass-1").json()["token"]
    assert move(other, slots[4].id, stranger).status_code == 404
    with db.new_session() as s:
        assert s.get(Slot, slots[4].id).status == "free"


def test_a_paid_visit_is_not_movable_in_the_app(client, business):
    slots = tomorrow_slots(business.id)
    booking_id = book(business.id, slots[0])
    token = sign_in(client).json()["token"]
    client.post(f"/api/mobile/bookings/{booking_id}/pay", json={"amount": 1500, "method": "cash"}, headers=auth(token))
    row = client.get("/api/mobile/bookings", params={"day": "2026-11-05"}, headers=auth(token)).json()["bookings"][0]
    assert row["movable"] is False
    r = client.post(f"/api/mobile/bookings/{booking_id}/move", json={"slot_id": slots[3].id}, headers=auth(token))
    assert r.status_code == 409 and "оплата" in r.json()["error"]
    with db.new_session() as s:
        assert s.get(Booking, booking_id).slot_id == slots[0].id and s.get(Slot, slots[3].id).status == "free"


# --- the customers list ----------------------------------------------------------------------------------


def test_the_owner_finds_a_customer_by_name_phone_or_tag(client, business):
    slots = tomorrow_slots(business.id)
    book(business.id, slots[0], name="Айгуль")  # +996700000001
    with db.new_session() as s:
        member = s.exec(select(Staff).where(Staff.business_id == business.id)).first()
        s.add(Booking(business_id=business.id, staff_id=member.id, staff_name=member.name, start=datetime(2026, 10, 1, 10),
                      service="Консультация", customer_name="Бакыт", customer_phone="+996555123456", channel=""))
        s.commit()
    token = sign_in(client).json()["token"]
    client.post("/api/mobile/customers/555123456", json={"note": "", "tags": "VIP"}, headers=auth(token))
    everyone = client.get("/api/mobile/customers", headers=auth(token)).json()
    assert {c["name"] for c in everyone["customers"]} >= {"Айгуль", "Бакыт"} and everyone["tags"] == ["VIP"]
    found = client.get("/api/mobile/customers", params={"q": "0555 123"}, headers=auth(token)).json()
    assert [c["key"] for c in found["customers"]] == ["555123456"] and found["total"] == 1
    assert found["tags"] == ["VIP"]  # the tags of everyone, to filter by, not only of those found
    assert [c["name"] for c in client.get("/api/mobile/customers", params={"q": "айгуль"}, headers=auth(token)).json()["customers"]] == ["Айгуль"]
    assert [c["name"] for c in client.get("/api/mobile/customers", params={"tag": "VIP"}, headers=auth(token)).json()["customers"]] == ["Бакыт"]


def test_a_master_lists_only_her_customers_and_another_business_none(client, business):
    slots = tomorrow_slots(business.id)
    mine = slots[0]
    other = next(x for x in slots if x.staff_id != mine.staff_id)
    book(business.id, mine, name="Айгуль")
    with db.new_session() as s:
        member = s.get(Staff, other.staff_id)
        s.add(Booking(business_id=business.id, staff_id=member.id, staff_name=member.name, start=other.start,
                      customer_name="Бакыт", customer_phone="+996555123456", channel=""))
        s.add(PanelUser(business_id=business.id, name="Айгерим", login="aigerim", password_hash=hash_password("staff-pass-1"),
                        staff_id=mine.staff_id))
        s.add(Business(slug="other", name="Другая", admin_password_hash=hash_password("other-pass-1")))
        s.commit()
    master = sign_in(client, user="aigerim", password="staff-pass-1").json()["token"]
    assert [c["name"] for c in client.get("/api/mobile/customers", headers=auth(master)).json()["customers"]] == ["Айгуль"]
    stranger = sign_in(client, company="other", password="other-pass-1").json()["token"]
    assert client.get("/api/mobile/customers", headers=auth(stranger)).json() == {"customers": [], "total": 0, "tags": []}


def test_the_dialogue_carries_the_ready_answers_filled_for_this_customer(client, business):
    from joop import quick_replies

    conv_id = _handed_off("telegram", "5553", last_customer_hours_ago=1)
    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.address = "ул. Киевская, 10"
        s.add(b)
        quick_replies.add(s, b, "Адрес", "{имя}, мы находимся по адресу: {адрес}. Ждём вас в {компания}!")
        s.commit()
    token = sign_in(client).json()["token"]
    ready = client.get(f"/api/mobile/conversations/{conv_id}", headers=auth(token)).json()["quick_replies"]
    assert [x["title"] for x in ready] == ["Адрес"]
    assert ready[0]["text"] == "Айгуль, мы находимся по адресу: ул. Киевская, 10. Ждём вас в Ак-Тиш Дент!"
