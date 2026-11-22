"""The business's people edited in the owner's app: the sign-up example out, its own people in, as the panel's
«Специалисты». Customers are booked only to the business's own people (joop/samples.py)."""

from fastapi.testclient import TestClient
from sqlmodel import select

from joop import billing, db, free_plan
from joop.models import Business, PanelUser, Slot, Staff
from joop.security import hash_password
from joop.web.app import create_app

from .conftest import NOW_UTC
from .test_mobile import auth, client, sign_in  # noqa: F401 - the client fixture

FORM = {"name": "Салон Айгерим", "niche": "beauty", "phone": "0555 123 456", "password": "aigerim-2026", "contact_name": "Айгерим"}


def _step(c, h):
    return next(x for x in c.get("/api/mobile/setup", headers=h).json()["steps"] if x["key"] == "staff")


def test_a_new_business_swaps_the_example_people_for_its_own_from_the_phone(engine, settings, rt):
    with TestClient(create_app(settings, rt, init=False)) as c:
        h = auth(c.post("/api/mobile/signup", json=FORM).json()["token"])
        data = c.get("/api/mobile/staff", headers=h).json()
        assert data["label"] and data["booking"] is True and data["staff"] and all(x["example"] for x in data["staff"])
        assert _step(c, h)["done"] is False
        r = c.post("/api/mobile/staff/example/delete", headers=h).json()
        assert r["removed"] == len(data["staff"]) and r["staff"] == []
        with db.new_session() as s:  # the example's free times went with them
            b = s.exec(select(Business).where(Business.slug == "salon-aygerim")).one()
            assert s.exec(select(Slot).where(Slot.business_id == b.id, Slot.status == "free")).all() == []
        r = c.post("/api/mobile/staff", headers=h, json={"name": "Айгерим", "role": "мастер маникюра", "handles": "маникюр, педикюр"})
        assert r.status_code == 200, r.text
        assert [(x["name"], x["handles"], x["example"]) for x in r.json()["staff"]] == [("Айгерим", "маникюр, педикюр", False)]
        assert _step(c, h)["done"] is True


def test_edit_and_retire_keep_bookings_history_and_the_input_is_checked(client, business):
    h = auth(sign_in(client).json()["token"])
    first = client.get("/api/mobile/staff", headers=h).json()["staff"][0]
    r = client.post(f"/api/mobile/staff/{first['id']}", headers=h, json={"name": "Д-р Асанов", "role": "терапевт", "handles": "кариес"})
    assert next(x for x in r.json()["staff"] if x["id"] == first["id"])["name"] == "Д-р Асанов"
    assert client.post(f"/api/mobile/staff/{first['id']}", headers=h, json={"name": " "}).status_code == 422
    assert client.post("/api/mobile/staff", headers=h, json={"name": ""}).status_code == 422
    r = client.post(f"/api/mobile/staff/{first['id']}/delete", headers=h)
    assert first["id"] not in [x["id"] for x in r.json()["staff"]]
    with db.new_session() as s:
        assert s.get(Staff, first["id"]).active is False  # retired, not deleted
    assert client.post(f"/api/mobile/staff/{first['id']}", headers=h, json={"name": "X"}).status_code == 404
    assert client.post("/api/mobile/staff/999999/delete", headers=h).status_code == 404


def test_the_free_plan_keeps_one_master(client, business):
    with db.new_session() as s:
        rows = s.exec(select(Staff).where(Staff.business_id == business.id).order_by(Staff.id)).all()
        for row in rows[1:]:
            row.active = False
            s.add(row)
        free_plan.switch(billing.start_trial(s, s.get(Business, business.id), 14, NOW_UTC))
        s.commit()
    h = auth(sign_in(client).json()["token"])
    r = client.post("/api/mobile/staff", headers=h, json={"name": "Второй"})
    assert r.status_code == 409 and r.json()["error"] == free_plan.TOO_MANY


def test_another_business_a_master_altegio_and_rooms_are_refused(client, business):
    with db.new_session() as s:
        other = Business(slug="other", name="Другой", niche="dental")
        s.add(other)
        s.flush()
        foreign = Staff(business_id=other.id, name="Чужой")
        master = Staff(business_id=business.id, name="Мастер")
        s.add(foreign)
        s.add(master)
        s.flush()
        s.add(PanelUser(business_id=business.id, login="m1", name="Мастер", password_hash=hash_password("master-pass-1"),
                        staff_id=master.id))
        s.commit()
        foreign_id = foreign.id
    h = auth(sign_in(client).json()["token"])
    assert client.post(f"/api/mobile/staff/{foreign_id}", headers=h, json={"name": "Мой"}).status_code == 404
    assert client.post(f"/api/mobile/staff/{foreign_id}/delete", headers=h).status_code == 404
    hm = auth(sign_in(client, user="m1", password="master-pass-1").json()["token"])
    assert client.get("/api/mobile/staff", headers=hm).status_code == 403
    assert client.post("/api/mobile/staff", headers=hm, json={"name": "X"}).status_code == 403
    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.altegio_location_id = 777
        s.add(b)
        s.commit()
    r = client.post("/api/mobile/staff", headers=h, json={"name": "X"})
    assert r.status_code == 409 and "Altegio" in r.json()["error"]
    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.altegio_location_id, b.niche = 0, "hotel"
        s.add(b)
        s.commit()
    r = client.post("/api/mobile/staff", headers=h, json={"name": "Люкс"})
    assert r.status_code == 409 and "в панели" in r.json()["error"]
