"""«Пустые окна», /today and /gaps count only the times customers can book.

The sign-up example's people are nobody: the AI never offers or books their times, and the dashboard and the launch
checklist already leave them out (#214, #224). gaps.week counted them, so a new business read «Свободных окон на
7 дней: 135 из 135» in Telegram and on the panel page while not one of them could be booked."""

import re
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlmodel import select

from joop import db, gaps, owner_commands
from joop.models import Business, Slot, Staff
from joop.presets import create_business
from joop.timeutil import utc_to_local
from joop.web.app import create_app

from .conftest import NOW_UTC
from .test_web import csrf_of


def _fresh() -> int:
    with db.new_session() as s:
        b = create_business(s, slug="fresh", name="Свежая", password="fresh-pass", niche="dental", demo=True, now_utc=NOW_UTC)
        s.commit()
        return b.id


def _own_master_with_three_free_times(business_id: int) -> None:
    with db.new_session() as s:
        b = s.get(Business, business_id)
        master = Staff(business_id=business_id, name="Бакыт Осмонов", role="терапевт")
        s.add(master)
        s.commit()
        tomorrow = utc_to_local(NOW_UTC, b.timezone).replace(hour=10, minute=0, second=0, microsecond=0) + timedelta(days=1)
        for h in range(3):
            s.add(Slot(business_id=business_id, staff_id=master.id, start=tomorrow + timedelta(hours=h)))
        s.commit()


def _answer(business_id: int, command: str) -> str:
    with db.new_session() as s:
        return owner_commands.answer(s, s.get(Business, business_id), command, NOW_UTC)


def test_a_new_business_has_no_bookable_windows_yet(engine):
    bid = _fresh()
    with db.new_session() as s:
        b = s.get(Business, bid)
        assert s.exec(select(Slot).where(Slot.business_id == bid)).first() is not None  # the example's times exist
        assert gaps.week(s, b, utc_to_local(NOW_UTC, b.timezone)) == []
    assert _answer(bid, "/gaps").startswith("Свободных окон на 7 дней: 0 из 0.")
    assert _answer(bid, "/today").endswith("Свободных окон: сегодня 0, на 7 дней 0.")


def test_only_the_owners_own_people_are_counted(engine):
    bid = _fresh()
    _own_master_with_three_free_times(bid)  # the example's three doctors are still there
    assert _answer(bid, "/gaps").startswith("Свободных окон на 7 дней: 3 из 3.")
    assert _answer(bid, "/today").endswith("на 7 дней 3.")


def test_the_panel_page_counts_the_same(settings, rt, engine):
    bid = _fresh()
    _own_master_with_three_free_times(bid)
    with TestClient(create_app(settings, rt, init=False)) as c:
        c.post("/login", data={"slug": "fresh", "password": "fresh-pass", "csrf": csrf_of(c.get("/login").text)})
        page = re.sub(r"\s+", " ", c.get("/panel/gaps").text)
    assert "<b>3</b><span>свободных окон на 7 дней из 3</span>" in page
