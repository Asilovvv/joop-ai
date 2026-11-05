"""A returning customer: the AI knows the last visits and the upcoming one.

When the chat's phone is known, code finds this customer's earlier bookings at the business (by the last nine
digits of the phone, as loyalty does) and tells the model in one line: how many visits, the last service and
specialist, what they usually take. The model may then offer "как в прошлый раз" instead of asking everything
again. An upcoming booking is named too, so the AI does not book the same person twice. Facts only, from the
database; the prompt's rules are unchanged. Booking platforms sell this as "recognises the returning client"
(docs: «Joop AI — стратегия с нуля», "память о постоянном клиенте").
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timedelta

import sqlalchemy as sa
from sqlmodel import Session, select

from .models import Booking, Business, Conversation
from .stats import TEST_CHANNEL
from .timeutil import fmt_slot

_DIGITS = re.compile(r"\D")
LAST = 10  # bookings looked at
KEEP_UPCOMING = timedelta(days=60)


def _key(phone: str) -> str:
    digits = _DIGITS.sub("", phone or "")[-9:]
    return digits if len(digits) == 9 else ""


def _bookings(session: Session, business: Business, conv: Conversation) -> list[Booking]:
    """This chat's own bookings, plus bookings from other chats with the same phone AND the same name: a friend's
    number typed into a chat must not open the friend's history to the model."""
    key = _key(conv.customer_phone)
    own = Booking.conversation_id == conv.id if conv.id else sa.false()
    match = sa.or_(own, Booking.customer_phone.like(f"%{key}")) if key else own  # phones are stored normalised, +E.164
    rows = session.exec(select(Booking).where(
        Booking.business_id == business.id, Booking.status == "booked", Booking.channel != TEST_CHANNEL, match,
    ).order_by(Booking.start.desc()).limit(LAST * 3)).all()
    me = (conv.customer_name or conv.display_name or "").strip().casefold()
    return [b for b in rows if b.conversation_id == conv.id or (me and (b.customer_name or "").strip().casefold() == me)]


def _what(b: Booking) -> str:
    return (b.service or "визит") + (f" у {b.staff_name}" if b.staff_name else "")


def prompt_hint(session: Session, business: Business, conv: Conversation, now_local: datetime) -> str:
    rows = _bookings(session, business, conv)
    if not rows:
        return ""
    lines = []
    upcoming = [b for b in rows if now_local <= b.start <= now_local + KEEP_UPCOMING]
    if upcoming:
        b = min(upcoming, key=lambda x: x.start)
        lines.append(f"Уже записан(а): {fmt_slot(b.start)} — {_what(b)}. Второй раз не записывай, если не просит ещё одну запись.")
    past = [b for b in rows if b.start < now_local][:LAST]
    if past:
        last = past[0]
        usual = Counter(_what(b) for b in past[1:]).most_common(1)
        before = f", до этого {usual[0][0]} ({usual[0][1]} раза)" if usual and usual[0][1] >= 2 else (f", до этого {usual[0][0]}" if usual else "")
        lines.append(f"Постоянный клиент: {_ru(len(past))}, последний — {_what(last)} {last.start:%d.%m}{before}. "
                     "Если не называет услугу или мастера, можно предложить как в прошлый раз, не настаивая.")
    return "\n" + "\n".join(lines) if lines else ""


def _ru(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} визит"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return f"{n} визита"
    return f"{n} визитов"
