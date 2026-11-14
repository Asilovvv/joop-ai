"""The «Запуск» checklist speaks the niche's language: a request for cargo, no counter for work at the customer's."""

from fastapi.testclient import TestClient

from joop import db
from joop.niches import get_pack
from joop.presets import create_business
from joop.web.app import create_app

from .conftest import NOW_UTC
from .test_web import csrf_of


def setup_page(settings, rt, niche):
    with db.new_session() as s:
        create_business(s, slug=niche, name=niche.title(), password="pass-12345", niche=niche, demo=True, now_utc=NOW_UTC)
        s.commit()
    with TestClient(create_app(settings, rt, init=False)) as c:
        token = csrf_of(c.get("/login").text)
        c.post("/login", data={"slug": niche, "password": "pass-12345", "csrf": token})
        return c.get("/panel/setup").text


def test_cargo_leaves_a_request_and_has_no_counter(settings, rt, engine):
    page = setup_page(settings, rt, "cargo")
    assert "спросите цену, оставьте заявку." in page and "запишитесь" not in page
    assert "Наклейка с QR-кодом на машине и визитке" in page and "у кассы" not in page


def test_water_orders_from_a_car_and_a_dentist_keeps_the_counter(settings, rt, engine):
    water = setup_page(settings, rt, "water")
    assert "спросите цену, закажите." in water and "Наклейка с QR-кодом на машине" in water
    dental = setup_page(settings, rt, "dental")
    assert "спросите цену, запишитесь." in dental and "Табличка с QR-кодом у кассы" in dental


def test_which_niches_go_to_the_customer():
    assert {n for n in ("cleaning", "water", "cargo", "renovation", "dental", "pharmacy", "shop") if get_pack(n).comes_to_client} == {
        "cleaning", "water", "cargo", "renovation"}
