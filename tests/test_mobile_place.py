"""The customer's card of a business in the app: «Записаться самому — 24/7» opens the booking page while customers can
book there, as the counter card and its QR do; the public page (QR menu, catalogue, prices) while it is open; Kyrgyz
names of services for a Kyrgyz-speaking customer."""

from datetime import datetime

from sqlmodel import select

from joop import billing, db
from joop.models import Business, Service

from .test_mobile import client  # noqa: F401 - the client fixture


def _set(business_id: int, **fields) -> None:
    with db.new_session() as s:
        b = s.get(Business, business_id)
        for k, v in fields.items():
            setattr(b, k, v)
        s.add(b)
        s.commit()


def test_book_yourself_is_offered_only_while_the_page_takes_bookings(client, business):
    card = client.get("/api/mobile/places/aktish").json()
    assert (card["book_url"], card["page_url"]) == ("", "")  # the page is closed
    assert card["page_label"] == "Прайс онлайн"
    _set(business.id, menu_enabled=True)
    card = client.get("/api/mobile/places/aktish").json()
    assert card["page_url"] == "https://joop.test/m/aktish" and card["book_url"] == ""  # booking by link is off
    _set(business.id, page_booking=True)
    assert client.get("/api/mobile/places/aktish").json()["book_url"] == "https://joop.test/m/aktish/book"
    with db.new_session() as s:  # a trial that ended long ago: the page takes no bookings, the card does not offer them
        billing.start_trial(s, s.get(Business, business.id), 14, datetime(2026, 9, 1))
        s.commit()
    card = client.get("/api/mobile/places/aktish").json()
    assert card["book_url"] == "" and card["page_url"] == "https://joop.test/m/aktish"


def test_services_carry_their_kyrgyz_names(client, business):
    with db.new_session() as s:
        row = s.exec(select(Service).where(Service.business_id == business.id).order_by(Service.id)).first()
        row.name_ky = "Кеңеш берүү"
        s.add(row)
        s.commit()
        row_id = row.id
    card = client.get("/api/mobile/places/aktish").json()
    assert next(x for x in card["services"] if x["id"] == row_id)["name_ky"] == "Кеңеш берүү"
