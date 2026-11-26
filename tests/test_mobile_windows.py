"""Free times opened from the owner's app: the launch list's «Свободные окна для записи» step in one tap, for a
person of the business's own (not the sign-up example), from tomorrow, by the business's hours, days off skipped."""

from datetime import date, time, timedelta

from fastapi.testclient import TestClient
from sqlmodel import select

from joop import db
from joop.models import Business, Slot, Staff
from joop.web.app import create_app

from .test_mobile import auth, client, sign_in  # noqa: F401 - the client fixture

FORM = {"name": "Салон Айгерим", "niche": "beauty", "phone": "0555 123 456", "password": "aigerim-2026", "contact_name": "Айгерим"}
TOMORROW = date(2026, 11, 5)  # NOW_UTC is Wed 4 Nov 2026 23:14 in Bishkek


def _step(c, h):
    return next(x for x in c.get("/api/mobile/setup", headers=h).json()["steps"] if x["key"] == "slots")


def test_a_new_business_opens_two_weeks_for_its_own_master(engine, settings, rt):
    with TestClient(create_app(settings, rt, init=False)) as c:
        h = auth(c.post("/api/mobile/signup", json=FORM).json()["token"])
        c.post("/api/mobile/staff/example/delete", headers=h)
        c.post("/api/mobile/contacts", headers=h, json={"address": "Бишкек", "phone": "0555 1", "hours_text": "Пн–Сб 10–14",
                                                        "work_start": "10:00", "work_end": "14:00", "days_off": [7]})
        person = c.post("/api/mobile/staff", headers=h, json={"name": "Айгерим", "handles": "маникюр"}).json()["staff"][0]
        assert person["free"] == 0 and _step(c, h)["done"] is False

        r = c.post(f"/api/mobile/staff/{person['id']}/windows", headers=h, json={"days": 14, "step": 60})
        assert r.status_code == 200, r.text
        # 14 days from Thu 5 Nov, two Sundays off -> 12 days x 4 hours (10-11, 11-12, 12-13, 13-14)
        assert r.json()["created"] == 48 and r.json()["staff"][0]["free"] == 48
        assert (r.json()["work_start"], r.json()["work_end"]) == ("10:00", "14:00")
        assert _step(c, h)["done"] is True
        with db.new_session() as s:
            slots = s.exec(select(Slot).where(Slot.staff_id == person["id"]).order_by(Slot.start)).all()
            assert slots[0].start.date() == TOMORROW and slots[0].start.time() == time(10, 0)
            assert slots[-1].start.date() == TOMORROW + timedelta(days=13) and slots[-1].start.time() == time(13, 0)
            assert all(x.start.isoweekday() != 7 for x in slots)
        # once more: the times already there are kept, nothing doubles
        assert c.post(f"/api/mobile/staff/{person['id']}/windows", headers=h, json={"days": 14}).json()["created"] == 0
        # other hours and step for a week: only the new times are added
        r = c.post(f"/api/mobile/staff/{person['id']}/windows", headers=h,
                   json={"days": 7, "step": 30, "start": "15:00", "end": "17:00"})
        assert r.json()["created"] == 6 * 4


def test_the_example_bad_hours_and_others_are_refused(client, business):
    h = auth(sign_in(client).json()["token"])
    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.example_ok = False  # the fixture's people become the sign-up example again
        s.add(b)
        s.commit()
        first = s.exec(select(Staff).where(Staff.business_id == business.id).order_by(Staff.id)).first().id
    assert next(p for p in client.get("/api/mobile/staff", headers=h).json()["staff"] if p["id"] == first)["example"]
    r = client.post(f"/api/mobile/staff/{first}/windows", headers=h, json={})
    assert r.status_code == 409 and "пример" in r.json()["error"]
    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.example_ok = True
        s.add(b)
        s.commit()
    r = client.post(f"/api/mobile/staff/{first}/windows", headers=h, json={"start": "18:00", "end": "09:00"})
    assert r.status_code == 422
    assert client.post("/api/mobile/staff/999999/windows", headers=h, json={}).status_code == 404
    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.altegio_location_id = 777
        s.add(b)
        s.commit()
    r = client.post(f"/api/mobile/staff/{first}/windows", headers=h, json={})
    assert r.status_code == 409 and "Altegio" in r.json()["error"]
