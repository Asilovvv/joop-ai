"""Altegio integration against a fake Altegio API (httpx.MockTransport): sync, bookings, failures, panel."""

import json
import re
from datetime import timedelta

import httpx
import pytest
from sqlmodel import select

from joop import altegio, crypto, db
from joop.agent.engine import EXTERNAL_DOWN_REPLY, handle_incoming
from joop.agent.llm import AgentReply
from joop.channels.base import IncomingMessage
from joop.models import Booking, Business, Lead, Service, Slot, Staff
from joop.scheduler import run_due_jobs
from joop.timeutil import utc_to_local

from .conftest import NOW_UTC, FakeLLM
from .test_web import client, csrf_of, login  # noqa: F401  (client is a fixture)

LOC = 4242
TOKEN = "partner-SECRET-token"


class FakeAltegio:
    """Answers like the documented Online Booking endpoints and records every call."""

    def __init__(self, now_local):
        day = now_local.date() + timedelta(days=1)
        self.day = day.isoformat()
        self.services = [
            {"id": 11, "title": "Маникюр с покрытием", "price_min": 1200, "price_max": 1200, "seance_length": 3600, "active": 1},
            {"id": 12, "title": "Стрижка женская", "price_min": 800, "price_max": 1500, "seance_length": 2700, "active": 1},
        ]
        self.staff = [
            {"id": 7, "name": "Айгерим", "bookable": True, "specialization": "мастер маникюра"},
            {"id": 8, "name": "Нурия", "bookable": False, "specialization": "стилист"},
        ]
        self.times = {7: [f"{self.day}T10:00:00+06:00", f"{self.day}T12:00:00+06:00"]}
        self.check_status, self.check_body = 201, None
        self.record_status = 201
        self.calls: list[tuple[str, str, dict | None, dict]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        path = request.url.path.removeprefix("/api/v1/")
        self.calls.append((request.method, path, body, dict(request.headers)))
        ok = lambda data: httpx.Response(200, json={"success": True, "data": data, "meta": []})  # noqa: E731
        if path == f"book_services/{LOC}":
            return ok({"services": self.services, "category": [], "events": []})
        if path == f"book_staff/{LOC}":
            return ok(self.staff)
        if path == f"book_dates/{LOC}":
            return ok({"booking_dates": [self.day], "booking_days": {}, "working_dates": [self.day]})
        m = re.fullmatch(rf"book_times/{LOC}/(\d+)/([\d-]+)", path)
        if m:
            return ok([{"time": t[11:16], "seance_length": 3600, "datetime": t} for t in self.times.get(int(m.group(1)), [])])
        if path == f"book_check/{LOC}":
            return httpx.Response(self.check_status, json=self.check_body) if self.check_body else httpx.Response(self.check_status)
        if path == f"book_record/{LOC}":
            if self.record_status >= 500:
                return httpx.Response(self.record_status, text="Bad gateway")
            return httpx.Response(201, json={"success": True, "data": [{"id": 1, "record_id": 987654, "record_hash": "h"}], "meta": []})
        return httpx.Response(404, json={"success": False, "meta": {"message": "not found"}})

    def paths(self, method=None):
        return [p for m, p, _, _ in self.calls if method is None or m == method]


@pytest.fixture
def fake(business):
    with db.new_session() as s:
        b = s.get(Business, business.id)
        now_local = utc_to_local(NOW_UTC, b.timezone)
        b.altegio_location_id = LOC
        s.add(b)
        s.commit()
    return FakeAltegio(now_local)


def make_client(fake):
    return altegio.AltegioClient(httpx.Client(transport=httpx.MockTransport(fake.handler)), TOKEN,
                                 "https://api.alteg.io/api/v1", min_interval=0)


def synced(business, fake):
    with db.new_session() as s:
        b = s.get(Business, business.id)
        res = altegio.sync(s, b, make_client(fake), NOW_UTC)
        s.commit()
        return res


def altegio_slot(business, hour="10:00"):
    with db.new_session() as s:
        member = s.exec(select(Staff).where(Staff.business_id == business.id, Staff.external_id == "7")).one()
        return next(x for x in s.exec(select(Slot).where(Slot.staff_id == member.id)).all() if x.start.strftime("%H:%M") == hour)


def book(business, fake, slot_id, service="маникюр с покрытием", ext="1"):
    llm = FakeLLM([AgentReply("Записала!", booking={"slot_id": slot_id, "name": "Айбек", "phone": "0555 123 456", "service": service})])
    incoming = IncomingMessage("telegram", "5001", "text", "Запишите на маникюр, Айбек, 0555 123 456", "Айбек", f"tg:{slot_id}:{ext}")
    with db.new_session() as s:
        b = s.get(Business, business.id)
        out = handle_incoming(s, b, incoming, lambda: llm, NOW_UTC, get_altegio=lambda _b: make_client(fake))
        s.commit()
        return out


def test_client_uses_the_documented_headers_and_reads_data(fake):
    c = make_client(fake)
    assert [s["title"] for s in c.services(LOC)] == ["Маникюр с покрытием", "Стрижка женская"]
    headers = fake.calls[0][3]
    assert headers["authorization"] == f"Bearer {TOKEN}" and headers["accept"] == "application/vnd.api.v2+json"
    assert fake.calls[0][1] == f"book_services/{LOC}"


def test_sync_copies_prices_team_and_free_times(business, fake):
    res = synced(business, fake)
    assert (res.services, res.staff, res.slots_added) == (2, 2, 2)
    with db.new_session() as s:
        services = {x.external_id: x for x in s.exec(select(Service).where(Service.business_id == business.id)).all()}
        assert (services["11"].name, services["11"].price, services["11"].price_value) == ("Маникюр с покрытием", "1 200", 1200)
        assert services["12"].price == "от 800 до 1 500" and services["12"].price_value is None
        # The niche's sample price list and team are switched off: only what Altegio knows is offered.
        assert not any(x.available for x in services.values() if not x.external_id)
        staff = {x.external_id: x for x in s.exec(select(Staff).where(Staff.business_id == business.id)).all()}
        assert staff["7"].active and not staff["8"].active and not any(x.active for x in staff.values() if not x.external_id)
        slots = s.exec(select(Slot).where(Slot.staff_id == staff["7"].id).order_by(Slot.start)).all()
        assert [x.start.strftime("%H:%M") for x in slots] == ["10:00", "12:00"] and slots[0].duration_min == 60
    # Next sync: 12:00 was booked in Altegio by phone, 15:00 opened; the local copy follows.
    fake.times[7] = [f"{fake.day}T10:00:00+06:00", f"{fake.day}T15:00:00+06:00"]
    res = synced(business, fake)
    assert (res.slots_added, res.slots_removed) == (1, 1)
    with db.new_session() as s:
        b = s.get(Business, business.id)
        assert b.altegio_synced_at == NOW_UTC and b.altegio_error == ""


def test_booking_is_checked_by_code_then_by_altegio_then_recorded(business, fake):
    synced(business, fake)
    slot = altegio_slot(business)
    out = book(business, fake, slot.id)
    assert out.booking_id is not None and out.reply == "Записала!"
    posts = [(p, b) for m, p, b, _ in fake.calls if m == "POST"]
    assert [p for p, _ in posts] == [f"book_check/{LOC}", f"book_record/{LOC}"]  # check first, then record
    appointment = posts[1][1]["appointments"][0]
    assert appointment == {"id": 1, "staff_id": 7, "datetime": f"{fake.day}T10:00:00+06:00", "services": [11]}
    assert posts[1][1]["phone"] == "+996555123456" and posts[1][1]["fullname"] == "Айбек"
    with db.new_session() as s:
        booking = s.get(Booking, out.booking_id)
        assert booking.external_id == "987654" and s.get(Slot, slot.id).status == "booked"


def test_a_slot_the_code_rejects_never_reaches_altegio(business, fake):
    synced(business, fake)
    slot = altegio_slot(business)
    book(business, fake, slot.id)
    before = len(fake.paths("POST"))
    out = book(business, fake, slot.id, ext="2")  # the same slot again: Joop's own check refuses it
    assert out.booking_id is None and "занято" in out.reply and len(fake.paths("POST")) == before


def test_taken_in_altegio_offers_other_times_and_closes_the_slot(business, fake):
    synced(business, fake)
    slot = altegio_slot(business)
    fake.check_status, fake.check_body = 422, {"success": False, "meta": {"message": "Время занято", "code": 433}}
    out = book(business, fake, slot.id)
    assert out.booking_id is None and "занято" in out.reply and "12:00" in out.reply
    assert fake.paths("POST") == [f"book_check/{LOC}"]  # nothing was recorded
    with db.new_session() as s:
        assert s.get(Slot, slot.id).status == "booked"  # not offered again


def test_altegio_down_turns_the_booking_into_a_request_for_staff(business, fake):
    synced(business, fake)
    slot = altegio_slot(business)
    fake.record_status = 502
    out = book(business, fake, slot.id)
    assert out.booking_id is None and out.request_id is not None and out.reply == EXTERNAL_DOWN_REPLY
    with db.new_session() as s:
        assert s.get(Slot, slot.id).status == "free"  # released for the next try
        lead = s.get(Lead, out.request_id)
        assert lead.kind == "request" and "10:00" in lead.summary
        assert s.exec(select(Booking).where(Booking.business_id == business.id, Booking.external_id != "")).first() is None


def test_unknown_error_code_is_not_treated_as_taken(fake):
    err = altegio.AltegioError(422, 432, "wrong SMS code")  # the salon requires SMS confirmation
    assert not err.taken and altegio.AltegioError(422, 433).taken


def test_scheduler_syncs_every_ten_minutes(business, fake, rt):
    rt.altegio = lambda b: make_client(fake)
    with db.new_session() as s:
        b = s.get(Business, business.id)
        assert run_due_jobs(s, rt, b, NOW_UTC)["altegio"] is True
        s.commit()
    n = len(fake.calls)
    with db.new_session() as s:
        b = s.get(Business, business.id)
        assert "altegio" not in run_due_jobs(s, rt, b, NOW_UTC + timedelta(minutes=5))
        assert run_due_jobs(s, rt, b, NOW_UTC + timedelta(minutes=10))["altegio"] is True
    assert len(fake.calls) > n


def test_scheduler_keeps_the_error_for_the_panel(business, fake, rt):
    rt.altegio = lambda b: altegio.AltegioClient(httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(500, text="down"))), TOKEN, min_interval=0)
    with db.new_session() as s:
        b = s.get(Business, business.id)
        assert run_due_jobs(s, rt, b, NOW_UTC)["altegio"] is False
        s.commit()
        assert "Altegio не ответил (500)" in s.get(Business, business.id).altegio_error


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", crypto.new_key())
    crypto.reset_key_cache()
    yield
    crypto.reset_key_cache()


