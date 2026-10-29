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
