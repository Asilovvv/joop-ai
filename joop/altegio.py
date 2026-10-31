"""Altegio integration: a salon that keeps its schedule in Altegio connects Joop AI with its location ID.

Altegio (alteg.io) is an online booking system for salons and clinics. Joop uses its public Online Booking
API (https://developer.alteg.io/en/public/openapi), the one booking widgets use: it needs only a partner
token, no access to the salon's account. Facts from the documentation this module relies on:

- base URL https://api.alteg.io/api/v1, header `Authorization: Bearer <partner_token>`,
  `Accept: application/vnd.api.v2+json`; limit 200 requests a minute or 5 a second per IP;
- GET book_services/{location} -> services (id, title, price_min, price_max, seance_length);
  GET book_staff/{location} -> team members (id, name, bookable, specialization);
  GET book_dates/{location}?staff_id= -> booking_dates; GET book_times/{location}/{staff}/{date} -> time slots
  (time, seance_length in seconds, datetime in ISO 8601);
- POST book_check/{location} with appointments [{id, services, staff_id, datetime}] -> 201 when valid,
  422 otherwise (433 slot taken, 436 no team member free, 437 overlap in the request, 438 service gone);
- POST book_record/{location} with phone, fullname, appointments, comment, api_id -> [{id, record_id, record_hash}];
  422 also for a bad phone (431), a wrong SMS code (432) and a missing name (435).

How Joop uses it, keeping the rule "the model proposes, the code decides":
- `sync` copies the price list, the team and the free times for the next days into Joop's own tables, so the
  prompt, the slot list and every check work exactly as for any other business;
- after Joop's code has checked and claimed a slot, `push_booking` asks Altegio to check it again and only then
  creates the record. A slot Altegio reports as taken is closed in Joop and the customer gets other times; if
  Altegio does not answer, the booking becomes a request that staff confirm (engine.py).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import httpx
from sqlmodel import Session, select

from .models import Business, Service, Slot, Staff
from .timeutil import get_tz, utc_to_local

log = logging.getLogger(__name__)

ACCEPT = "application/vnd.api.v2+json"
SYNC_DAYS = 7  # free times copied ahead; matches the week of slots the prompt shows
SYNC_EVERY = timedelta(minutes=10)
MIN_INTERVAL = 0.25  # seconds between calls: Altegio allows 5 a second per IP
MAX_CALLS = 120  # one sync never takes more than this (200 a minute is the documented limit)
TAKEN_CODES = {433, 436, 437, 438}  # the time or the service is no longer available (book_check, book_record)


class AltegioError(Exception):
    def __init__(self, status: int, code: int | None = None, message: str = "") -> None:
        super().__init__(f"Altegio {status}" + (f"/{code}" if code else "") + (f": {message}" if message else ""))
        self.status, self.code, self.message = status, code, message

    @property
    def taken(self) -> bool:
        return self.status == 422 and self.code in TAKEN_CODES


class AltegioClient:
    def __init__(self, http: httpx.Client, token: str, base_url: str = "https://api.alteg.io/api/v1",
                 min_interval: float = MIN_INTERVAL) -> None:
        self.http, self.base_url, self.min_interval = http, base_url.rstrip("/"), min_interval
        self._headers = {"Authorization": f"Bearer {token}", "Accept": ACCEPT, "Content-Type": "application/json"}
        self._last = 0.0
        self.calls = 0

    def _request(self, method: str, path: str, params: dict | None = None, body: dict | None = None) -> Any:
        wait = self._last + self.min_interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        self.calls += 1
        try:
            r = self.http.request(method, f"{self.base_url}/{path}", params=params, json=body, headers=self._headers, timeout=15.0)
        except httpx.HTTPError as exc:
            raise AltegioError(0, None, type(exc).__name__) from exc
        payload: Any = None
        if r.content:
            try:
                payload = r.json()
            except ValueError:
                payload = None
        if r.status_code >= 400 or (isinstance(payload, dict) and payload.get("success") is False):
            raise AltegioError(r.status_code, _error_code(payload), _error_message(payload))
        return payload.get("data") if isinstance(payload, dict) else payload

    def services(self, location: int) -> list[dict]:
        data = self._request("GET", f"book_services/{location}") or {}
        return list(data.get("services") or []) if isinstance(data, dict) else []

    def staff(self, location: int) -> list[dict]:
        return list(self._request("GET", f"book_staff/{location}") or [])

    def dates(self, location: int, staff_id: int) -> list[str]:
        data = self._request("GET", f"book_dates/{location}", params={"staff_id": staff_id}) or {}
        return [str(d) for d in (data.get("booking_dates") or [])] if isinstance(data, dict) else []

    def times(self, location: int, staff_id: int, day: str) -> list[dict]:
        return list(self._request("GET", f"book_times/{location}/{staff_id}/{day}") or [])

    def check(self, location: int, appointments: list[dict]) -> None:
        self._request("POST", f"book_check/{location}", body={"appointments": appointments})

    def record(self, location: int, phone: str, fullname: str, appointments: list[dict], comment: str, api_id: str) -> list[dict]:
        body = {"phone": phone, "fullname": fullname, "appointments": appointments, "comment": comment, "api_id": api_id}
        return list(self._request("POST", f"book_record/{location}", body=body) or [])


def _error_code(payload: Any) -> int | None:
    """The documented error codes (433 and so on); where they sit in the body is not specified, so look around."""
    if not isinstance(payload, dict):
        return None
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    errors = payload.get("errors") if isinstance(payload.get("errors"), dict) else {}
    for value in (payload.get("code"), meta.get("code"), errors.get("code"), (meta.get("errors") or {}).get("code")
                  if isinstance(meta.get("errors"), dict) else None):
        try:
            if value is not None:
                return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _error_message(payload: Any) -> str:
    if isinstance(payload, dict):
        meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
        return str(meta.get("message") or payload.get("message") or "")[:300]
    return ""


# --- sync ------------------------------------------------------------------------------------------


@dataclass
class SyncResult:
    services: int = 0
    staff: int = 0
    slots_added: int = 0
    slots_removed: int = 0


def _price(item: dict) -> tuple[str, int | None]:
    def num(x: Any) -> int:
        try:
            return int(round(float(x or 0)))
        except (TypeError, ValueError):
            return 0

    low, high = num(item.get("price_min")), num(item.get("price_max"))
    fmt = lambda n: f"{n:,}".replace(",", " ")  # noqa: E731
    if not low and not high:
        return "", None
    if not high or high == low:
        return fmt(low or high), low or high
    return f"от {fmt(low)} до {fmt(high)}", None


def _local(value: str, tz: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.astimezone(get_tz(tz)).replace(tzinfo=None) if dt.tzinfo else dt


def sync(session: Session, business: Business, client: AltegioClient, now_utc: datetime, days: int = SYNC_DAYS,
         with_slots: bool = True) -> SyncResult:
    """Copy services, team members and free times from Altegio. Bookings already made in Joop are kept.

    The price list and the team come from Altegio only: entries typed in Joop before (the niche's sample data)
    are switched off, so the AI never offers a service or a specialist the salon's system does not know."""
    loc = business.altegio_location_id
    res = SyncResult()

    services = client.services(loc)
    current = {s.external_id: s for s in session.exec(select(Service).where(
        Service.business_id == business.id, Service.external_id != "")).all()}
    seen: set[str] = set()
    for i, item in enumerate(services):
        ext = str(item.get("id") or "")
        if not ext or not item.get("title"):
            continue
        seen.add(ext)
        row = current.get(ext) or Service(business_id=business.id, name="", external_id=ext)
        row.name = str(item["title"])[:200]
        row.price, row.price_value = _price(item)
        row.note = str(item.get("comment") or "")[:300]
        row.available = item.get("active", 1) not in (0, False, "0")
        row.sort = i
        session.add(row)
        res.services += 1
    for ext, row in current.items():
        if ext not in seen:
            row.available = False  # removed in Altegio: the AI stops offering it
            session.add(row)
    for row in session.exec(select(Service).where(Service.business_id == business.id, Service.external_id == "")).all():
        row.available = False
        session.add(row)

    people = {p.external_id: p for p in session.exec(select(Staff).where(
        Staff.business_id == business.id, Staff.external_id != "")).all()}
    active: list[Staff] = []
    listed: set[str] = set()
    for item in client.staff(loc):
        ext = str(item.get("id") or "")
        if not ext or not item.get("name"):
            continue
        listed.add(ext)
        row = people.get(ext) or Staff(business_id=business.id, name="", external_id=ext)
        row.name = str(item["name"])[:120]
        row.role = str(item.get("specialization") or "")[:120]
        row.active = bool(item.get("bookable", True))
        session.add(row)
        if row.active:
            active.append(row)
        res.staff += 1
    for ext, row in people.items():
        if ext not in listed:
            row.active = False
            session.add(row)
    for row in session.exec(select(Staff).where(Staff.business_id == business.id, Staff.external_id == "")).all():
        row.active = False  # its slots are no longer offered: free_slots lists active staff only
        session.add(row)
    session.flush()
    if not with_slots:
        return res

    now_local = utc_to_local(now_utc, business.timezone)
    last_day = now_local.date() + timedelta(days=days)
    for member in active:
        if client.calls >= MAX_CALLS:
            log.warning("Altegio sync for %s stopped at %s calls", business.slug, client.calls)
            break
        wanted: dict[datetime, int] = {}
        for day in client.dates(loc, int(member.external_id)):
            try:
                d = date.fromisoformat(day[:10])
            except ValueError:
                continue
            if not now_local.date() <= d <= last_day or client.calls >= MAX_CALLS:
                continue
            for t in client.times(loc, int(member.external_id), d.isoformat()):
                start = _local(t.get("datetime") or "", business.timezone)
                if start is not None and start > now_local:
                    wanted[start] = max(5, int(t.get("seance_length") or 3600) // 60)
        added, removed = _reconcile(session, business, member, wanted, now_local, last_day)
        res.slots_added += added
        res.slots_removed += removed

    business.altegio_synced_at = now_utc
    business.altegio_error = ""
    session.add(business)
    return res


def _reconcile(session: Session, business: Business, member: Staff, wanted: dict[datetime, int], now_local: datetime,
               last_day: date) -> tuple[int, int]:
    """Make Joop's free slots of one team member equal to Altegio's free times; booked slots stay as they are."""
    rows = session.exec(select(Slot).where(
        Slot.business_id == business.id, Slot.staff_id == member.id, Slot.start > now_local,
        Slot.start < datetime.combine(last_day + timedelta(days=1), datetime.min.time()))).all()
    have = {r.start: r for r in rows}
    removed = 0
    for start, row in have.items():
        if start not in wanted and row.status == "free" and row.taken == 0:
            session.delete(row)
            removed += 1
    added = 0
    for start, minutes in wanted.items():
        if start not in have:
            session.add(Slot(business_id=business.id, staff_id=member.id, start=start, duration_min=minutes))
            added += 1
        elif have[start].status == "free":
            have[start].duration_min = minutes
            session.add(have[start])
    return added, removed


def due(business: Business, now_utc: datetime) -> bool:
    return bool(business.altegio_location_id) and (
        business.altegio_synced_at is None or now_utc - business.altegio_synced_at >= SYNC_EVERY)


# --- bookings --------------------------------------------------------------------------------------


def _service_id(session: Session, business: Business, text: str) -> int | None:
    """The Altegio id of the service the customer named, when it matches one service unambiguously."""
    words = " ".join((text or "").casefold().split())
    if not words:
        return None
    rows = session.exec(select(Service).where(Service.business_id == business.id, Service.external_id != "",
                                              Service.available == True)).all()  # noqa: E712
    exact = [r for r in rows if r.name.casefold() == words]
    near = exact or [r for r in rows if words in r.name.casefold() or r.name.casefold() in words]
    return int(near[0].external_id) if len(near) == 1 else None


def push_booking(session: Session, business: Business, client: AltegioClient, slot: Slot, member: Staff,
                 service: str, name: str, phone: str, api_id: str) -> str:
    """Check the slot in Altegio, then create the record there. Returns the Altegio record id.

    Raises AltegioError: `.taken` when Altegio says the time or the service is no longer available."""
    start = slot.start.replace(tzinfo=get_tz(business.timezone)).isoformat()
    appointment: dict[str, Any] = {"id": 1, "staff_id": int(member.external_id), "datetime": start}
    sid = _service_id(session, business, service)
    if sid is not None:
        appointment["services"] = [sid]
    loc = business.altegio_location_id
    client.check(loc, [appointment])
    comment = "Joop AI" + (f": {service}" if service else "")
    created = client.record(loc, phone, name, [appointment], comment[:200], api_id)
    record = next((c for c in created if isinstance(c, dict) and c.get("record_id")), None)
    if record is None:
        raise AltegioError(201, None, "no record_id in the answer")
    return str(record["record_id"])
