"""Found walking a fitness studio's launch from the phone (26.11.2026): a sign-up in the app, own prices, people
and free times, booking by link on, a customer booking by the QR page."""

from fastapi.testclient import TestClient
from sqlmodel import select

from joop import db
from joop.models import Business
from joop.niches import all_packs, get_pack
from joop.web import mobile as web_mobile
from joop.web.app import create_app
from joop.web.menu import PEOPLE_KY, people_title

from .test_booking_page import CLOCK, _form, form_clock  # noqa: F401 - the form's clock

FORM = {"name": "Студия Алга", "niche": "fitness", "phone": "0555 123 456", "password": "alga-fit-2026", "contact_name": "Айгерим"}


def test_every_niche_names_its_people_in_kyrgyz():
    """The Kyrgyz booking page said «Тренеры и залы» in Russian; the menu page said «Усталар» (masters) even for a
    restaurant's tables or a hotel's rooms."""
    for key in all_packs():
        assert get_pack(key).resource_label in PEOPLE_KY, key
    assert people_title(get_pack("fitness"), "ky") == "Машыктыруучулар жана залдар"
    assert people_title(get_pack("restaurant"), "ky") == "Үстөлдөр"
    assert people_title(get_pack("fitness"), "ru") == "Тренеры и залы"


def test_a_studio_launched_from_the_phone_gets_its_first_real_customer_from_the_qr_page(engine, settings, rt):
    """The launch list's «Первый настоящий клиент» counted chats only: a customer who booked on the page stayed
    unseen, and the step the owner was waiting for stayed undone."""
    web_mobile._signups.clear()
    with TestClient(create_app(settings, rt, init=False)) as c:
        r = c.post("/api/mobile/signup", json=FORM).json()
        h, slug = {"Authorization": f"Bearer {r['token']}"}, r["business"]["slug"]
        c.post("/api/mobile/contacts", headers=h, json={"address": "Бишкек, Ахунбаева 120", "phone": "+996 555 123 456",
                                                        "hours_text": "Ежедневно 08:00–21:00", "work_start": "08:00",
                                                        "work_end": "21:00", "days_off": []})
        c.post("/api/mobile/services/example/delete", headers=h)
        c.post("/api/mobile/services", headers=h, json={"name": "Йога, разовое занятие", "price": "500"})
        c.post("/api/mobile/staff/example/delete", headers=h)
        c.post("/api/mobile/staff", headers=h, json={"name": "Йога утром", "role": "групповое занятие", "group_size": 10})
        for person in c.post("/api/mobile/staff", headers=h, json={"name": "Бакыт", "role": "тренер"}).json()["staff"]:
            c.post(f"/api/mobile/staff/{person['id']}/windows", headers=h,
                   json={"days": 7, "step": 60, "start": "08:00", "end": "11:00"})
        c.post("/api/mobile/setup/page-booking", headers=h, json={"on": True})
        real = lambda: next(x for x in c.get("/api/mobile/setup", headers=h).json()["steps"] if x["key"] == "real")["done"]  # noqa: E731
        assert real() is False

        c.cookies.clear()  # a customer, not logged in
        assert "<h2>Машыктыруучулар жана залдар</h2>" in c.get(f"/m/{slug}/book?lang=ky").text
        assert "Машыктыруучулар жана залдар" in c.get(f"/m/{slug}?lang=ky").text
        page = c.get(f"/m/{slug}/book").text
        slot = page.split('href="?slot=')[1].split('"')[0]
        fields = _form(c.get(f"/m/{slug}/book?slot={slot}").text)
        CLOCK["t"] += 8
        done = c.post(f"/m/{slug}/book", data={**fields, "name": "Айбек", "phone": "0555 987 654"}, follow_redirects=False)
        assert done.status_code == 303
        assert real() is True
    with db.new_session() as s:
        assert s.exec(select(Business).where(Business.slug == slug)).one().page_booking
