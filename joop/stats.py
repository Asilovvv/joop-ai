"""Activity numbers for the dashboard, the morning summary and the pilot report."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func
from sqlmodel import Session, select

from .models import Booking, Lead, Message


def activity(session: Session, business_id: int, since_utc: datetime) -> dict[str, int]:
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
        "leads": scalar(
            select(func.count()).select_from(Lead).where(Lead.business_id == business_id, Lead.created_at >= since_utc)
        ),
    }
