"""An owner's own price row that happens to share the example's name and price is the owner's, not the example
(found walking a cafe's launch from the phone, 26.11.2026): example rows are matched on every field sign-up copied."""

from fastapi.testclient import TestClient
from sqlmodel import select

from joop import db, samples
from joop.models import Business, Service
from joop.web import mobile as web_mobile
from joop.web.app import create_app

FORM = {"name": "Кафе Сайрам", "niche": "restaurant", "phone": "0555 123 456", "password": "sairam-2026", "contact_name": "Нурлан"}


def test_a_cafes_own_plov_at_the_examples_price_is_its_own(engine, settings, rt):
    """The example's «Плов, 350» stayed hidden from customers after the owner deleted the example and typed their own
    plov at the same price, and «Меню» on the launch list never got done («из них пример: 1»)."""
    web_mobile._signups.clear()
    with TestClient(create_app(settings, rt, init=False)) as c:
        h = {"Authorization": f"Bearer {c.post('/api/mobile/signup', json=FORM).json()['token']}"}
        before = c.get("/api/mobile/services", headers=h).json()["services"]
        plov = next(x for x in before if x["name"] == "Плов")
        assert plov["example"] and plov["price"] == "350"
        c.post("/api/mobile/services/example/delete", headers=h)
        for name, price in [("Плов", "350"), ("Лагман", "300")]:
            c.post("/api/mobile/services", headers=h, json={"name": name, "price": price})
        rows = c.get("/api/mobile/services", headers=h).json()["services"]
        assert [(x["name"], x["example"]) for x in rows] == [("Плов", False), ("Лагман", False)]
        step = next(x for x in c.get("/api/mobile/setup", headers=h).json()["steps"] if x["key"] == "prices")
        assert step["done"] is True and "пример" not in step["title"]
    with db.new_session() as s:
        b = s.exec(select(Business).where(Business.slug == "kafe-sayram")).one()
        assert samples.hidden_from_customers(s, b, "telegram").services == frozenset()


def test_an_untouched_example_row_is_still_the_example_and_any_edit_makes_it_own(engine, settings, rt):
    web_mobile._signups.clear()
    with TestClient(create_app(settings, rt, init=False)) as c:
        h = {"Authorization": f"Bearer {c.post('/api/mobile/signup', json=FORM).json()['token']}"}
        rows = c.get("/api/mobile/services", headers=h).json()["services"]
        assert rows and all(x["example"] for x in rows)  # sign-up's copy: every field as the example's
        plov = next(x for x in rows if x["name"] == "Плов")
        r = c.post(f"/api/mobile/services/{plov['id']}", headers=h,
                   json={"name": "Плов", "price": "350", "name_ky": plov["name_ky"], "note": "порция 500 г"})
        assert next(x for x in r.json()["services"] if x["id"] == plov["id"])["example"] is False
    with db.new_session() as s:
        b = s.exec(select(Business).where(Business.slug == "kafe-sayram")).one()
        hidden = samples.hidden_from_customers(s, b, "telegram").services
        assert plov["id"] not in hidden and len(hidden) == len(rows) - 1
        assert s.get(Service, plov["id"]).note == "порция 500 г"
