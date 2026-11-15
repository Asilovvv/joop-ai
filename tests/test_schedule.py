"""Closing and opening times by hand (joop/schedule.py): an ill doctor's day, from the panel and from the app."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlmodel import select

from joop import db
from joop.models import Booking, Business, Conversation, PanelUser, Slot, Staff, WaitlistEntry
from joop.slots import CLOSED, claim_slot, free_slots, release_slot, resize_group
from joop.security import hash_password
from joop.timeutil import utc_to_local
from joop.web.app import _login_fails, create_app

from .conftest import NOW_UTC
from .test_mobile import TOMORROW, _chat_booking, auth, book, sign_in, tomorrow_slots
from .test_web import client, login  # noqa: F401  (fixture)

LOCAL = utc_to_local(NOW_UTC, "Asia/Bishkek")


def _doctor_day(business_id):
    """The first doctor's free times tomorrow, and the doctor."""
    slots = tomorrow_slots(business_id)
    staff_id = slots[0].staff_id
    return [x for x in slots if x.staff_id == staff_id], staff_id


def _waiting(business_id, chat="w1"):
    with db.new_session() as s:
        conv = Conversation(business_id=business_id, channel="telegram", chat_id=chat, customer_name="Айбек")
        s.add(conv)
        s.flush()
        s.add(WaitlistEntry(business_id=business_id, conversation_id=conv.id, customer_name="Айбек", channel="telegram",
                            chat_id=chat, day=TOMORROW.date(), service="чистка"))
        s.commit()


def _states(staff_id, day=TOMORROW):
    with db.new_session() as s:
        return [x.status for x in s.exec(select(Slot).where(Slot.staff_id == staff_id, Slot.start >= day,
                                                              Slot.start < day + timedelta(days=1)).order_by(Slot.start)).all()]


def test_an_ill_doctors_day_stays_closed_after_her_patients_are_moved_and_cancelled(client, business, rt):  # noqa: F811
    day, doctor = _doctor_day(business.id)
    moved_away, cancelled = _chat_booking(business.id, day[0]), book(business.id, day[1], name="Бакыт")
    token = login(client)
    r = client.post("/panel/slots/day", data={"csrf": token, "staff_id": doctor, "day": TOMORROW.date().isoformat(), "action": "close"})
    assert "ИИ не будет записывать на этот день" in r.text
    assert f"{day[0].start:%H:%M} Айгуль" in r.text and f"{day[1].start:%H:%M} Бакыт" in r.text  # to move or cancel
    assert set(_states(doctor)) == {CLOSED}
    with db.new_session() as s:
        offered = {slot.staff_id for slot, _ in free_slots(s, business.id, LOCAL, days=2) if slot.start.date() == TOMORROW.date()}
        assert doctor not in offered and offered  # the AI does not see her day, and still sees the others'
        assert claim_slot(s, day[2].id) is False

    _waiting(business.id)
    other = next(x for x in tomorrow_slots(business.id) if x.staff_id != doctor)
    client.post(f"/panel/bookings/{moved_away}/move", data={"csrf": token, "slot_id": other.id})
    client.post(f"/panel/bookings/{cancelled}/cancel", data={"csrf": token})
    assert set(_states(doctor)) == {CLOSED}  # freed times of a closed day stay closed
    assert not any(chat == "w1" for chat, *_ in rt.tg.sent)  # nobody waiting is offered the ill doctor's time
    with db.new_session() as s:
        assert s.get(Booking, moved_away).slot_id == other.id and s.get(Booking, cancelled).status == "cancelled"
        assert s.get(Slot, day[0].id).taken == 0

    page = client.get("/panel/slots").text
    assert "закрыто" in page and 'value="open">Открыть день' in page
    r = client.post("/panel/slots/day", data={"csrf": token, "staff_id": doctor, "day": TOMORROW.date().isoformat(), "action": "open"})
    assert "Открыто времени" in r.text and "листа ожидания: 1" in r.text
    assert set(_states(doctor)) == {"free"}
    assert any(chat == "w1" and "освободилось время" in text for chat, text, *_ in rt.tg.sent)


def test_closing_keeps_a_booking_and_opening_gives_its_time_back_taken(client, business):  # noqa: F811
    day, doctor = _doctor_day(business.id)
    kept = book(business.id, day[0])
    token = login(client)
    client.post(f"/panel/slots/{day[0].id}/toggle", data={"csrf": token})  # a booked time: refused, as before
    assert _states(doctor)[0] == "booked"
    client.post("/panel/slots/day", data={"csrf": token, "staff_id": doctor, "day": TOMORROW.date().isoformat(), "action": "close"})
    client.post(f"/panel/slots/{day[0].id}/toggle", data={"csrf": token})  # a closed time with its booking: opened, still taken
    with db.new_session() as s:
        assert s.get(Slot, day[0].id).status == "booked" and s.get(Booking, kept).status == "booked"
        assert s.get(Slot, day[1].id).status == CLOSED
    assert client.post("/panel/slots/day", data={"csrf": token, "staff_id": doctor, "day": "9999-12-31"}).status_code == 400
    assert client.post("/panel/slots/day", data={"csrf": "forged", "staff_id": doctor, "day": "2026-11-05"}).status_code == 403


