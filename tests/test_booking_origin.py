"""Where a booking came from, as the panel shows it: a partner's system or another assistant (API/MCP) is not «вручную»."""

import re
from datetime import timedelta

from fastapi.testclient import TestClient

from joop import db
from joop.customers import key_of
from joop.models import Booking
from joop.timeutil import utc_to_local
from joop.web.app import booking_origin, create_app

from .conftest import NOW_UTC
from .test_web import login

LOCAL = utc_to_local(NOW_UTC, "Asia/Bishkek")


def test_origin_names_the_api_the_channel_or_a_person():
    assert booking_origin(Booking(business_id=1, start=LOCAL, source="api")) == "через API"
    assert booking_origin(Booking(business_id=1, start=LOCAL, source="staff")) == "вручную"
    assert booking_origin(Booking(business_id=1, start=LOCAL, channel="telegram")) == "Telegram"
    assert booking_origin(Booking(business_id=1, start=LOCAL, channel="telegram", source="staff")) == "Telegram, записал человек"


def test_panel_pages_do_not_call_an_api_booking_manual(business, settings, rt):
    with db.new_session() as s:
        s.add(Booking(business_id=business.id, customer_name="Айбек", customer_phone="+996555123456", service="Чистка",
                      start=LOCAL + timedelta(hours=20), source="api", created_at=NOW_UTC))
        s.commit()
    with TestClient(create_app(settings, rt, init=False)) as c:
        login(c)
        for page in ("/panel", "/panel/bookings"):
            html = c.get(page).text
            row = html[html.index("Айбек"):][:600]
            assert "через API" in row and "вручную" not in row, page
        card = c.get(f"/panel/customers/{key_of('+996555123456')}").text
        line = re.sub(r"\s+", " ", card[card.index("Чистка"):]).split("</div>")[0]
        assert "через API" in line and "записал человек" not in line and "· ," not in line
