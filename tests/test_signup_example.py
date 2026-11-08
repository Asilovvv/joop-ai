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
