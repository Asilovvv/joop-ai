"""Every free day is in sight on the booking page (/m/<slug>/book).

The days were one row that scrolled sideways: on a 390 px phone four of six days showed, the fourth ending exactly at
the edge, with no sign that more followed (found in the fitness studio's launch walk, #301). Measured in Chromium
after the change: the row is 358 px wide for 358 px of content at 390 px, two rows of three days.
"""

import re

from fastapi.testclient import TestClient

from joop.web.app import create_app

from .test_booking_page import _open, form_clock  # noqa: F401


def test_the_days_wrap_instead_of_scrolling_sideways(business, settings, rt):
    _open(business.id)
    with TestClient(create_app(settings, rt, init=False)) as c:
        page = c.get("/m/aktish/book").text
    rule = re.search(r"\.days \{([^}]*)\}", page).group(1)
    assert "grid" in rule and "nowrap" not in rule and "overflow-x" not in rule
    assert len(re.findall(r'href="\?day=', page)) > 4  # more days than fit in one phone-wide row
