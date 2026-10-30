"""Questions before a visit and a reward for every N-th visit.

Questions: right after the AI books a slot it asks the company's questions ("что беспокоит?", "порода и
вес питомца?"); the customer's next message is saved with the booking for the specialist and still goes
to the AI as usual, so nothing the customer writes is swallowed.
Loyalty: code counts the customer's earlier visits by phone; every N-th visit gets the company's reward.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from sqlmodel import Session, select

from .models import Booking, Business, Conversation, Message
from .timeutil import fmt_slot

MAX_QUESTIONS = 5
ANSWER_WINDOW = timedelta(hours=48)
_DIGITS = re.compile(r"\D")


def questions(business: Business) -> list[str]:
    return [q.strip()[:200] for q in (business.intake_questions or "").splitlines() if q.strip()][:MAX_QUESTIONS]


def ask_text(business: Business, kyrgyz: bool) -> str:
    items = questions(business)
    head = ("Келишиңизге даярдануу үчүн, сураныч, бир билдирүү менен жооп бериңиз:" if kyrgyz
            else "Чтобы подготовиться к визиту, ответьте, пожалуйста, одним сообщением:")
    return "\n".join([head] + [f"{i}. {q}" for i, q in enumerate(items, start=1)])


def after_booking(business: Business, booking: Booking, kyrgyz: bool) -> str:
    """Text to add to the booking confirmation; marks the booking as waiting for answers."""
    if not questions(business):
        return ""
    booking.intake_status = "asked"
    return "\n\n" + ask_text(business, kyrgyz)


def capture(session: Session, conv: Conversation, text: str, now_utc: datetime) -> Booking | None:
    """Save the customer's reply as answers when the AI's last message was the questions."""
    if len((text or "").strip()) < 2:
        return None
    booking = session.exec(select(Booking).where(Booking.conversation_id == conv.id, Booking.intake_status == "asked",
                                                 Booking.created_at >= now_utc - ANSWER_WINDOW)
                           .order_by(Booking.created_at.desc())).first()
    if booking is None:
        return None
    last_ai = session.exec(select(Message.text).where(Message.conversation_id == conv.id, Message.role == "ai")
                           .order_by(Message.id.desc())).first()
    if not last_ai or "1. " not in last_ai:
        return None
    booking.intake_answers, booking.intake_status = text.strip()[:2000], "answered"
    session.add(booking)
    return booking


def answers_note(booking: Booking) -> str:
    return (f"Ответы перед визитом: {booking.customer_name}, {fmt_slot(booking.start)}"
            + (f", {booking.staff_name}" if booking.staff_name else "") + f"\n{booking.intake_answers}")


ANSWERED_HINT = ("\nКлиент только что ответил на вопросы перед визитом, ответы уже переданы специалисту: коротко "
                 "поблагодари. Если в сообщении есть вопрос, ответь на него.")


# --- loyalty -----------------------------------------------------------------------------------


def visit_number(session: Session, business: Business, booking: Booking) -> int:
    key = _DIGITS.sub("", booking.customer_phone)[-9:]
    if len(key) < 9:
        return 1
    earlier = session.exec(select(Booking.customer_phone).where(
        Booking.business_id == business.id, Booking.status == "booked", Booking.start < booking.start,
        Booking.id != booking.id)).all()
    return 1 + sum(1 for p in earlier if _DIGITS.sub("", p)[-9:] == key)


def loyalty_line(session: Session, business: Business, booking: Booking, kyrgyz: bool) -> str:
    if business.loyalty_every < 2 or not business.loyalty_reward.strip():
        return ""
    n = visit_number(session, business, booking)
    if n % business.loyalty_every:
        return ""
    booking.loyalty_visit = n
    reward = business.loyalty_reward.strip()
    return f" Бул сиздин {n}-келишиңиз болот — {reward}." if kyrgyz else f" Это будет ваш {n}-й визит — {reward}."
