"""One follow-up to a customer who asked and went quiet without booking.

A customer asks the price or whether there is a time, the AI answers, and nothing more comes. Two hours later,
in working hours, the AI sends one message with the two nearest free times and asks for a "да" or another time.
It is the customer's own open question, not a broadcast: nothing goes to people who booked, were handed to a
person, placed an order, opted out, or already got this follow-up. Off by default (`Business.nudge_unfinished`).
Messenger rules hold: WhatsApp and Instagram only within 24 hours of the customer's last message, which two
hours later they still are. The Monday report counts the follow-ups and the bookings that came after them.

The same move in CIS practice (docs: «Joop AI — стратегия с нуля», "дожим незавершённого диалога"): a sales
assistant's booking conversion is reported at 55–65% against 15–20% for a form — the vendor's own numbers.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import func
from sqlmodel import Session, select

from .followups import _kyrgyz, deliver_to_chat
from .models import Booking, Business, Conversation, Lead, Message, Order
from .slots import free_slots
from .stats import TEST_CHANNEL
from .timeutil import fmt_slot, is_off_hours, utc_to_local

if TYPE_CHECKING:
    from .runtime import Runtime

WAIT = timedelta(hours=2)  # after the customer's last message
LOOK_BACK = timedelta(hours=20)  # older silence is left alone: the messenger window closes at 24 h anyway
CHANNELS = ("telegram", "whatsapp", "instagram")
PER_TICK = 20


def _text(session: Session, business: Business, conv: Conversation, now_local: datetime) -> str | None:
    pair = free_slots(session, business.id, now_local, days=7, limit=2)
    if not pair:
        return None
    times = " или ".join(fmt_slot(slot.start) for slot, _ in pair)
    if _kyrgyz(session, conv.id):
        return f"Ыңгайлуу болсо, жазып коёюн: {times}. «Ооба» деп же башка ыңгайлуу убакытты жазыңыз."
    return f"Если удобно, могу записать вас: {times}. Напишите «да» или другое удобное время."


def _open(session: Session, conv: Conversation) -> bool:
    """The customer asked, the AI answered last, and nothing came of it yet."""
    last = session.exec(select(Message.role).where(Message.conversation_id == conv.id).order_by(Message.id.desc())).first()
    if last != "ai":
        return False
    if session.exec(select(Booking.id).where(Booking.conversation_id == conv.id)).first() is not None:
        return False
    if session.exec(select(Order.id).where(Order.conversation_id == conv.id)).first() is not None:
        return False
    return session.exec(select(Lead.id).where(Lead.conversation_id == conv.id)).first() is None


def due(session: Session, business: Business, now_utc: datetime) -> list[Conversation]:
    if not business.nudge_unfinished:
        return []
    now_local = utc_to_local(now_utc, business.timezone)
    if is_off_hours(now_local, business.work_start, business.work_end, business.days_off):
        return []
    rows = session.exec(select(Conversation).where(
        Conversation.business_id == business.id, Conversation.channel.in_(CHANNELS), Conversation.followup_at == None,  # noqa: E711
        Conversation.broadcast_opt_out == False, Conversation.last_customer_at <= now_utc - WAIT,  # noqa: E712
        Conversation.last_customer_at >= now_utc - LOOK_BACK, Conversation.ai_paused_until == None,  # noqa: E711
    ).order_by(Conversation.last_customer_at)).all()
    return [c for c in rows if _open(session, c)][:PER_TICK]


def send_due(session: Session, rt: "Runtime", business: Business, now_utc: datetime) -> dict[str, int]:
    convs = due(session, business, now_utc)
    if not convs:
        return {}
    now_local = utc_to_local(now_utc, business.timezone)
    sent = 0
    for conv in convs:
        text = _text(session, business, conv, now_local)
        conv.followup_at = now_utc  # tried once, whatever happened: never a second time
        session.add(conv)
        if text and deliver_to_chat(session, rt, business, conv, text, now_utc):
            sent += 1
    return {"sent": sent} if sent else {}


def week_numbers(session: Session, business: Business, since_utc: datetime) -> tuple[int, int]:
    """Follow-ups sent in the period, and bookings made in those conversations after the follow-up."""
    convs = session.exec(select(Conversation).where(
        Conversation.business_id == business.id, Conversation.followup_at >= since_utc, Conversation.channel != TEST_CHANNEL,
    )).all()
    booked = 0
    for conv in convs:
        booked += session.exec(select(func.count()).select_from(Booking).where(
            Booking.conversation_id == conv.id, Booking.created_at >= conv.followup_at)).one() > 0
    return len(convs), booked