def test_release_and_group_resize_keep_a_closed_time_closed(business):
    day, doctor = _doctor_day(business.id)
    with db.new_session() as s:
        slot = s.get(Slot, day[0].id)
        slot.status, slot.taken = CLOSED, 1
        s.add(slot)
        s.flush()
        release_slot(s, slot.id)
        s.refresh(slot)
        assert (slot.status, slot.taken) == (CLOSED, 0)
        resize_group(s, doctor, 6, LOCAL)
        s.flush()
        s.refresh(slot)
        assert (slot.status, slot.seats) == (CLOSED, 6)
        s.rollback()


def test_the_app_shows_the_day_and_closes_and_opens_times(business, rt, settings):
    _login_fails.clear()
    day, doctor = _doctor_day(business.id)
    booked = book(business.id, day[0])
    with db.new_session() as s:
        busy = s.get(Slot, day[1].id)
        busy.status = "booked"  # marked busy by staff in the panel, without a booking
        s.add(busy)
        s.commit()
    with TestClient(create_app(settings, rt, init=False)) as c:
        token = sign_in(c).json()["token"]
        r = c.get("/api/mobile/schedule", params={"day": "2026-11-05"}, headers=auth(token)).json()
        mine = next(x for x in r["staff"] if x["id"] == doctor)
        assert [x["state"] for x in mine["slots"]][:3] == ["booked", "busy", "free"] and mine["slots"][0]["customer"] == "Айгуль"
        assert mine["from_altegio"] is False

        closed = c.post("/api/mobile/schedule/day", json={"staff_id": doctor, "day": "2026-11-05", "open": False}, headers=auth(token))
        assert closed.status_code == 200 and closed.json()["changed"] == len(day) - 1  # the busy mark stays as it is
        assert [x["id"] for x in closed.json()["bookings"]] == [booked]
        assert _states(doctor)[1] == "booked" and set(_states(doctor)[:1] + _states(doctor)[2:]) == {CLOSED}
        opened = c.post(f"/api/mobile/schedule/slots/{day[2].id}", json={"open": True}, headers=auth(token)).json()
        assert opened["changed"] == 1 and _states(doctor)[2] == "free"
        c.post("/api/mobile/schedule/day", json={"staff_id": doctor, "day": "2026-11-05", "open": True}, headers=auth(token))
        states = _states(doctor)
        # a time staff marked busy (a phone customer) survives close-and-reopen: it must not become free for the AI
        assert states[0] == "booked" and states[1] == "booked" and CLOSED not in states
        today = c.get("/api/mobile/schedule", headers=auth(token)).json()
        assert today["day"] == "2026-11-04" and all(x["start_local"] > "2026-11-04T23:14" for p in today["staff"] for x in p["slots"])
        assert c.get("/api/mobile/schedule", params={"day": "9999-12-31"}, headers=auth(token)).status_code == 400
    _login_fails.clear()


def test_the_app_refuses_altegio_people_started_times_masters_and_strangers(business, rt, settings):
    _login_fails.clear()
    day, doctor = _doctor_day(business.id)
    with db.new_session() as s:
        s.add(PanelUser(business_id=business.id, name="Айгерим", login="aigerim", password_hash=hash_password("staff-pass-1"),
                        staff_id=doctor))
        s.add(Business(slug="other", name="Другая", admin_password_hash=hash_password("other-pass-1")))
        past = Slot(business_id=business.id, staff_id=doctor, start=LOCAL - timedelta(minutes=30))
        s.add(past)
        s.commit()
        past_id = past.id
    with TestClient(create_app(settings, rt, init=False)) as c:
        token = sign_in(c).json()["token"]
        assert c.post(f"/api/mobile/schedule/slots/{past_id}", json={"open": False}, headers=auth(token)).status_code == 409
        master = sign_in(c, user="aigerim", password="staff-pass-1").json()["token"]
        assert c.get("/api/mobile/schedule", headers=auth(master)).status_code == 403
        assert c.post("/api/mobile/schedule/day", json={"staff_id": doctor, "day": "2026-11-05", "open": False},
                      headers=auth(master)).status_code == 403
        stranger = sign_in(c, company="other", password="other-pass-1").json()["token"]
        assert c.post(f"/api/mobile/schedule/slots/{day[0].id}", json={"open": False}, headers=auth(stranger)).status_code == 404
        assert c.post("/api/mobile/schedule/day", json={"staff_id": doctor, "day": "2026-11-05", "open": False},
                      headers=auth(stranger)).status_code == 404
        with db.new_session() as s:
            b = s.get(Business, business.id)
            b.altegio_location_id = 4242
            member = s.get(Staff, doctor)
            member.external_id = "7"
            s.add_all([b, member])
            s.commit()
        r = c.post("/api/mobile/schedule/day", json={"staff_id": doctor, "day": "2026-11-05", "open": False}, headers=auth(token))
        assert r.status_code == 409 and "Altegio" in r.json()["error"]
        assert next(x for x in c.get("/api/mobile/schedule", params={"day": "2026-11-05"}, headers=auth(token)).json()["staff"]
                    if x["id"] == doctor)["from_altegio"] is True
    assert CLOSED not in _states(doctor)
    _login_fails.clear()
