"""Pilot report: per business, the numbers a pilot is judged by, counted from the database.

These are the rows of the pilot table in the thesis (Chapter 8) and of the founder's own review:
conversations, how many customer messages came outside working hours, what the AI completed on its own
(bookings, booking requests, orders, qualified leads), what it handed to people, how often it failed to
answer and how many of those it answered later, how fast the first answer came, what the model cost per reply and per
conversation, and whether the business pays. Demo businesses of the public site
and the owners' own test chats (joop/stats.py) are left out.
"""

from __future__ import annotations

import csv
import io
import statistics
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import func
from sqlmodel import Session, select

from . import billing
from .agent.engine import ERROR_REPLY, TEXT_ONLY_REPLY
from .models import Booking, Business, Lead, Message, Order, Subscription
from .niches import get_pack
from .stats import TEST_CHANNEL, real_messages

DEMO_PREFIX = "site-demo-"
LATE = "ИИ после сбоя"  # Lead.closed_by of a failure the AI answered later (set by joop/recovery.py)


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
    handoff_conversations: int = 0
    failures: int = 0  # the model could not answer; the customer got the fallback
    answered_later: int = 0  # of those, answered by the AI once it worked again (joop/recovery.py)
    cost_usd: float = 0.0
    status: str = ""
    paying: bool = False
    _days: set = field(default_factory=set, repr=False)
    _convs: set = field(default_factory=set, repr=False)
    _first_reply: list = field(default_factory=list, repr=False)  # seconds from a conversation's first customer message to the first answer

    @property
    def median_first_reply_s(self) -> int | None:
        """Median time to the first answer (AI or staff) of a conversation in the period, in seconds."""
        return round(statistics.median(self._first_reply)) if self._first_reply else None

    @property
    def handoff_pct(self) -> int | None:
        """Conversations handed to people, as a share of all conversations (one chat counts once however often)."""
        return round(100 * self.handoff_conversations / self.conversations) if self.conversations else None

    @property
    def cost_per_conversation(self) -> float | None:
        return self.cost_usd / self.conversations if self.conversations else None

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
    in_period = (Message.created_at >= since_utc, Message.created_at < until_utc, real_messages())  # not the test chat
    rows: dict[int, PilotRow] = {}

    def row(bid: int) -> PilotRow | None:
        if bid not in businesses:
            return None
        if bid not in rows:
            b = businesses[bid]
            rows[bid] = PilotRow(business=b.name, niche=get_pack(b.niche).label)
        return rows[bid]

    asked: dict[int, datetime] = {}  # conversation -> its first customer message in the period
    answered: set[int] = set()
    not_an_answer = {ERROR_REPLY, TEXT_ONLY_REPLY}  # fallbacks the customer gets when the AI could not answer
    for bid, conv_id, at, off, role, cost, text in session.exec(select(
            Message.business_id, Message.conversation_id, Message.created_at, Message.off_hours, Message.role, Message.cost_usd,
            Message.text,
    ).where(*in_period).order_by(Message.created_at, Message.id)).all():
        r = row(bid)
        if r is None:
            continue
        if role == "customer":
            asked.setdefault(conv_id, at)
        elif role in ("ai", "staff") and conv_id in asked and conv_id not in answered and text not in not_an_answer:
            answered.add(conv_id)
            r._first_reply.append(max(0.0, (at - asked[conv_id]).total_seconds()))
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
            model.created_at >= since_utc, model.created_at < until_utc, model.channel != TEST_CHANNEL, *where,
        ).group_by(model.business_id)).all())

    for attr, counts in (
        ("bookings", count(Booking, Booking.source == "ai")),
        ("requests", count(Lead, Lead.kind == "request")),
        ("orders", count(Order)),
        ("leads", count(Lead, Lead.kind == "lead")),
        ("handoffs", count(Lead, Lead.kind == "handoff")),
        ("handoff_conversations", dict(session.exec(select(Lead.business_id, func.count(func.distinct(Lead.conversation_id))).where(
            Lead.created_at >= since_utc, Lead.created_at < until_utc, Lead.channel != TEST_CHANNEL, Lead.kind == "handoff",
            Lead.conversation_id != None).group_by(Lead.business_id)).all())),  # noqa: E711
        ("failures", count(Lead, Lead.kind == "error")),
        ("answered_later", count(Lead, Lead.kind == "error", Lead.closed_by == LATE)),
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
    total._first_reply = [x for r in ordered for x in r._first_reply]
    for f in ("conversations", "customer_messages", "off_hours_messages", "ai_replies", "bookings", "requests",
              "orders", "leads", "handoffs", "handoff_conversations", "failures", "answered_later", "cost_usd"):
        setattr(total, f, sum(getattr(r, f) for r in ordered))
    total.status = f"платят: {sum(r.paying for r in ordered)}"
    total.paying = any(r.paying for r in ordered)
    return ordered, total


CSV_COLUMNS = [
    ("business", "business"), ("niche", "niche"), ("active_days", "active_days"), ("conversations", "conversations"),
    ("customer_messages", "customer_messages"), ("off_hours_messages", "off_hours_messages"), ("off_hours_pct", "off_hours_pct"),
    ("ai_replies", "ai_replies"), ("bookings", "bookings"), ("requests", "requests"), ("orders", "orders"), ("leads", "leads"),
    ("completed", "completed_by_ai"), ("handoffs", "handoffs"), ("failures", "failures"), ("answered_later", "failures_answered_later"), ("cost_usd", "cost_usd"),
    ("cost_per_reply", "cost_per_reply_usd"), ("cost_per_conversation", "cost_per_conversation_usd"),
    ("handoff_pct", "handoff_pct"), ("median_first_reply_s", "median_first_reply_s"), ("status", "status"), ("paying", "paying"),
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
                v = f"{v:.6f}" if attr in ("cost_per_reply", "cost_per_conversation") else f"{v:.4f}"
            values.append("" if v is None else v)
        w.writerow(values)
    return out.getvalue()

