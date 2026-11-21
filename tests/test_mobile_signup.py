"""A business signs itself up in the app (POST /api/mobile/signup), as on the site, and is signed in at once."""

from dataclasses import replace

from fastapi.testclient import TestClient
from sqlmodel import select

from joop import db, samples
from joop.models import Business, Subscription
from joop.web.app import create_app

FORM = {"name": "Салон Айгерим", "niche": "beauty", "phone": "0555 123 456", "password": "aigerim-2026", "contact_name": "Айгерим"}


def test_the_app_lists_the_niches_and_signs_up(engine, settings, rt):
    with TestClient(create_app(settings, rt, init=False)) as c:
        niches = c.get("/api/mobile/niches").json()
        keys = [n["key"] for n in niches["niches"]]
        assert "beauty" in keys and keys[-1] == "other" and niches["trial_days"] == settings.trial_days
        r = c.post("/api/mobile/signup", json=FORM)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["business"]["slug"] == "salon-aygerim" and data["role"] == "owner" and data["setup_path"] == "/panel/setup"
        me = c.get("/api/mobile/me", headers={"Authorization": f"Bearer {data['token']}"})
        assert me.status_code == 200 and me.json()["business"]["name"] == "Салон Айгерим"
        # the password works for the panel and the app's own sign-in, by the generated login or the phone
        assert c.post("/api/mobile/login", json={"company": "salon-aygerim", "password": "aigerim-2026"}).status_code == 200
        assert c.post("/api/mobile/login", json={"company": "+996555123456", "password": "aigerim-2026"}).status_code == 200
    with db.new_session() as s:
        b = s.exec(select(Business).where(Business.slug == "salon-aygerim")).one()
        sub = s.exec(select(Subscription).where(Subscription.business_id == b.id)).one()
        assert (b.niche, b.phone, b.address, b.booking_policy) == ("beauty", "0555 123 456", "", "")
        assert sub.status == "trial" and sub.source == "signup-app"
        assert samples.left(s, b).services  # the sample price list, hidden from customers until replaced


def test_what_the_site_refuses_the_app_refuses(engine, settings, rt):
    with TestClient(create_app(settings, rt, init=False)) as c:
        for bad in ({"password": "short"}, {"phone": "12"}, {"name": "A"}):
            r = c.post("/api/mobile/signup", json={**FORM, **bad})
            assert r.status_code == 422 and r.json()["error"] == "Укажите название, телефон и пароль не короче 8 символов."
        assert c.post("/api/mobile/signup", json={**FORM, "niche": "no-such"}).status_code == 200
    with db.new_session() as s:
        assert s.exec(select(Business).where(Business.slug == "salon-aygerim")).one().niche == "other"


def test_a_flood_from_one_address_is_stopped(engine, settings, rt):
    with TestClient(create_app(settings, rt, init=False)) as c:
        codes = [c.post("/api/mobile/signup", json={**FORM, "name": f"Салон {n}"}).status_code for n in range(5)]
    assert codes == [200, 200, 200, 429, 429]


def test_closed_when_sign_up_is_off(engine, settings, rt):
    with TestClient(create_app(replace(settings, signup_enabled=False), rt, init=False)) as c:
        assert c.post("/api/mobile/signup", json=FORM).status_code == 404
        assert c.get("/api/mobile/niches").status_code == 404
