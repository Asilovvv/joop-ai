"""Sign-up's example: fictional terms never reach real customers, the copied hours are flagged (joop/samples.py)."""

from sqlmodel import select

from joop import db
from joop.models import Business
from joop.web.saas import checklist

from .conftest import NOW_UTC
from .test_saas import app_client, saas_settings, signup  # noqa: F401  (fixtures)


def test_signup_leaves_the_examples_terms_out_and_flags_its_hours(app_client):
    """A new cafe got «Кафе … (демо)», «минимальная сумма заказа 600 сом, доставка 300 сом» and «Стол держим 15
    минут» from the example; the AI told real customers these as the cafe's own terms."""
    signup(app_client, name="Кафе Береке", niche="restaurant")
    with db.new_session() as s:
        b = s.exec(select(Business).where(Business.name == "Кафе Береке")).one()
        assert (b.description, b.booking_policy, b.min_order, b.delivery_fee, b.free_delivery_from) == ("", "", 0, 0, 0)
        assert b.hours_text  # the example's hours stay so the test chat can answer, but the checklist asks to check them
        contacts = next(i for i in checklist(s, b, NOW_UTC) if i["key"] == "contacts")
        assert not contacts["done"] and f"часы работы (сейчас из примера: {b.hours_text})" in contacts["hint"]
        b.hours_text = b.hours_text + ", без выходных"  # the owner changed them
        b.address = "Бишкек, ул. Токтогула 1"
        assert next(i for i in checklist(s, b, NOW_UTC) if i["key"] == "contacts")["done"]


def test_a_prospect_demo_is_asked_for_its_own_address_and_phone(engine):
    """A demo the founder creates for a prospect keeps the example's fictional address and phone: hidden from real
    customers (samples.example_contacts), so the checklist must not call the contacts done."""
    from joop.presets import create_business

    with db.new_session() as s:
        b = create_business(s, slug="prospect", name="Береке", password="prospect-pass", niche="restaurant", demo=True,
                            now_utc=NOW_UTC)
        b.hours_text = "Ежедневно 09:00–21:00"  # the owner's own hours
        contacts = next(i for i in checklist(s, b, NOW_UTC) if i["key"] == "contacts")
        assert not contacts["done"]
        assert f"адрес (сейчас из примера: {b.address})" in contacts["hint"]
        assert f"телефон (сейчас из примера: {b.phone})" in contacts["hint"]
        b.address, b.phone = "Бишкек, Токтогула 1", "+996 700 123 456"
        contacts = next(i for i in checklist(s, b, NOW_UTC) if i["key"] == "contacts")  # the example's rules are left
        assert not contacts["done"] and "адрес" not in contacts["hint"] and "порядок записи (сейчас из примера:" in contacts["hint"]
        b.booking_policy, b.delivery_fee = "Стол держим 20 минут.", 200  # the café's own
        assert next(i for i in checklist(s, b, NOW_UTC) if i["key"] == "contacts")["done"]
