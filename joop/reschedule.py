"""Moving a booking to another free time: the customer phoned «можно на час позже?».

Until now staff cancelled and booked again, which lost the booking's history (the chat it came from, the deposit,
the upsell) and sent no word to the customer. Here the booking keeps its row and moves: the new time is taken
with claim_slot as the AI takes it, the old one is freed and offered to the waiting list as a cancellation is,
the reminder and the customer's «да» are reset (they were about the old time), and the customer is told in their
chat where the channel allows it. Bookings that went to Altegio are moved in Altegio: Joop does not edit records
there.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from sqlmodel import Session, update

from . import waitlist
from .confirm import fmt_slot_ky
from .deposits import BEFORE_START
from .followups import REVIEW_AFTER, _kyrgyz, deliver_to_chat
from .models import Booking, Business, Conversation, Slot, Staff
from .slots import claim_slot, release_slot, seats_needed
from .timeutil import fmt_dt, fmt_slot, local_to_utc, utc_to_local

if TYPE_CHECKING:
    from .runtime import Runtime


@dataclass
class Moved:
    problem: str = ""  # why it did not move, in the panel's words; empty when it did
    told: bool = False  # the customer got the new time in their chat


def blocked(booking: Booking, now_local: datetime) -> str:
    """Why this booking cannot be moved at all, whatever the time; empty when it can.

    Only a visit that has not happened moves. A paid one happened: the cash counts it on its day (joop/cash.py). One
    whose time passed long enough ago for Joop to ask how it went (followups.REVIEW_AFTER) is a past visit too; until
    then a customer who is late can still be moved to a later hour."""
    if booking.status != "booked":
        return "Запись отменена: переносить нечего."
    if booking.external_id:
        return "Запись есть в Altegio: перенесите её там, Joop подхватит изменение."
    if booking.paid_som:
        return "По этой записи уже отмечена оплата: визит состоялся. Для нового визита запишите клиента заново."
    if booking.start <= now_local - REVIEW_AFTER:
        return "Этот визит уже прошёл. Если клиент не пришёл и хочет другое время — запишите его заново, а эту запись отмените."
    return ""


@dataclass
class Move:
    problem: str = ""
    old: Slot | None = None  # the time given back; free unless staff closed it
    member: Staff | None = None


def move(s: Session, business: Business, booking: Booking, slot: Slot, now_local: datetime,
         hidden_staff: set[int] | frozenset[int] = frozenset()) -> Move:
    """Move `booking` to `slot`: the core the panel, the app and the AI share. Nothing is sent from here; the
    caller offers the freed time to the waiting list and tells whom it must. The caller commits."""
    if blocked(booking, now_local):
        return Move(blocked(booking, now_local))
    if slot.id == booking.slot_id:
        return Move("Это то же самое время.")
    member = s.get(Staff, slot.staff_id)
    if member is None or not member.active or member.id in hidden_staff:
        return Move("Такого времени нет.")
    if booking.deposit_status == "awaiting" and booking.deposit_deadline is not None \
            and local_to_utc(slot.start, business.timezone) - BEFORE_START < booking.deposit_deadline:
        # the prepayment deadline would fall after the visit, and a business that releases unpaid bookings
        # (deposit_auto_cancel) would lose the one staff have just moved
        until = fmt_dt(utc_to_local(booking.deposit_deadline, business.timezone))
        return Move(f"По этой записи ждём предоплату до {until}, а новое время раньше. "
                    "Отметьте предоплату полученной или выберите время позже.")
    if member.capacity and booking.party_size > member.capacity:  # the same rule as the AI's booking
        return Move(f"Этот стол рассчитан на {member.capacity} гостей, а в записи {booking.party_size}. Выберите стол побольше.")
    if slot.start <= now_local or not claim_slot(s, slot.id, seats_needed(slot, booking.party_size)):
        return Move("Это время уже занято. Выберите другое.")
    old_id = booking.slot_id
    # Moved only if nobody moved or cancelled it since this page read it: two quick «перенести» presses must not
    # both free the old time (the second would free a time the AI has meanwhile given to someone else).
    moved = s.exec(update(Booking)
                   .where(Booking.id == booking.id, Booking.status == "booked",
                          Booking.slot_id == old_id if old_id is not None else Booking.slot_id.is_(None))
                   .values(slot_id=slot.id, staff_id=member.id, staff_name=member.name, start=slot.start,
                           reminder_status="", confirmed_at=None))  # reminder and «да» were about the old time
    if moved.rowcount != 1:
        release_slot(s, slot.id, seats_needed(slot, booking.party_size))
        s.refresh(booking)
        return Move("Запись только что изменили. Обновите страницу и посмотрите её время.")
    s.refresh(booking)
    old = s.get(Slot, old_id) if old_id else None
    if old is not None:
        release_slot(s, old.id, seats_needed(old, booking.party_size))
    s.flush()
    if old is not None:
        s.refresh(old)
    return Move(old=old, member=member)


def cancel(s: Session, booking: Booking) -> tuple[bool, Slot | None]:
    """Cancel a booked visit and give its time back: whether it was still booked, and the slot freed (free unless
    staff closed it). Atomic, so two quick cancels free the time once. Nothing is sent from here; the caller commits."""
    done = s.exec(update(Booking).where(Booking.id == booking.id, Booking.status == "booked")
                  .values(status="cancelled")).rowcount == 1
    s.refresh(booking)
    if not done:
        return False, None
    slot = s.get(Slot, booking.slot_id) if booking.slot_id else None
    release_slot(s, booking.slot_id, seats_needed(slot, booking.party_size) if slot else 1)
    s.flush()
    if slot is not None:
        s.refresh(slot)
    return True, slot


def reschedule(s: Session, rt: "Runtime", business: Business, booking: Booking, slot: Slot, now_local: datetime,
               now_utc: datetime, hidden_staff: set[int] = frozenset()) -> Moved:
    """Move `booking` to `slot` (move()), offer the old time to the waiting list and tell the customer. The caller
    checked both belong to `business` and commits."""
    done = move(s, business, booking, slot, now_local, hidden_staff)
    if done.problem:
        return Moved(done.problem)
    member = done.member
    if done.old is not None:
        waitlist.offer_freed_slot(s, rt, business, done.old, now_utc)
    conv = s.get(Conversation, booking.conversation_id) if booking.conversation_id else None
    if conv is None:
        return Moved()
    text = (f"Жазылууңуз {fmt_slot_ky(slot.start)} убакытка жылдырылды ({member.name}). "
            "Ыңгайсыз болсо, ушул жерге жазыңыз." if _kyrgyz(s, conv.id)
            else f"Ваша запись перенесена на {fmt_slot(slot.start)} ({member.name}). Если неудобно — напишите сюда.")
    return Moved(told=deliver_to_chat(s, rt, business, conv, text, now_utc))
