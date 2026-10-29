"""Time slots: creating them, listing free ones, claiming one for a booking."""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta

from sqlalchemy import update
from sqlmodel import Session, select

from .models import Business, Slot, Staff
from .timeutil import parse_days_off, parse_hhmm

MAX_GENERATE_DAYS = 62
LEAD_MINUTES = 60  # do not offer slots that start within the next hour


def parse_times(text: str) -> list[time]:
    """'10:00, 11.30 15' -> [10:00, 11:30, 15:00]"""
    result: list[time] = []
    for part in re.split(r"[,;\s]+", text or ""):
        parsed = parse_hhmm(part)
        if parsed is not None and parsed not in result:
            result.append(parsed)
    return sorted(result)


def _existing_starts(session: Session, business_id: int, staff_id: int, day_from: date, day_to: date) -> set[datetime]:
    rows = session.exec(
        select(Slot.start).where(
            Slot.business_id == business_id,
            Slot.staff_id == staff_id,
            Slot.start >= datetime.combine(day_from, time.min),
            Slot.start <= datetime.combine(day_to, time.max),
        )
    ).all()
    return set(rows)


def add_slots(session: Session, business: Business, staff_id: int, day: date, times: list[time], duration_min: int = 60) -> int:
    existing = _existing_starts(session, business.id, staff_id, day, day)
    created = 0
    for t in times:
        start = datetime.combine(day, t)
        if start in existing:
            continue
        session.add(Slot(business_id=business.id, staff_id=staff_id, start=start, duration_min=duration_min))
        created += 1
    return created


def generate_slots(
    session: Session,
    business: Business,
    staff_id: int,
    date_from: date,
    date_to: date,
    start: time,
    end: time,
    step_min: int = 60,
    skip_days_off: bool = True,
) -> int:
    """Create slots every `step_min` minutes between `start` and `end` for each day in the range."""
    if step_min < 10 or date_to < date_from:
        return 0
    date_to = min(date_to, date_from + timedelta(days=MAX_GENERATE_DAYS))
    days_off = parse_days_off(business.days_off) if skip_days_off else set()
    existing = _existing_starts(session, business.id, staff_id, date_from, date_to)
    created = 0
    day = date_from
    while day <= date_to:
        if day.isoweekday() not in days_off:
            current = datetime.combine(day, start)
            day_end = datetime.combine(day, end)
            while current + timedelta(minutes=step_min) <= day_end:
                if current not in existing:
                    session.add(Slot(business_id=business.id, staff_id=staff_id, start=current, duration_min=step_min))
                    created += 1
                current += timedelta(minutes=step_min)
        day += timedelta(days=1)
    return created


def free_slots(
    session: Session,
    business_id: int,
    now_local: datetime,
    days: int = 10,
    limit: int = 200,
    staff_id: int | None = None,
) -> list[tuple[Slot, Staff]]:
    query = (
        select(Slot, Staff)
        .join(Staff, Staff.id == Slot.staff_id)
        .where(
            Slot.business_id == business_id,
            Slot.status == "free",
            Staff.active == True,  # noqa: E712
            Slot.start > now_local + timedelta(minutes=LEAD_MINUTES),
            Slot.start <= now_local + timedelta(days=days),
        )
    )
    if staff_id is not None:
        query = query.where(Slot.staff_id == staff_id)
    return list(session.exec(query.order_by(Slot.start, Slot.id).limit(limit)).all())


def claim_slot(session: Session, slot_id: int) -> bool:
    """Atomically mark a free slot as booked. False if someone took it first."""
    result = session.exec(update(Slot).where(Slot.id == slot_id, Slot.status == "free").values(status="booked"))
    return result.rowcount == 1


def release_slot(session: Session, slot_id: int | None) -> None:
    if slot_id is None:
        return
    session.exec(update(Slot).where(Slot.id == slot_id).values(status="free"))


# --- the time a customer named in their own words ------------------------------------------------

_DAY_WORDS = (
    (re.compile(r"послезавтра|бүрсүгүнү|бурсугуну", re.I), 2),
    (re.compile(r"завтра|эртең|эртен", re.I), 1),
    (re.compile(r"сегодня|бүгүн|бугун", re.I), 0),
)
_TIMES = (
    re.compile(r"\b([01]?\d|2[0-3])[:.]([0-5]\d)\b"),  # 18:00, 9.30
    re.compile(r"(?:саат|в|к|на)\s+([01]?\d|2[0-3])\b(?![:.,]?\d)(?!\s*(?:человек|чел|киши|гост|адам|орун|мест))", re.I),
    re.compile(r"\b([01]?\d|2[0-3])\s?-?(?:да|де|до|дө|та|те|то|тө|ге|га|ке|ка|гө|го)\b", re.I),  # 10до, 12де
)

_EVENING = re.compile(r"вечер|кечинде|кечки|кечкурун", re.I)


def requested_time(text: str, today: date) -> datetime | None:
    """'Завтра в 18:00' / 'эртең саат 10до' -> that day and time. None when the day or the time is missing."""
    day = next((today + timedelta(days=shift) for pattern, shift in _DAY_WORDS if pattern.search(text)), None)
    if day is None:
        return None
    for pattern in _TIMES:
        m = pattern.search(text)
        if m:
            hour = int(m.group(1))
            if hour < 12 and _EVENING.search(text):
                hour += 12
            minute = int(m.group(2)) if m.lastindex and m.lastindex >= 2 else 0
            if 7 <= hour <= 23:
                return datetime.combine(day, time(hour, minute))
    return None
