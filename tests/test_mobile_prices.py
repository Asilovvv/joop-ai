"""The price list edited in the owner's app: the sign-up example out, the business's own prices in, as the panel's
«Прайс». The AI names only rows that are no longer the example (joop/samples.py)."""

from fastapi.testclient import TestClient
from sqlmodel import select

from joop import db
from joop.models import Business, PanelUser, Service, Staff
from joop.security import hash_password
from joop.web.app import create_app

from .test_mobile import auth, client, sign_in  # noqa: F401 - the client fixture

FORM = {"name": "Салон Айгерим", "niche": "beauty", "phone": "0555 123 456", "password": "aigerim-2026", "contact_name": "Айгерим"}


def test_a_new_business_swaps_the_example_for_its_own_prices_from_the_phone(engine, settings, rt):
    with TestClient(create_app(settings, rt, init=False)) as c:
        h = auth(c.post("/api/mobile/signup", json=FORM).json()["token"])
        rows = c.get("/api/mobile/services", headers=h).json()["services"]
        assert rows and all(x["example"] for x in rows)
        assert next(x for x in c.get("/api/mobile/setup", headers=h).json()["steps"] if x["key"] == "prices")["done"] is False

        # one example row edited becomes the business's own; the rest are still the example
        first = rows[0]
        r = c.post(f"/api/mobile/services/{first['id']}", headers=h,
                   json={"name": "Стрижка женская", "price": "900", "note": "30–40 минут"})
        assert r.status_code == 200, r.text
        edited = next(x for x in r.json()["services"] if x["id"] == first["id"])
        assert (edited["name"], edited["price"], edited["price_value"], edited["note"], edited["example"]) == \
            ("Стрижка женская", "900", 900, "30–40 минут", False)

        r = c.post("/api/mobile/services/example/delete", headers=h).json()
        assert r["removed"] == len(rows) - 1 and [x["id"] for x in r["services"]] == [first["id"]]
        assert c.post("/api/mobile/services/example/delete", headers=h).json()["removed"] == 0

        r = c.post("/api/mobile/services", headers=h, json={"name": "Маникюр", "price": "1200 сом", "name_ky": "Маникюр"})
        added = r.json()["services"][-1]
        assert (added["name"], added["price_value"], added["available"], added["example"]) == ("Маникюр", 1200, True, False)
        assert next(x for x in c.get("/api/mobile/setup", headers=h).json()["steps"] if x["key"] == "prices")["done"] is True

        r = c.post(f"/api/mobile/services/{added['id']}/delete", headers=h)
        assert [x["name"] for x in r.json()["services"]] == ["Стрижка женская"]
    with db.new_session() as s:
        b = s.exec(select(Business).where(Business.slug == "salon-aygerim")).one()
        assert [x.name for x in s.exec(select(Service).where(Service.business_id == b.id)).all()] == ["Стрижка женская"]


def test_editing_keeps_the_stop_list_and_checks_the_input(client, business):
    h = auth(sign_in(client).json()["token"])
    row = client.get("/api/mobile/services", headers=h).json()["services"][0]
    client.post(f"/api/mobile/services/{row['id']}/available", headers=h, json={"available": False})
    r = client.post(f"/api/mobile/services/{row['id']}", headers=h, json={"name": row["name"], "price": "2 500"})
    assert next(x for x in r.json()["services"] if x["id"] == row["id"])["available"] is False  # still on the stop list
    assert client.post(f"/api/mobile/services/{row['id']}", headers=h, json={"name": "  "}).status_code == 422
    assert client.post("/api/mobile/services", headers=h, json={"name": ""}).status_code == 422
    assert client.post("/api/mobile/services/999999", headers=h, json={"name": "X"}).status_code == 404
    assert client.post("/api/mobile/services/999999/delete", headers=h).status_code == 404


def test_another_business_row_altegio_and_a_master_are_refused(client, business):
    with db.new_session() as s:
        other = Business(slug="other", name="Другой", niche="dental")
        s.add(other)
        s.flush()
        foreign = Service(business_id=other.id, name="Чужая", price="100")
        master = Staff(business_id=business.id, name="Мастер")
        s.add(foreign)
        s.add(master)
        s.flush()
        s.add(PanelUser(business_id=business.id, login="m1", name="Мастер", password_hash=hash_password("master-pass-1"),
                        staff_id=master.id))
        s.commit()
        foreign_id = foreign.id
    h = auth(sign_in(client).json()["token"])
    assert client.post(f"/api/mobile/services/{foreign_id}", headers=h, json={"name": "Моя"}).status_code == 404
    assert client.post(f"/api/mobile/services/{foreign_id}/delete", headers=h).status_code == 404
    hm = auth(sign_in(client, user="m1", password="master-pass-1").json()["token"])
    assert client.post("/api/mobile/services", headers=hm, json={"name": "X"}).status_code == 403
    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.altegio_location_id = 777
        s.add(b)
        s.commit()
    r = client.post("/api/mobile/services", headers=h, json={"name": "X"})
    assert r.status_code == 409 and "Altegio" in r.json()["error"]
