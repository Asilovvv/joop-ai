"""Activity numbers for the dashboard, the morning summary and the pilot report.

Only real customers count. The panel's test chat (/panel/try, channel "console") is the owner writing as a
customer: its messages, bookings and requests stay visible in the panel lists, but they are left out of every
number shown to the owner, of the reports and of the pilot table, and they are not sent to the business's CRM.
The same holds for a Telegram chat where the owner or staff test their own bot (Conversation.staff_test): the
alerts chat linked with /admin, a chat opened from the panel's «Написать боту» link (/start test_<secret code>), or the web chat
written from a browser logged in to the business's panel.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import and_, false, func, or_
from sqlmodel import Session, select

from .models import Booking, Conversation, Lead, Message, Order, Stay

TEST_CHANNEL = "console"  # the panel's test chat


def test_conversations(business_id: int | None = None):
    """Ids of test conversations (of one business, or of all): the panel's test chat and staff testing their bot."""
    q = select(Conversation.id).where(or_(Conversation.channel == TEST_CHANNEL, Conversation.staff_test == True))  # noqa: E712
    return q.where(Conversation.business_id == business_id) if business_id is not None else q


def real_conversation():
    """Condition on Conversation: a real customer's chat."""
    return and_(Conversation.channel != TEST_CHANNEL, Conversation.staff_test == false())


def is_test(conv: Conversation | None) -> bool:
    return conv is not None and (conv.channel == TEST_CHANNEL or conv.staff_test)


def not_test(model, business_id: int | None = None):
    """Condition on Booking, Lead, Order, Stay or WaitlistEntry: made for a real customer, not in a test chat."""
    return and_(model.channel != TEST_CHANNEL, or_(
        model.conversation_id.is_(None), model.conversation_id.not_in(test_conversations(business_id))))


def real_messages(business_id: int | None = None):
    """Condition on Message: not in the test chat."""
    return Message.conversation_id.not_in(test_conversations(business_id))


def activity(session: Session, business_id: int, since_utc: datetime) -> dict:
    def scalar(query) -> int:
        return int(session.exec(query).one() or 0)

    customer = (Message.business_id == business_id, Message.role == "customer", Message.created_at >= since_utc,
                real_messages(business_id))
    return {
        "customer_messages": scalar(select(func.count()).select_from(Message).where(*customer)),
        "conversations": scalar(select(func.count(func.distinct(Message.conversation_id))).where(*customer)),
        "off_hours_conversations": scalar(
            select(func.count(func.distinct(Message.conversation_id))).where(*customer, Message.off_hours == True)  # noqa: E712
        ),
        "bookings": scalar(
            select(func.count()).select_from(Booking).where(
                Booking.business_id == business_id, Booking.source == "ai", Booking.created_at >= since_utc,
                not_test(Booking, business_id),
            )
        ),
        "off_hours_bookings": scalar(
            select(func.count()).select_from(Booking).where(
                Booking.business_id == business_id,
                Booking.source == "ai",
                Booking.created_at >= since_utc,
                Booking.created_off_hours == True,  # noqa: E712
                not_test(Booking, business_id),
            )
        ),
        "stays": scalar(  # hotel room bookings the AI made (joop/stays.py)
            select(func.count()).select_from(Stay).where(
                Stay.business_id == business_id, Stay.source == "ai", Stay.created_at >= since_utc, not_test(Stay, business_id),
            )
        ),
        "off_hours_stays": scalar(
            select(func.count()).select_from(Stay).where(
                Stay.business_id == business_id, Stay.source == "ai", Stay.created_at >= since_utc,
                Stay.created_off_hours == True, not_test(Stay, business_id),  # noqa: E712
            )
        ),
        "requests": scalar(
            select(func.count()).select_from(Lead).where(
                Lead.business_id == business_id, Lead.kind == "request", Lead.created_at >= since_utc, not_test(Lead, business_id)
            )
        ),
        "qualified": scalar(  # leads the AI qualified (budget, district, volume…): a result, not a question for staff
            select(func.count()).select_from(Lead).where(
                Lead.business_id == business_id, Lead.kind == "lead", Lead.created_at >= since_utc, not_test(Lead, business_id)
            )
        ),
        "leads": scalar(
            select(func.count()).select_from(Lead).where(
                Lead.business_id == business_id, Lead.kind != "request", Lead.created_at >= since_utc, not_test(Lead, business_id)
            )
        ),
        "orders": scalar(
            select(func.count()).select_from(Order).where(Order.business_id == business_id, Order.created_at >= since_utc,
                                                          not_test(Order, business_id))
        ),
        "ai_replies": scalar(
            select(func.count()).select_from(Message).where(
                Message.business_id == business_id, Message.role == "ai", Message.created_at >= since_utc, real_messages(business_id)
            )
        ),
        "ai_cost_usd": float(
            session.exec(
                select(func.coalesce(func.sum(Message.cost_usd), 0.0)).where(
                    Message.business_id == business_id, Message.created_at >= since_utc, real_messages(business_id)
                )
            ).one()
            or 0.0
        ),
    }


