"""Rooms, cars and halls from the owner's app: a hotel, a car rental or a banquet hall launched from the phone
replaces the sign-up example with its own (the launch list's «Номера» step), as on the panel's page. Until then the
AI books nothing for real guests: the example's rooms are hidden from them."""

from fastapi.testclient import TestClient
from sqlmodel import select

from joop import db
from joop.agent.llm import AgentReply
from joop.models import Staff, Stay
from joop.web.app import create_app

from .test_mobile import auth

HOTEL = {"name": "Отель Ала-Арча", "niche": "hotel", "phone": "0555 333 444", "password": "hotel-pass-2026", "contact_name": "Жамиля"}


def _step(c, h):
    return next(x for x in c.get("/api/mobile/setup", headers=h).json()["steps"] if x["key"] == "rooms")


def test_a_hotel_from_the_phone_puts_in_its_own_rooms_and_a_guest_books_one(engine, settings, rt, llm):
    with TestClient(create_app(settings, rt, init=False)) as c:
        h = auth(c.post("/api/mobile/signup", json=HOTEL).json()["token"])
        assert c.get("/api/mobile/me", headers=h).json()["people_label"] == "Номера"
        info = c.get("/api/mobile/staff", headers=h).json()
        assert (info["units"], info["stay_kind"], info["capacity"], info["booking"]) == (True, "room", True, False)
        assert all(x["example"] for x in info["staff"]) and _step(c, h)["done"] is False
        assert c.post("/api/mobile/staff/example/delete", headers=h).json()["removed"] == 3
        r = c.post("/api/mobile/staff", headers=h, json={"name": "Стандарт", "role": "номер на двоих", "capacity": 2,
                                                          "group_size": 0})
        assert r.status_code == 200, r.text
        room = r.json()["staff"][0]
        assert (room["name"], room["capacity"], room["group_size"], room["example"]) == ("Стандарт", 2, 1, False)  # at least one
        r = c.post(f"/api/mobile/staff/{room['id']}", headers=h, json={"name": "Стандарт", "role": "номер на двоих",
                                                                        "capacity": 2, "group_size": 5})
        assert r.json()["staff"][0]["group_size"] == 5
        assert _step(c, h)["done"] is True
        assert c.post(f"/api/mobile/staff/{room['id']}/windows", headers=h, json={}).status_code == 409  # no times here

        free = c.get("/api/mobile/stays/rooms", headers=h, params={"check_in": "2026-11-20", "check_out": "2026-11-22"}).json()
        assert [(x["name"], x["free"]) for x in free["rooms"]] == [("Стандарт", 5)]
        c.cookies.clear()
        llm.replies.append(AgentReply("Забронировала Стандарт на 20–22 ноября, администратор свяжется насчёт оплаты.",
                                      stay={"room_id": room["id"], "check_in": "2026-11-20", "check_out": "2026-11-22",
                                            "guests": 2, "name": "Асель", "phone": "0700 123 456"}))
        c.post("/c/otel-ala-archa/chat", json={"text": "Стандарт 20-22 ноября на двоих, Асель 0700 123 456", "visitor": "e" * 24})
        system = llm.calls[-1]["system"]  # the AI offers the hotel's own room, not the example's
        assert f"- [{room['id']}] Стандарт, до 2 гостей, номеров такого типа: 5" in system and "Стандартный номер" not in system
        stays = c.get("/api/mobile/stays", headers=h).json()["stays"]
        assert [(x["room"], x["check_in"], x["guests"]) for x in stays] == [("Стандарт", "2026-11-20", 2)]
    with db.new_session() as s:
        assert s.exec(select(Stay)).one().customer_name == "Асель"


def test_a_hall_is_one_and_a_car_has_no_guests(engine, settings, rt):
    with TestClient(create_app(settings, rt, init=False)) as c:
        h = auth(c.post("/api/mobile/signup", json={**HOTEL, "name": "Банкетный зал Той", "niche": "banquet"}).json()["token"])
        info = c.get("/api/mobile/staff", headers=h).json()
        assert (info["units"], info["stay_kind"], info["capacity"]) == (False, "hall", True)
        r = c.post("/api/mobile/staff", headers=h, json={"name": "Зал Той", "capacity": 150, "group_size": 4}).json()
        assert [(x["capacity"], x["group_size"]) for x in r["staff"] if x["name"] == "Зал Той"] == [(150, 0)]
        h = auth(c.post("/api/mobile/signup", json={**HOTEL, "name": "Прокат Авто", "niche": "carrental",
                                                     "phone": "0555 333 445"}).json()["token"])
        info = c.get("/api/mobile/staff", headers=h).json()
        assert (info["units"], info["stay_kind"], info["capacity"]) == (True, "car", False)
    with db.new_session() as s:
        assert s.exec(select(Staff).where(Staff.name == "Зал Той")).one().group_size == 0