def test_panel_connects_altegio_and_never_shows_the_key(client, business, rt, key):  # noqa: F811
    from sqlalchemy import text

    fake = FakeAltegio(utc_to_local(NOW_UTC, "Asia/Bishkek"))
    rt.altegio = lambda b: make_client(fake) if b.altegio_location_id else None
    token = login(client)
    assert "Укажите ID филиала" in client.post("/panel/altegio", data={"location_id": "", "token": TOKEN, "csrf": token}).text
    page = client.post("/panel/altegio", data={"location_id": f" {LOC} ", "token": TOKEN, "csrf": token}).text
    assert "Altegio подключён: услуг 2, сотрудников 2" in page and TOKEN not in page and "SECRET" not in page
    with db.get_engine().connect() as conn:
        raw = conn.execute(text("select altegio_token from business where id = :i"), {"i": business.id}).scalar()
    assert raw.startswith("enc:v1:") and "SECRET" not in raw  # encrypted at rest
    with db.new_session() as s:
        b = s.get(Business, business.id)
        assert b.altegio_location_id == LOC and b.altegio_token == TOKEN and b.altegio_synced_at is None
    assert fake.paths() == [f"book_services/{LOC}", f"book_staff/{LOC}"]  # times are left to the scheduler
    client.post("/panel/altegio", data={"location_id": str(LOC), "action": "disconnect", "csrf": csrf_of(page)})
    with db.new_session() as s:
        assert s.get(Business, business.id).altegio_location_id == 0


