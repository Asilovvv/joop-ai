"""Confirming a visit from the reminder, and what happens when nobody confirms.

The reminder the day before ends with "Ответьте «да», если придёте". A short "да" / "приду" / "ооба" / "келем"
while a reminded booking of this chat waits is taken by code (no model call): `Booking.confirmed_at` is set and
the customer gets one line. The morning summary lists today's bookings nobody confirmed, so the administrator
calls them first. When the business chose so (`Business.release_unconfirmed_hours`, off by default), a booking
still unconfirmed that many hours before the visit is released: the customer is told, the time goes to the
waiting list, staff get a note. Only bookings whose reminder was actually delivered are released: a customer
who never got the question is not blamed for not answering it.

A salon-chain case with the same mechanic (reminders with Приду/Перенести buttons, release of silent bookings)
reported no-shows 14% → 6%; the number is the vendor's own (docs: «Joop AI — стратегия с нуля»).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from sqlmodel import Session, select

from .followups import _kyrgyz, deliver_to_chat
from .lang import is_kyrgyz_message
from .models import Booking, Business, Conversation
from .stats import TEST_CHANNEL
from .timeutil import fmt_slot, utc_to_local

if TYPE_CHECKING:
    from .runtime import Runtime

ASK_RU = "Ответьте «да», если придёте, или напишите, если планы изменились."
ASK_KY = "Келсеңиз «ооба» деп жооп бериңиз, пландар өзгөрсө — жазыңыз."
HORIZON = timedelta(hours=48)  # a "да" confirms a reminded visit within two days, not a booking next month
WEEKDAYS_KY = ("Дш", "Шш", "Шр", "Бш", "Жм", "Иш", "Жк")  # проверить носителем
_YES = re.compile(r"^\W*(да|ага|приду|буду|будем|придём|придем|ок|окей|хорошо|конечно|подтверждаю|обязательно|"
                  r"ооба|келем|келебиз|макул|барам|барабыз|\+|👍)\b", re.I)
_NO = re.compile(r"\b(не|нет|жок|отмен|перенес|перенос|позже|другой|другое|башка)\w*", re.I)


def says_yes(text: str) -> bool:
    """A short plain yes: "да", "Да, приду", "ооба келем" — not "да, а можно перенести?"."""
    t = (text or "").strip()
    return 0 < len(t) <= 40 and "?" not in t and bool(_YES.match(t)) and not _NO.search(t)


def fmt_slot_ky(dt: datetime) -> str:
    return f"{WEEKDAYS_KY[dt.weekday()]} {dt:%d.%m %H:%M}"


def _pending(session: Session, conv: Conversation, now_local: datetime) -> Booking | None:
    """The reminded, unconfirmed booking of this chat that is coming up."""
    return session.exec(select(Booking).where(
        Booking.conversation_id == conv.id, Booking.status == "booked", Booking.reminder_status == "sent",
        Booking.confirmed_at == None, Booking.start > now_local, Booking.start <= now_local + HORIZON,  # noqa: E711
    ).order_by(Booking.start)).first()


@dataclass
class Confirmed:
    reply: str
    booking_id: int


def capture(session: Session, business: Business, conv: Conversation, text: str, now_utc: datetime) -> Confirmed | None:
    if not says_yes(text):
        return None
    booking = _pending(session, conv, utc_to_local(now_utc, business.timezone))
    if booking is None:
        return None
    booking.confirmed_at = now_utc
    session.add(booking)
    kyrgyz = is_kyrgyz_message(text) or _kyrgyz(session, conv.id)
    reply = f"Рахмат, {fmt_slot_ky(booking.start)} күтөбүз!" if kyrgyz else f"Спасибо, ждём вас {fmt_slot(booking.start)}!"
    return Confirmed(reply=reply, booking_id=booking.id)


def unconfirmed(session: Session, business: Business, bookings: list[Booking]) -> list[Booking]:
    """Of today's bookings, those whose reminder went out and nobody answered "да"."""
    return [b for b in bookings if b.reminder_status == "sent" and b.confirmed_at is None]


def digest_line(bookings: list[Booking]) -> str:
    rows = ", ".join(f"{b.start:%H:%M} {b.customer_name}, {b.customer_phone}" for b in bookings)
    return f"Не подтвердили запись: {len(bookings)} — {rows}. Позвоните или освободите время."


def release_unconfirmed(session: Session, rt: "Runtime", business: Business, now_utc: datetime) -> dict[str, int]:
    """The business chose to free times nobody confirmed: N hours before the visit the booking is released."""
    hours = business.release_unconfirmed_hours
    if hours <= 0:
        return {}
    now_local = utc_to_local(now_utc, business.timezone)
    due = session.exec(select(Booking).where(
        Booking.business_id == business.id, Booking.status == "booked", Booking.reminder_status == "sent",
        Booking.confirmed_at == None, Booking.channel != TEST_CHANNEL,  # noqa: E711
        Booking.start > now_local, Booking.start <= now_local + timedelta(hours=hours),
    ).order_by(Booking.start)).all()
    if not due:
        return {}
    from . import waitlist
    from .deposits import _release
    from .dispatch import notify_admins

    notes = []
    for booking in due:
        slot = _release(session, booking)
        conv = session.get(Conversation, booking.conversation_id) if booking.conversation_id else None
        kyrgyz = bool(conv) and _kyrgyz(session, conv.id)
        text = (f"Сиз {fmt_slot_ky(booking.start)} жазылууну ырастаган жоксуз, ошондуктан убакыт бошотулду. "
                "Кааласаңыз, кайра жазам — ыңгайлуу убакытты жазыңыз." if kyrgyz else
                f"Вы не подтвердили запись на {fmt_slot(booking.start)}, поэтому время освобождено. "
                "Если хотите, запишу снова — напишите удобное время.")
        told = deliver_to_chat(session, rt, business, conv, text, now_utc) if conv else False
        offered = waitlist.offer_freed_slot(session, rt, business, slot, now_utc) if slot is not None else 0
        notes.append(f"Запись снята: {booking.customer_name}, {booking.customer_phone}, {fmt_slot(booking.start)} — "
                     "не подтвердил(а) после напоминания." + ("" if told else " Клиенту сообщите сами.")
                     + (f" Время предложено из листа ожидания: {offered}." if offered else ""))
    notify_admins(rt, business, notes)
    return {"released": len(due)}
