"""The sales funnel for requests: new → contacted → booked → visited, or lost — moved by the AI, not by hand.

amoCRM and Bitrix24 sell "воронки продаж": a board where a manager drags each lead through stages. In a salon
nobody drags anything, so Joop moves the stages itself from what it already knows: a staff reply in the chat
means «связались»; a booking or an order in the same conversation after the request means «записан»; the booking's
time passing without a cancellation means «пришёл». Only «потерян» is a person's call (one button). The funnel
page shows the last 30 days by stage with the two conversions that matter: how many requests became bookings,
how many bookings became visits. `Lead.status` (new / done) stays what it was — "someone handled it".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlmodel import Session, select

from .models import Booking, Business, Lead, Order
from .stats import not_test
from .timeutil import utc_to_local

STAGES = ("new", "contacted", "booked", "visited", "lost")
LABELS = {"new": "Новая", "contacted": "Связались", "booked": "Записан", "visited": "Пришёл", "lost": "Потерян"}
KINDS = ("request", "lead", "handoff")  # what a funnel is about; media and error leads are not sales
WINDOW = timedelta(days=30)


def advance(session: Session, business: Business, now_utc: datetime) -> int:
    """Move stages from the facts in the database. Returns how many leads moved."""
    now_local = utc_to_local(now_utc, business.timezone)
    moved = 0
    leads = session.exec(select(Lead).where(Lead.business_id == business.id, Lead.kind.in_(KINDS), Lead.stage.in_(["new", "contacted", "booked"]),
                                           Lead.conversation_id != None, Lead.created_at >= now_utc - WINDOW)).all()  # noqa: E711
    for lead in leads:
        booking = session.exec(select(Booking).where(Booking.business_id == business.id, Booking.conversation_id == lead.conversation_id,
                                                     Booking.created_at >= lead.created_at,
                                                     Booking.status == "booked").order_by(Booking.start)).first()
        order = None if booking else session.exec(select(Order).where(Order.business_id == business.id, Order.conversation_id == lead.conversation_id,
                                                                       Order.created_at >= lead.created_at,
                                                                       Order.status != "cancelled")).first()
        if lead.stage in ("new", "contacted") and (booking or order):
            lead.stage = "booked"
            session.add(lead)
            moved += 1
        if lead.stage == "booked" and booking and booking.start < now_local:
            lead.stage = "visited"
            session.add(lead)
            moved += 1
    return moved


def contacted(session: Session, conversation_id: int) -> None:
    """A person answered in this chat: every new request there is «связались»."""
    for lead in session.exec(select(Lead).where(Lead.conversation_id == conversation_id, Lead.stage == "new", Lead.kind.in_(KINDS))).all():
        lead.stage = "contacted"
        session.add(lead)


@dataclass
class Funnel:
    counts: dict[str, int]
    rows: dict[str, list[Lead]]
    total: int

    @property
    def booked_pct(self) -> int | None:
        done = self.counts["booked"] + self.counts["visited"]
        return round(100 * done / self.total) if self.total else None

    @property
    def visited_pct(self) -> int | None:
        done = self.counts["booked"] + self.counts["visited"]
        return round(100 * self.counts["visited"] / done) if done else None


def report(session: Session, business: Business, now_utc: datetime) -> Funnel:
    since = now_utc - WINDOW
    leads = session.exec(select(Lead).where(Lead.business_id == business.id, Lead.kind.in_(KINDS), not_test(Lead),
                                           Lead.created_at >= since).order_by(Lead.id.desc())).all()
    rows = {stage: [x for x in leads if x.stage == stage] for stage in STAGES}
    return Funnel(counts={k: len(v) for k, v in rows.items()}, rows=rows, total=len(leads))
