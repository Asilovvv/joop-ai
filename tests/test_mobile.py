"""The mobile app's JSON API (/api/mobile): sign-in with the panel's credentials, bookings, cancelling, services."""

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from joop import db
from joop.models import Booking, Business, PanelUser, Slot, Staff
from joop.security import hash_password
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
    assert r["sections"] == {"bookings": True, "orders": True, "leads": True}
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
    assert master["sections"] == {"bookings": True, "orders": False, "leads": False}
    assert client.get("/api/mobile/leads", headers=auth(master["token"])).status_code == 403
    assert client.get("/api/mobile/orders", headers=auth(master["token"])).status_code == 403
