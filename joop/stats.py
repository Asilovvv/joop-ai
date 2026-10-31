"""Activity numbers for the dashboard, the morning summary and the pilot report."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func
from sqlmodel import Session, select

from .models import Booking, Lead, Message, Order


def activity(session: Session, business_id: int, since_utc: datetime) -> dict:
    def scalar(query) -> int:
        return int(session.exec(query).one() or 0)

    customer = (Message.business_id == business_id, Message.role == "customer", Message.created_at >= since_utc)
    return {
        "customer_messages": scalar(select(func.count()).select_from(Message).where(*customer)),
        "conversations": scalar(select(func.count(func.distinct(Message.conversation_id))).where(*customer)),
        "off_hours_conversations": scalar(
            select(func.count(func.distinct(Message.conversation_id))).where(*customer, Message.off_hours == True)  # noqa: E712
        ),
        "bookings": scalar(
            select(func.count()).select_from(Booking).where(
                Booking.business_id == business_id, Booking.source == "ai", Booking.created_at >= since_utc
            )
        ),
        "off_hours_bookings": scalar(
            select(func.count()).select_from(Booking).where(
                Booking.business_id == business_id,
                Booking.source == "ai",
                Booking.created_at >= since_utc,
                Booking.created_off_hours == True,  # noqa: E712
            )
        ),
        "requests": scalar(
            select(func.count()).select_from(Lead).where(
                Lead.business_id == business_id, Lead.kind == "request", Lead.created_at >= since_utc
            )
        ),
        "leads": scalar(
            select(func.count()).select_from(Lead).where(
                Lead.business_id == business_id, Lead.kind != "request", Lead.created_at >= since_utc
            )
        ),
        "orders": scalar(
            select(func.count()).select_from(Order).where(Order.business_id == business_id, Order.created_at >= since_utc)
        ),
        "ai_replies": scalar(
            select(func.count()).select_from(Message).where(
                Message.business_id == business_id, Message.role == "ai", Message.created_at >= since_utc
            )
        ),
        "ai_cost_usd": float(
            session.exec(
                select(func.coalesce(func.sum(Message.cost_usd), 0.0)).where(
                    Message.business_id == business_id, Message.created_at >= since_utc
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
            Message.business_id == business_id, Message.role == "customer", Message.created_at >= since_utc
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
