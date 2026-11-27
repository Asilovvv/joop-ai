"""«Заказы в работе» in the owner's app: a repair shop, a car service, an optician or a furniture maker takes a
receipt at the counter and marks it ready from the phone; «готов» sends the customer the panel's message once."""

import re

from fastapi.testclient import TestClient
from sqlmodel import select

from joop import db
from joop.models import Job, PanelUser, Staff
from joop.security import hash_password
from joop.web.app import create_app

from .test_jobs import ask, shop
from .test_mobile import auth, client, sign_in  # noqa: F401 - the client fixture

FORM = {"name": "Мастер Ремонт", "niche": "repair", "phone": "0555 123 456", "password": "remont-2026", "contact_name": "Эрлан"}


def test_a_new_repair_shop_swaps_the_example_receipts_for_its_own_from_the_phone(engine, settings, rt):
    with TestClient(create_app(settings, rt, init=False)) as c:
        h = auth(c.post("/api/mobile/signup", json=FORM).json()["token"])
        assert c.get("/api/mobile/me", headers=h).json()["sections"]["jobs"] is True
        data = c.get("/api/mobile/jobs", headers=h).json()
        assert data["delivered"] is False and data["words"]["item_label"] == "Что сдали и что сделать"
        assert [x["key"] for x in data["statuses"]] == ["accepted", "in_progress", "ready", "issued", "cancelled"]
        assert {(x["number"], x["status"], x["example"]) for x in data["open"]} == {("1042", "ready", True), ("1043", "in_progress", True)}
        r = c.post("/api/mobile/jobs/example/delete", headers=h).json()
        assert r["removed"] == 2 and r["open"] == [] and r["done"] == []

        # what was left and the customer's phone are needed: by them the AI finds the job
        r = c.post("/api/mobile/jobs", headers=h, json={"item": "Куртка, химчистка", "customer_phone": "12"})
        assert r.status_code == 400 and "телефон клиента" in r.json()["error"]
        r = c.post("/api/mobile/jobs", headers=h, json={"item": "Куртка, химчистка", "customer_phone": "0555 404 404",
                                                         "customer_name": "Нурлан", "price": "600 сом", "ready_by": "2026-11-07"})
        assert r.status_code == 200, r.text
        job = r.json()["job"]
        assert re.fullmatch(r"\d{5}", job["number"]) and job["status"] == "accepted" and job["status_label"] == "принят"
        assert job["ready_by"] == "2026-11-07" and job["example"] is False
        assert [x["id"] for x in r.json()["open"]] == [job["id"]]
        assert c.post("/api/mobile/jobs", headers=h, json={"number": job["number"], "item": "Брюки",
                                                           "customer_phone": "0555 404 404"}).status_code == 409

        # nobody wrote from that number: «готов» is stored and staff are told to call
        r = c.post(f"/api/mobile/jobs/{job['id']}", headers=h, json={"status": "ready", "note": "", "price": "600 сом"}).json()
        assert r["customer_told"] is False and r["job"]["status"] == "ready" and r["job"]["ready_by"] == "2026-11-07"
        r = c.post(f"/api/mobile/jobs/{job['id']}", headers=h, json={"status": "issued", "price": "600 сом"}).json()
        assert r["customer_told"] is None and r["open"] == [] and [x["status_label"] for x in r["done"]] == ["выдан"]
        assert c.get("/api/mobile/jobs", headers=h, params={"q": "куртка"}).json()["done"][0]["id"] == job["id"]
        assert c.get("/api/mobile/jobs", headers=h, params={"q": "пальто"}).json()["done"] == []
        assert c.post(f"/api/mobile/jobs/{job['id']}", headers=h, json={"status": "lost"}).status_code == 400
    assert rt.tg.sent == []


def test_ready_from_the_phone_tells_the_customer_who_asked_once(engine, settings, rt):
    b = shop()
    ask(b.id, "telegram", "t9", "Квитанция 1043, мой номер 0700 343 434", "j5")
    with TestClient(create_app(settings, rt, init=False)) as c:
        h = auth(sign_in(c, company="clean", password="clean-pass").json()["token"])
        with db.new_session() as s:
            job = s.exec(select(Job).where(Job.business_id == b.id, Job.number == "1043")).one()
        r = c.post(f"/api/mobile/jobs/{job.id}", headers=h, json={"status": "ready", "price": "4 500 сом"}).json()
        assert r["customer_told"] is True and r["job"]["ready_notified"] is True
        assert rt.tg.sent[-1][0] == "t9" and "№1043 готов" in rt.tg.sent[-1][1]
        sent = len(rt.tg.sent)
        r = c.post(f"/api/mobile/jobs/{job.id}", headers=h, json={"status": "ready", "note": "в пакете"}).json()
        assert r["customer_told"] is None and len(rt.tg.sent) == sent  # once
        assert r["job"]["note"] == "в пакете" and r["job"]["price"] == ""  # the form's values, as the panel's


def test_jobs_are_not_a_masters_nor_a_niche_without_them(client, business):
    h = auth(sign_in(client).json()["token"])
    assert client.get("/api/mobile/me", headers=h).json()["sections"]["jobs"] is False
    assert client.get("/api/mobile/jobs", headers=h).status_code == 404
    assert client.post("/api/mobile/jobs", headers=h, json={"item": "X", "customer_phone": "0555 404 404"}).status_code == 404
    b = shop()
    with db.new_session() as s:
        master = Staff(business_id=b.id, name="Мастер")
        s.add(master)
        s.flush()
        s.add(PanelUser(business_id=b.id, login="m1", name="Мастер", password_hash=hash_password("master-pass-1"),
                        staff_id=master.id))
        other = Job(business_id=business.id, number="77777", item="Чужое пальто", customer_phone="0555 777 777")
        s.add(other)
        s.commit()
        s.refresh(other)
    hm = auth(sign_in(client, company="clean", user="m1", password="master-pass-1").json()["token"])
    assert client.get("/api/mobile/me", headers=hm).json()["sections"]["jobs"] is False
    assert client.get("/api/mobile/jobs", headers=hm).status_code == 403
    ho = auth(sign_in(client, company="clean", password="clean-pass").json()["token"])
    assert client.post(f"/api/mobile/jobs/{other.id}", headers=ho, json={"status": "ready"}).status_code == 404
    with db.new_session() as s:
        assert s.get(Job, other.id).status == "accepted"
