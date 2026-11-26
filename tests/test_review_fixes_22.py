"""Fixes from the independent review of #290-#298 (26.11.2026)."""

from fastapi.testclient import TestClient
from sqlmodel import select

from joop import billing, db, free_plan
from joop.models import Business, Slot, Staff
from joop.niches import get_pack
from joop.timeutil import utcnow
from joop.web.app import create_app

from .test_mobile import auth, client, sign_in  # noqa: F401 - the client fixture
from .test_web import csrf_of

FORM = {"name": "Фитнес Алга", "niche": "fitness", "phone": "0555 123 456", "password": "alga-fit-2026", "contact_name": "Айгерим"}


def _free_fitness(c) -> tuple[dict, int, int]:
    """A fitness business on the free plan with its one own coach; returns the app headers, the example group's id."""
    h = auth(c.post("/api/mobile/signup", json=FORM).json()["token"])
    people = c.get("/api/mobile/staff", headers=h).json()["staff"]
    group = next(p for p in people if p["group_size"] > 1 and p["example"])
    assert c.post("/api/mobile/staff", headers=h, json={"name": "Бакыт", "handles": "силовые"}).status_code == 200
    with db.new_session() as s:
        b = s.exec(select(Business).where(Business.slug == "fitnes-alga")).one()
        free_plan.switch(billing.get_subscription(s, b.id))
        s.commit()
        return h, group["id"], b.id


def test_a_seats_or_group_change_alone_cannot_make_a_second_real_master_on_the_free_plan(engine, settings, rt):
    """Only name, role and «what they take» were checked: changing an example group from 12 to 14 places made it the
    business's own, a second real master on the free plan, and the AI stopped answering every customer."""
    with TestClient(create_app(settings, rt, init=False)) as c:
        h, group, business_id = _free_fitness(c)
        row = next(p for p in c.get("/api/mobile/staff", headers=h).json()["staff"] if p["id"] == group)
        r = c.post(f"/api/mobile/staff/{group}", headers=h, json={**row, "group_size": 14})
        assert r.status_code == 409 and r.json()["error"] == free_plan.TOO_MANY
        # the panel's form the same way
        c.post("/login", data={"slug": "fitnes-alga", "password": "alga-fit-2026", "csrf": csrf_of(c.get("/login").text)})
        page = c.post(f"/panel/staff/{group}", data={"name": row["name"], "role": row["role"], "handles": row["handles"],
                                                     "capacity": "0", "group_size": "14",
                                                     "csrf": csrf_of(c.get("/panel/staff").text)}, follow_redirects=True)
        assert free_plan.TOO_MANY in page.text
    with db.new_session() as s:
        assert s.get(Staff, group).group_size == 12  # nothing changed
        assert billing.access_ok(s, business_id, utcnow())  # the AI still answers


def test_opening_again_with_another_length_never_overlaps_the_times_already_open(client, business):
    """Only the exact start was checked: 60-minute times and then 30-minute ones gave 10:00 and 10:30 to one master."""
    h = auth(sign_in(client).json()["token"])
    person = client.post("/api/mobile/staff", headers=h, json={"name": "Д-р Асанов"}).json()["staff"][-1]["id"]
    url = f"/api/mobile/staff/{person}/windows"
    assert client.post(url, headers=h, json={"days": 1, "step": 60, "start": "10:00", "end": "12:00"}).json()["created"] == 2
    assert client.post(url, headers=h, json={"days": 1, "step": 30, "start": "10:00", "end": "12:00"}).json()["created"] == 0
    # a longer stretch with the shorter length adds only what is free: 12:00-13:00 in two halves
    assert client.post(url, headers=h, json={"days": 1, "step": 30, "start": "10:00", "end": "13:00"}).json()["created"] == 2
    with db.new_session() as s:
        times = [(x.start.strftime("%H:%M"), x.duration_min) for x in s.exec(
            select(Slot).where(Slot.staff_id == person).order_by(Slot.start)).all()]
    assert times == [("10:00", 60), ("11:00", 60), ("12:00", 30), ("12:30", 30)]


def test_the_counter_card_names_the_page_that_has_the_switch(business, rt, settings):
    from .test_web import login

    with TestClient(create_app(settings, rt, init=False)) as c:
        login(c)
        page = c.get("/panel/card?via=book").text
        # the switch lives in the panel's online page («Клиенты записываются сами»), not on «Запуск»
        assert "Запись по ссылке выключена" in page and "«Запуске»" not in page and "«Клиенты записываются сами»" in page
        assert f"«{get_pack('dental').online_label}»" in page
