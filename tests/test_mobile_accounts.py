"""Staff logins from the owner's app: the panel's «Доступ сотрудников» (joop/web/accounts.py) on the phone. A salon
launched from the phone gives each master her own login, sees who signed in when, turns a login off or changes its
password, with the panel's rules."""

from fastapi.testclient import TestClient
from sqlmodel import select

from joop import db
from joop.models import PanelUser
from joop.web.app import create_app

from .test_mobile import auth, client, sign_in  # noqa: F401 - the client fixture

SALON = {"name": "Салон Айгерим", "niche": "beauty", "phone": "0555 123 456", "password": "aigerim-2026", "contact_name": "Айгерим"}


def test_a_salon_gives_its_master_a_login_from_the_phone_and_she_signs_in(engine, settings, rt):
    with TestClient(create_app(settings, rt, init=False)) as c:
        h = auth(c.post("/api/mobile/signup", json=SALON).json()["token"])
        info = c.get("/api/mobile/accounts", headers=h).json()
        assert (info["company"], info["min_password"], info["masters"], info["users"]) == ("salon-aygerim", 8, True, [])
        assert info["people"] == []  # the sign-up example's masters are not real people to give a login to
        c.post("/api/mobile/staff/example/delete", headers=h)
        nurgul = c.post("/api/mobile/staff", headers=h, json={"name": "Нургуль", "handles": "маникюр"}).json()["staff"][0]["id"]
        assert c.get("/api/mobile/accounts", headers=h).json()["people"] == [{"id": nurgul, "name": "Нургуль"}]

        # the panel's rules, word for word
        for body, problem in [({"name": "", "login": "nurgul", "password": "nurgul-pass"}, "Напишите имя сотрудника."),
                              ({"name": "Нургуль", "login": "Нур Гуль", "password": "nurgul-pass"}, "Логин: 3–32"),
                              ({"name": "Нургуль", "login": "nurgul", "password": "short"}, "не короче 8")]:
            r = c.post("/api/mobile/accounts", headers=h, json=body)
            assert r.status_code == 422 and problem in r.json()["error"]
        r = c.post("/api/mobile/accounts", headers=h, json={"name": "Нургуль", "login": "Nurgul", "password": "nurgul-pass",
                                                             "staff_id": nurgul})
        assert r.status_code == 200, r.text
        assert r.json()["added"] == "nurgul"
        user = r.json()["users"][0]
        assert (user["login"], user["active"], user["staff_name"], user["last_login_local"]) == ("nurgul", True, "Нургуль", None)
        assert c.post("/api/mobile/accounts", headers=h, json={"name": "Другая", "login": "nurgul",
                                                               "password": "other-pass"}).json()["error"] == "Такой логин уже есть."

        # she signs in with the company login, her own login and password, and sees her own part only
        r = c.post("/api/mobile/login", json={"company": "salon-aygerim", "user": "nurgul", "password": "nurgul-pass"})
        assert r.status_code == 200 and r.json()["role"] == "master"
        hm = auth(r.json()["token"])
        assert c.get("/api/mobile/accounts", headers=hm).status_code == 403
        assert c.get("/api/mobile/accounts", headers=h).json()["users"][0]["last_login_local"] == "2026-11-04T23:14"  # Bishkek

        # a new password ends her session; off keeps her out
        assert c.post(f"/api/mobile/accounts/{user['id']}/password", headers=h, json={"password": "1234567"}).status_code == 422
        assert c.post(f"/api/mobile/accounts/{user['id']}/password", headers=h, json={"password": "new-nurgul-pass"}).status_code == 200
        assert c.get("/api/mobile/me", headers=hm).status_code == 401
        r = c.post(f"/api/mobile/accounts/{user['id']}/active", headers=h, json={"active": False})
        assert r.json()["users"][0]["active"] is False
        assert c.post("/api/mobile/login", json={"company": "salon-aygerim", "user": "nurgul",
                                                 "password": "new-nurgul-pass"}).status_code == 401


def test_only_the_owner_and_only_her_business(client, business):
    h = auth(sign_in(client).json()["token"])
    with TestClient(client.app) as c:
        other = auth(c.post("/api/mobile/signup", json=SALON).json()["token"])
        c.post("/api/mobile/accounts", headers=other, json={"name": "Нургуль", "login": "nurgul", "password": "nurgul-pass"})
    with db.new_session() as s:
        foreign = s.exec(select(PanelUser).where(PanelUser.login == "nurgul")).one()
    assert client.post(f"/api/mobile/accounts/{foreign.id}/active", headers=h, json={"active": False}).status_code == 404
    assert client.post(f"/api/mobile/accounts/{foreign.id}/password", headers=h, json={"password": "taken-over-1"}).status_code == 404
    with db.new_session() as s:
        assert s.get(PanelUser, foreign.id).active is True
