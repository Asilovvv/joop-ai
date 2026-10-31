"""A customer cancels or moves their own booking in the chat.

The model may only point at a booking from the list of this customer's upcoming bookings. The code checks
that it belongs to this conversation and is still ahead, frees the slot, and the dispatcher then offers the
time to the waiting list. A booking that lives in the salon's Altegio is not cancelled here: Joop cannot
cancel it there, so staff get the request and the next Altegio sync closes it in Joop (joop/altegio.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlmodel import Session, select

from .models import Booking, Conversation, Slot
from .slots import release_slot, seats_needed
from .timeutil import fmt_slot

SHOWN = 5
CANCEL_FORMAT = ('"cancel": null или номер записи из списка «Предстоящие записи клиента», '
                 'если клиент ясно просит отменить или перенести её')
CANCEL_RULE = (
    "Если клиент просит отменить запись, заполни cancel номером записи из этого списка и в reply подтверди отмену; "
    "если записей несколько и неясно какую, уточни. Если клиент хочет перенести запись, предложи новое время из "
    "свободных окон, а когда он выберет, заполни booking новым окном и cancel — старой записью. "
    "Без ясной просьбы клиента cancel не заполняй."
)
NOT_FOUND_REPLY = "Не нашла такой записи. Я передала ваш вопрос администратору — он поможет."
EXTERNAL_REPLY = "Передала администратору: он отменит запись в системе салона и подтвердит вам."


def upcoming(session: Session, conv: Conversation, now_local: datetime) -> list[Booking]:
    return list(session.exec(select(Booking).where(
        Booking.conversation_id == conv.id, Booking.status == "booked", Booking.start > now_local,
    ).order_by(Booking.start).limit(SHOWN)).all())


def prompt_hint(session: Session, conv: Conversation, now_local: datetime) -> str:
    rows = upcoming(session, conv, now_local)
    if not rows:
        return ""
    lines = ["", "Предстоящие записи клиента (номер записи: день и время):"]
    for b in rows:
        extra = ", ".join(x for x in (b.staff_name, b.service) if x)
        lines.append(f"- {b.id}: {fmt_slot(b.start)}" + (f" — {extra}" if extra else ""))
    return "\n".join(lines + [CANCEL_RULE])


@dataclass
class CancelResult:
    booking: Booking | None = None  # cancelled here
    freed_slot_id: int | None = None  # offer it to the waiting list
    reply: str | None = None  # replaces the model's reply when the cancel did not happen here
    note: str = ""  # for staff
    handoff: str = ""  # a request staff must act on


def cancel(session: Session, conv: Conversation, booking_id: object, now_local: datetime) -> CancelResult:
    try:
        bid = int(booking_id)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        bid = 0
    booking = session.get(Booking, bid) if bid else None
    if booking is None or booking.conversation_id != conv.id or booking.status != "booked" or booking.start <= now_local:
        return CancelResult(reply=NOT_FOUND_REPLY, handoff="Клиент просит отменить запись, но такой предстоящей записи "
                                                            "в этом чате нет. Свяжитесь с клиентом.")
    who = ", ".join(x for x in (booking.customer_name, booking.customer_phone) if x) or "клиент"
    when = fmt_slot(booking.start) + (f", {booking.staff_name}" if booking.staff_name else "")
    if booking.external_id:
        return CancelResult(reply=EXTERNAL_REPLY,
                            handoff=f"Клиент просит отменить запись {when} ({who}). Отмените её в Altegio "
                                    f"(запись №{booking.external_id}); в Joop она закроется сама.")
    booking.status = "cancelled"
    session.add(booking)
    slot = session.get(Slot, booking.slot_id) if booking.slot_id else None
    if slot is not None:
        release_slot(session, slot.id, seats_needed(slot, booking.party_size))
    session.flush()
    return CancelResult(booking=booking, freed_slot_id=slot.id if slot is not None else None,
                        note=f"Клиент отменил запись в чате: {when}, {who}. Время снова свободно.")
