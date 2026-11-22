"""Contacts and opening hours from the owner's app: the launch list's «Контакты и часы работы» step without the
panel. The example's address, phone and hours are marked, and customers are told only the business's own."""

from fastapi.testclient import TestClient
from sqlmodel import select

from joop import db, samples
from joop.models import Business, PanelUser, Staff
from joop.security import hash_password
from joop.web.app import create_app

from .test_mobile import auth, client, sign_in  # noqa: F401 - the client fixture

FORM = {"name": "Салон Айгерим", "niche": "beauty", "phone": "0555 123 456", "password": "aigerim-2026", "contact_name": "Айгерим"}


def _step(c, h):
    return next(x for x in c.get("/api/mobile/setup", headers=h).json()["steps"] if x["key"] == "contacts")


def test_a_new_business_writes_its_own_contacts_and_hours_from_the_phone(engine, settings, rt):
    with TestClient(create_app(settings, rt, init=False)) as c:
        h = auth(c.post("/api/mobile/signup", json=FORM).json()["token"])
        before = c.get("/api/mobile/contacts", headers=h).json()
        assert "hours_text" in before["example"] and _step(c, h)["done"] is False
        r = c.post("/api/mobile/contacts", headers=h, json={
            "address": "Бишкек, ул. Токтогула 100", "phone": "+996 555 123 456", "hours_text": "Пн–Сб 10:00–20:00",
            "work_start": "10:00", "work_end": "20:00", "days_off": [7, 9]})
        assert r.status_code == 200, r.text
        assert r.json() == {"address": "Бишкек, ул. Токтогула 100", "phone": "+996 555 123 456",
                            "hours_text": "Пн–Сб 10:00–20:00", "work_start": "10:00", "work_end": "20:00",
                            "days_off": [7], "example": []}
        assert _step(c, h)["done"] is True
    with db.new_session() as s:
        b = s.exec(select(Business).where(Business.slug == "salon-aygerim")).one()
        assert (b.days_off, samples.customer_hours(b), samples.customer_contact(b, "address")) == \
            ("7", "Пн–Сб 10:00–20:00", "Бишкек, ул. Токтогула 100")


def test_hours_that_end_before_they_start_are_refused_and_nothing_changes(client, business):
    h = auth(sign_in(client).json()["token"])
    before = client.get("/api/mobile/contacts", headers=h).json()
    r = client.post("/api/mobile/contacts", headers=h, json={**before, "address": "Другой", "work_start": "18:00", "work_end": "09:00"})
    assert r.status_code == 422 and "позже начала" in r.json()["error"]
    assert client.post("/api/mobile/contacts", headers=h, json={**before, "work_start": "9 утра"}).status_code == 422
    assert client.get("/api/mobile/contacts", headers=h).json() == before


def test_a_master_does_not_change_the_contacts(client, business):
    with db.new_session() as s:
        master = Staff(business_id=business.id, name="Мастер")
        s.add(master)
        s.flush()
        s.add(PanelUser(business_id=business.id, login="m1", name="Мастер", password_hash=hash_password("master-pass-1"),
                        staff_id=master.id))
        s.commit()
    hm = auth(sign_in(client, user="m1", password="master-pass-1").json()["token"])
    assert client.get("/api/mobile/contacts", headers=hm).status_code == 403
    assert client.post("/api/mobile/contacts", headers=hm, json={"address": "X"}).status_code == 403
    assert client.get("/api/mobile/contacts").status_code == 401
