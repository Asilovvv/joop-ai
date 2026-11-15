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

from sqlmodel import Session

from . import waitlist
from .confirm import fmt_slot_ky
from .followups import _kyrgyz, deliver_to_chat
from .models import Booking, Business, Conversation, Slot, Staff
from .slots import claim_slot, release_slot, seats_needed
from .timeutil import fmt_slot

if TYPE_CHECKING:
    from .runtime import Runtime


@dataclass
class Moved:
    problem: str = ""  # why it did not move, in the panel's words; empty when it did
    told: bool = False  # the customer got the new time in their chat


def reschedule(s: Session, rt: "Runtime", business: Business, booking: Booking, slot: Slot, now_local: datetime,
               now_utc: datetime, hidden_staff: set[int] = frozenset()) -> Moved:
    """Move `booking` to `slot`. The caller checked both belong to `business` and commits."""
    if booking.status != "booked":
        return Moved("Запись отменена: переносить нечего.")
    if booking.external_id:
        return Moved("Запись есть в Altegio: перенесите её там, Joop подхватит изменение.")
    if slot.id == booking.slot_id:
        return Moved("Это то же самое время.")
    member = s.get(Staff, slot.staff_id)
    if member is None or not member.active or member.id in hidden_staff:
        return Moved("Такого времени нет.")
    if slot.start <= now_local or not claim_slot(s, slot.id, seats_needed(slot, booking.party_size)):
        return Moved("Это время уже занято. Выберите другое.")
    old = s.get(Slot, booking.slot_id) if booking.slot_id else None
    if old is not None:
        release_slot(s, old.id, seats_needed(old, booking.party_size))
    booking.slot_id, booking.staff_id, booking.staff_name, booking.start = slot.id, member.id, member.name, slot.start
    booking.reminder_status, booking.confirmed_at = "", None  # both were about the old time
    s.add(booking)
    s.flush()
    if old is not None:
        s.refresh(old)
        waitlist.offer_freed_slot(s, rt, business, old, now_utc)
    conv = s.get(Conversation, booking.conversation_id) if booking.conversation_id else None
    if conv is None:
        return Moved()
    text = (f"Жазылууңуз {fmt_slot_ky(slot.start)} убакытка жылдырылды ({member.name}). "
            "Ыңгайсыз болсо, ушул жерге жазыңыз." if _kyrgyz(s, conv.id)
            else f"Ваша запись перенесена на {fmt_slot(slot.start)} ({member.name}). Если неудобно — напишите сюда.")
    return Moved(told=deliver_to_chat(s, rt, business, conv, text, now_utc))
