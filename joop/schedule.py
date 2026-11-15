"""Closing and reopening times by hand: a doctor is ill, a master leaves at three, a table is under repair.

Until now staff could only mark single times busy, one click each, and a busy time became free again as soon as a
booking on it was cancelled or moved — so after staff moved the patients of an ill doctor, the AI booked new ones
into her day. A closed time (Slot.status "closed") is different: nothing claims it (claim_slot wants "free"),
release_slot keeps it closed, and only staff open it again. Closing keeps the bookings already made; they are
returned so staff move or cancel them, since their customers do not know yet. Reopening offers the time to the
waiting list, as a cancellation does.

Times of a person whose schedule comes from Altegio are refused: Altegio's sync would open them again.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from sqlmodel import Session, select

from . import waitlist
from .models import Booking, Business, Slot, Staff
from .slots import CLOSED

if TYPE_CHECKING:
    from .runtime import Runtime

ALTEGIO = "Расписание этого сотрудника берётся из Altegio: закройте или откройте время там, Joop подхватит это сам."


@dataclass
class Changed:
    count: int = 0  # times closed or opened
    bookings: list[Booking] = field(default_factory=list)  # bookings left in closed times: staff move or cancel them
    offered: int = 0  # waiting-list customers told about reopened times
    problem: str = ""


def from_altegio(business: Business, member: Staff) -> bool:
    return bool(business.altegio_location_id and member.external_id)


def _active(s: Session, slots: list[Slot]) -> list[Booking]:
    ids = [x.id for x in slots]
    return list(s.exec(select(Booking).where(Booking.slot_id.in_(ids or [0]), Booking.status == "booked")
                       .order_by(Booking.start, Booking.id)).all())


def _busy_by_hand(s: Session, slot: Slot) -> bool:
    """Staff marked it busy themselves (a customer booked by phone): no seats taken through Joop, no booking."""
    return slot.status == "booked" and slot.taken == 0 and not _active(s, [slot])


def close(s: Session, business: Business, member: Staff, slots: list[Slot], now_local: datetime) -> Changed:
    """Close the times that have not started yet; the bookings already on them stay and are returned."""
    if from_altegio(business, member):
        return Changed(problem=ALTEGIO)
    ahead = [x for x in slots if x.start > now_local]
    out = Changed()
    for slot in ahead:
        if _busy_by_hand(s, slot):
            continue  # a phone customer's time: closing and reopening the day must not turn it free
        if slot.status != CLOSED:
            slot.status = CLOSED
            s.add(slot)
            out.count += 1
    s.flush()
    out.bookings = _active(s, ahead)
    return out


def reopen(s: Session, rt: "Runtime", business: Business, member: Staff, slots: list[Slot], now_local: datetime,
           now_utc: datetime, busy_too: bool = False) -> Changed:
    """Open closed times again (and, with `busy_too`, times marked busy without a booking); free ones go to the
    waiting list."""
    if from_altegio(business, member):
        return Changed(problem=ALTEGIO)
    out = Changed()
    for slot in (x for x in slots if x.start > now_local):
        busy = busy_too and _busy_by_hand(s, slot)
        if slot.status != CLOSED and not busy:
            continue
        slot.status = "booked" if slot.taken >= slot.seats else "free"  # a closed time with its booking: taken again
        s.add(slot)
        s.flush()
        out.count += 1
        if slot.status == "free":
            out.offered += waitlist.offer_freed_slot(s, rt, business, slot, now_utc)
    return out
