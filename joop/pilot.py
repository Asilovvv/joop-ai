"""Pilot report: per business, the numbers a pilot is judged by, counted from the database.

These are the rows of the pilot table in the thesis (Chapter 8) and of the founder's own review:
conversations, how many customer messages came outside working hours, what the AI completed on its own
(bookings, booking requests, orders, qualified leads), what it handed to people, how often it failed to
answer, what the model cost, and whether the business pays. Demo businesses of the public site are left out.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import func
from sqlmodel import Session, select

from . import billing
from .models import Booking, Business, Lead, Message, Order, Subscription
from .niches import get_pack

DEMO_PREFIX = "site-demo-"


@dataclass
class PilotRow:
    business: str
    niche: str = ""
    active_days: int = 0  # days with at least one customer message
    conversations: int = 0
    customer_messages: int = 0
    off_hours_messages: int = 0
    ai_replies: int = 0
    bookings: int = 0  # made by the AI into free slots
    requests: int = 0  # booking requests staff confirm
    orders: int = 0
    leads: int = 0  # qualified leads (real estate, wholesale)
    handoffs: int = 0
    failures: int = 0  # the model could not answer; the customer got the fallback
    cost_usd: float = 0.0
    status: str = ""
    paying: bool = False
    _days: set = field(default_factory=set, repr=False)
    _convs: set = field(default_factory=set, repr=False)

    @property
    def completed(self) -> int:
        """What the AI finished without staff: the pilot's "leads delivered to owners"."""
        return self.bookings + self.requests + self.orders + self.leads

    @property
    def off_hours_pct(self) -> int | None:
        return round(100 * self.off_hours_messages / self.customer_messages) if self.customer_messages else None

    @property
    def cost_per_reply(self) -> float | None:
        return self.cost_usd / self.ai_replies if self.ai_replies else None


def report(session: Session, since_utc: datetime, until_utc: datetime, now_utc: datetime) -> tuple[list[PilotRow], PilotRow]:
    """Rows for businesses with customer messages in [since, until), busiest first, and a total row."""
    businesses = {b.id: b for b in session.exec(select(Business).where(Business.slug.not_like(f"{DEMO_PREFIX}%"))).all()}
    in_period = (Message.created_at >= since_utc, Message.created_at < until_utc)
    rows: dict[int, PilotRow] = {}

    def row(bid: int) -> PilotRow | None:
        if bid not in businesses:
            return None
        if bid not in rows:
            b = businesses[bid]
            rows[bid] = PilotRow(business=b.name, niche=get_pack(b.niche).label)
        return rows[bid]

    for bid, conv_id, at, off, role, cost in session.exec(select(
            Message.business_id, Message.conversation_id, Message.created_at, Message.off_hours, Message.role, Message.cost_usd,
    ).where(*in_period)).all():
        r = row(bid)
        if r is None:
            continue
        if role == "customer":
            r.customer_messages += 1
            r.off_hours_messages += 1 if off else 0
            r._days.add(at.date())
            r._convs.add(conv_id)
        elif role == "ai":
            r.ai_replies += 1
        r.cost_usd += float(cost or 0)
    for r in rows.values():
        r.active_days = len(r._days)
        r.conversations = len(r._convs)
    rows = {bid: r for bid, r in rows.items() if r.customer_messages}

    def count(model, *where) -> dict[int, int]:
        return dict(session.exec(select(model.business_id, func.count()).where(
            model.created_at >= since_utc, model.created_at < until_utc, *where).group_by(model.business_id)).all())

    for attr, counts in (
        ("bookings", count(Booking, Booking.source == "ai")),
        ("requests", count(Lead, Lead.kind == "request")),
        ("orders", count(Order)),
        ("leads", count(Lead, Lead.kind == "lead")),
        ("handoffs", count(Lead, Lead.kind == "handoff")),
        ("failures", count(Lead, Lead.kind == "error")),
    ):
        for bid, n in counts.items():
            if bid in rows:
                setattr(rows[bid], attr, n)
    subs = {s.business_id: s for s in session.exec(select(Subscription).where(Subscription.business_id.in_(list(rows) or [0]))).all()}
    for bid, r in rows.items():
        sub = subs.get(bid)
        st = billing.state(sub, now_utc) if sub else None
        r.status = st.label if st else "без подписки"
        r.paying = bool(st and st.code == "active")

    ordered = sorted(rows.values(), key=lambda r: (-r.conversations, r.business))
    total = PilotRow(business=f"Итого: {len(ordered)}")
    total.active_days = len(set().union(*(r._days for r in ordered)))  # calendar days with any customer message
    for f in ("conversations", "customer_messages", "off_hours_messages", "ai_replies", "bookings", "requests",
              "orders", "leads", "handoffs", "failures", "cost_usd"):
        setattr(total, f, sum(getattr(r, f) for r in ordered))
    total.status = f"платят: {sum(r.paying for r in ordered)}"
    total.paying = any(r.paying for r in ordered)
    return ordered, total


CSV_COLUMNS = [
    ("business", "business"), ("niche", "niche"), ("active_days", "active_days"), ("conversations", "conversations"),
    ("customer_messages", "customer_messages"), ("off_hours_messages", "off_hours_messages"), ("off_hours_pct", "off_hours_pct"),
    ("ai_replies", "ai_replies"), ("bookings", "bookings"), ("requests", "requests"), ("orders", "orders"), ("leads", "leads"),
    ("completed", "completed_by_ai"), ("handoffs", "handoffs"), ("failures", "failures"), ("cost_usd", "cost_usd"),
    ("cost_per_reply", "cost_per_reply_usd"), ("status", "status"), ("paying", "paying"),
]


def to_csv(rows: list[PilotRow], total: PilotRow) -> str:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow([name for _, name in CSV_COLUMNS])
    for r in [*rows, total]:
        values = []
        for attr, _ in CSV_COLUMNS:
            v = getattr(r, attr)
            if isinstance(v, float):
                v = f"{v:.6f}" if attr == "cost_per_reply" else f"{v:.4f}"
            values.append("" if v is None else v)
        w.writerow(values)
    return out.getvalue()