def by_hour(session: Session, business_id: int, since_utc: datetime, tz: str) -> dict:
    """Customer messages by local hour of day, split into working and off hours (Message.off_hours).

    The owner sees when customers write and how many messages came while nobody was at the desk:
    the main thing the AI is paid for.
    """
    from .timeutil import utc_to_local

    rows = session.exec(
        select(Message.created_at, Message.off_hours).where(
            Message.business_id == business_id, Message.role == "customer", Message.created_at >= since_utc,
            real_messages(business_id),
        ).limit(50_000)
    ).all()
    on = [0] * 24
    off = [0] * 24
    for created, is_off in rows:
        hour = utc_to_local(created, tz).hour
        (off if is_off else on)[hour] += 1
    total, off_total = sum(on) + sum(off), sum(off)
    return {"on": on, "off": off, "total": total, "off_total": off_total,
            "off_pct": round(100 * off_total / total) if total else 0}


def hour_bars(data: dict, width: int = 720, height: int = 150, top: int = 18, gap: int = 2) -> list[dict]:
    """Bar geometry for the 24-hour chart: one column per hour, the off-hours part stacked on top."""
    peak = max((a + b for a, b in zip(data["on"], data["off"])), default=0) or 1
    step = width / 24
    bar_w = step - 4
    bars = []
    for h in range(24):
        on, off = data["on"][h], data["off"][h]
        on_h = (height - top) * on / peak
        off_h = (height - top) * off / peak
        if on and off:
            off_h = max(off_h - gap, 1)  # a 2px surface gap between the stacked parts
        x = h * step + 2
        on_y = height - on_h
        off_y = on_y - (gap if on and off else 0) - off_h
        bars.append({"h": h, "x": round(x, 1), "w": round(bar_w, 1), "on": on, "off": off, "top": off_y if off else on_y,
                     # the upper segment gets the rounded data-end, the lower one stays square
                     "on_d": _bar(x, on_y, bar_w, on_h, rounded=not off) if on else "",
                     "off_d": _bar(x, off_y, bar_w, off_h, rounded=True) if off else ""})
    return bars


def _bar(x: float, y: float, w: float, h: float, rounded: bool, r: float = 4) -> str:
    """SVG path of a bar standing on the baseline; `rounded` rounds the two top corners."""
    r = min(r, w / 2, h) if rounded else 0
    x, y, w, h = (round(v, 1) for v in (x, y, w, h))
    if not r:
        return f"M{x},{y + h}V{y}H{x + w}V{y + h}Z"
    return (f"M{x},{y + h}V{y + r}Q{x},{y} {x + r},{y}H{x + w - r}Q{x + w},{y} {x + w},{y + r}V{y + h}Z")