def test_a_visit_cancelled_in_altegio_is_closed_in_joop_and_its_time_offered_again(business, fake):
    synced(business, fake)
    slot = altegio_slot(business)
    out = book(business, fake, slot.id)  # booked at NOW_UTC; Altegio now lists only 12:00 as free
    fake.times[7] = [f"{fake.day}T12:00:00+06:00"]
    with db.new_session() as s:
        res = altegio.sync(s, s.get(Business, business.id), make_client(fake), NOW_UTC + timedelta(minutes=10))
        s.commit()
    assert res.released == 0 and s.get(Booking, out.booking_id).status == "booked"
    # Staff cancelled the visit in Altegio: 10:00 is free there again.
    fake.times[7] = [f"{fake.day}T10:00:00+06:00", f"{fake.day}T12:00:00+06:00"]
    with db.new_session() as s:
        res = altegio.sync(s, s.get(Business, business.id), make_client(fake), NOW_UTC + timedelta(minutes=20))
        s.commit()
    assert res.released == 1
    with db.new_session() as s:
        assert s.get(Booking, out.booking_id).status == "cancelled"
        assert (s.get(Slot, slot.id).status, s.get(Slot, slot.id).taken) == ("free", 0)


def test_a_booking_newer_than_the_times_read_is_not_released(business, fake):
    synced(business, fake)
    slot = altegio_slot(business)
    out = book(business, fake, slot.id)  # created at NOW_UTC
    with db.new_session() as s:  # a sync that read the times just before the booking was recorded
        res = altegio.sync(s, s.get(Business, business.id), make_client(fake), NOW_UTC + timedelta(seconds=30))
        s.commit()
    assert res.released == 0
    with db.new_session() as s:
        assert s.get(Booking, out.booking_id).status == "booked" and s.get(Slot, slot.id).status == "booked"
