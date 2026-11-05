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
from .models import Booking, Business, Conversation, Message
from .stats import TEST_CHANNEL
from .timeutil import fmt_slot, utc_to_local

if TYPE_CHECKING:
    from .runtime import Runtime

ASK_RU = "Ответьте «да», если придёте, или напишите, если планы изменились."
ASK_KY = "Келсеңиз «ооба» деп жооп бериңиз, пландар өзгөрсө — жазыңыз."
HORIZON = timedelta(hours=48)  # a "да" confirms a reminded visit within two days, not a booking next month
GRACE = timedelta(hours=3)  # the customer gets at least this long after the question before a release
WEEKDAYS_KY = ("дүй", "шейш", "шарш", "бейш", "жума", "ишм", "жек")  # CLDR ky abbreviations; проверить носителем
_YES = re.compile(r"^\W*(да|ага|приду|буду|будем|придём|придем|ок|окей|хорошо|конечно|подтверждаю|обязательно|"
                  r"ооба|келем|келебиз|макул|барам|барабыз|\+|👍)(?!\w)", re.I)
_NO = re.compile(r"\b(не|нет|жок|отмен|перенес|перенос|позже|другой|другое|башка)\w*", re.I)
ASKS = (ASK_RU, ASK_KY)


def says_yes(text: str) -> bool:
    """A short plain yes: "да", "Да, приду", "ооба келем", "👍" — not "да, а можно перенести?", not "да, запишите на 10:00"."""
    t = (text or "").strip()
    return (0 < len(t) <= 40 and "?" not in t and len(t.split()) <= 3 and not re.search(r"\d", t)
            and bool(_YES.match(t)) and not _NO.search(t))


def asked_at(session: Session, conv: Conversation) -> datetime | None:
    """When the reminder's question was the AI's last word in this chat; None if the AI asked something else since."""
    last = session.exec(select(Message).where(Message.conversation_id == conv.id, Message.role == "ai")
                        .order_by(Message.id.desc())).first()
    if last is None or not any(ask in (last.text or "") for ask in ASKS):
        return None
    return last.created_at


def fmt_slot_ky(dt: datetime) -> str:
    return f"{WEEKDAYS_KY[dt.weekday()]} {dt:%d.%m %H:%M}"


def _pending(session: Session, conv: Conversation, now_local: datetime) -> list[Booking]:
    """The reminded, unconfirmed bookings of this chat that are coming up (two visits in one chat: both)."""
    return list(session.exec(select(Booking).where(
        Booking.conversation_id == conv.id, Booking.status == "booked", Booking.reminder_status == "sent",
        Booking.confirmed_at == None, Booking.start > now_local, Booking.start <= now_local + HORIZON,  # noqa: E711
    ).order_by(Booking.start)).all())


@dataclass
class Confirmed:
    reply: str
    booking_id: int


def capture(session: Session, business: Business, conv: Conversation, text: str, now_utc: datetime) -> Confirmed | None:
    """A yes while the reminder's question is the AI's last word: the AI asked nothing else since, so this "да" is for it."""
    if not says_yes(text) or asked_at(session, conv) is None:
        return None
    bookings = _pending(session, conv, utc_to_local(now_utc, business.timezone))
    if not bookings:
        return None
    for booking in bookings:
        booking.confirmed_at = now_utc
        session.add(booking)
    kyrgyz = is_kyrgyz_message(text) or _kyrgyz(session, conv.id)
    times = " и ".join((fmt_slot_ky if kyrgyz else fmt_slot)(b.start) for b in bookings)
    reply = f"Рахмат, {times} күтөбүз!" if kyrgyz else f"Спасибо, ждём вас {times}!"
    return Confirmed(reply=reply, booking_id=bookings[0].id)


def unconfirmed(bookings: list[Booking]) -> list[Booking]:
    """Of today's bookings, those that got the question (the text reminder, not a WhatsApp template) and no "да"."""
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
        Booking.deposit_status.not_in(["paid", "check"]),  # money on the table is a confirmation
        Booking.start > now_local, Booking.start <= now_local + timedelta(hours=hours),
    ).order_by(Booking.start)).all()
    if not due:
        return {}
    from . import waitlist
    from .deposits import _release
    from .dispatch import notify_admins

    notes = []
    released = 0
    for booking in due:
        conv = session.get(Conversation, booking.conversation_id) if booking.conversation_id else None
        asked = asked_at(session, conv) if conv else None
        if asked is None or now_utc - asked < GRACE:
            continue  # the question is not the last word, or it was asked too recently to blame the silence
        released += 1
        slot = _release(session, booking)
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
    if not released:
        return {}
    notify_admins(rt, business, notes)
    return {"released": released}
