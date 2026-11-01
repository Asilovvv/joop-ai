"""Prepayment for a booking, asked in the chat right after the AI books.

The business sets the amount, how to pay (bank transfer by phone number, a payment link or QR from its bank)
and how many hours the customer has. Joop does not take the money: it tells the customer how to pay, takes
"оплатил" or a photo of the receipt as "please check", and staff mark the payment in the panel. If nothing
comes by the deadline, staff are told, or, when the business chose so, the booking is released and the
customer is told why.

Booking.deposit_status: "" (not asked) | awaiting | check (customer says paid) | paid | overdue (staff told)
| expired (released automatically).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from sqlmodel import Session, select

from .channels.base import IncomingMessage
from .followups import _kyrgyz, deliver_to_chat
from .lang import is_kyrgyz_message
from .models import Booking, Business, Conversation, Slot
from .slots import release_slot, seats_needed
from .timeutil import fmt_slot, local_to_utc, utc_to_local

if TYPE_CHECKING:
    from .runtime import Runtime

MAX_HOURS = 48
BEFORE_START = timedelta(hours=1)  # the deadline is never later than an hour before the visit
MIN_TIME = timedelta(minutes=20)  # less time than this to pay: do not ask, the visit is too soon
RECEIPTS = {"фото", "файл"}  # media labels that can be a receipt
_PAID = re.compile(r"\b(оплатил[аи]?|оплачено|оплата\s+(прошла|отправлена)|перев[её]л[аи]?|скинул[аи]?|"
                   r"отправил[аи]?\s+(деньги|оплату|предоплату|чек)|төлөдүм|төлөп\s+койдум|которуп\s+койдум|"
                   r"акча\s+жибердим)\b", re.I)
OPEN = ("awaiting", "overdue")


def says_paid(text: str) -> bool:
    """A short statement like "оплатила" or "перевёл, проверьте" — not a question like "а как оплатить?"."""
    t = (text or "").strip()
    return 0 < len(t) <= 60 and "?" not in t and bool(_PAID.search(t))


def enabled(business: Business) -> bool:
    return business.deposit_amount > 0 and bool(business.deposit_details.strip())


def _when(dt_local: datetime, now_local: datetime) -> str:
    return f"{dt_local:%H:%M}" if dt_local.date() == now_local.date() else f"{dt_local:%d.%m %H:%M}"


def require(business: Business, booking: Booking, now_utc: datetime) -> bool:
    """Mark a fresh AI booking as waiting for prepayment. False when it is off or the visit is too soon."""
    if not enabled(business):
        return False
    hours = max(1, min(business.deposit_hours or 2, MAX_HOURS))
    deadline = min(now_utc + timedelta(hours=hours), local_to_utc(booking.start, business.timezone) - BEFORE_START)
    if deadline - now_utc < MIN_TIME:
        return False
    booking.deposit_due, booking.deposit_status, booking.deposit_deadline = business.deposit_amount, "awaiting", deadline
    return True


def _amount(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def reply_line(business: Business, booking: Booking, now_utc: datetime, kyrgyz: bool) -> str:
    if booking.deposit_status != "awaiting" or booking.deposit_deadline is None:
        return ""
    now_local = utc_to_local(now_utc, business.timezone)
    until = _when(utc_to_local(booking.deposit_deadline, business.timezone), now_local)
    details = business.deposit_details.strip()
    if kyrgyz:
        line = (f"\n\nЖазылууну бекитүү үчүн {_amount(booking.deposit_due)} сом алдын ала төлөө керек. Кантип төлөө: {details}. "
                f"{until} чейин төлөп, чекти (скриншот) ушул жерге жибериңиз.")
        return line + (" Төлөнбөсө, убакыт бошотулат." if business.deposit_auto_cancel else "")
    line = (f"\n\nЧтобы закрепить запись, нужна предоплата {_amount(booking.deposit_due)} сом. Как оплатить: {details}. "
            f"Оплатите до {until} и пришлите сюда чек (скриншот).")
    return line + (" Без предоплаты время освободится." if business.deposit_auto_cancel else "")


def note_line(business: Business, booking: Booking) -> str:
    if booking.deposit_status != "awaiting" or booking.deposit_deadline is None:
        return ""
    until = utc_to_local(booking.deposit_deadline, business.timezone)
    return f"Ждём предоплату {_amount(booking.deposit_due)} сом до {until:%d.%m %H:%M}."


def prompt_line(business: Business) -> str:
    """For the model: it must not invent payment details, and it can answer "нужна ли предоплата?"."""
    if not enabled(business):
        return ""
    return (f"Для записи нужна предоплата {_amount(business.deposit_amount)} сом. Как и до какого времени оплатить, "
            "система напишет клиенту сама сразу после записи — реквизиты сам не называй и не придумывай.")


# --- the customer says they paid ---------------------------------------------------------------


@dataclass
class Captured:
    reply: str
    note: str


def capture(session: Session, business: Business, conv: Conversation, incoming: IncomingMessage, text: str,
            now_utc: datetime) -> Captured | None:
    """A receipt photo or "оплатил(а)" while a booking of this chat waits for prepayment."""
    is_receipt = incoming.kind == "media" and incoming.media_label in RECEIPTS
    if not (is_receipt or (incoming.kind == "text" and says_paid(text))):
        return None
    booking = session.exec(select(Booking).where(
        Booking.conversation_id == conv.id, Booking.status == "booked", Booking.deposit_status.in_(OPEN),
    ).order_by(Booking.id.desc())).first()
    if booking is None:
        return None
    booking.deposit_status = "check"
    session.add(booking)
    kyrgyz = is_kyrgyz_message(text) or _kyrgyz(session, conv.id)
    reply = ("Рахмат! Администратор төлөмдү текшерип, жазылууңузду ырастайт." if kyrgyz
             else "Спасибо! Администратор проверит оплату и подтвердит запись.")
    what = "прислал(а) чек" if is_receipt else f"пишет: «{(text or '')[:80]}»"
    note = (f"Предоплата: {booking.customer_name}, {booking.customer_phone} {what} по записи {fmt_slot(booking.start)}. "
            f"Проверьте поступление {_amount(booking.deposit_due)} сом и отметьте в панели («Записи» → «Предоплата получена»).")
    return Captured(reply=reply, note=note)


# --- staff and the deadline --------------------------------------------------------------------


def mark_paid(session: Session, rt: "Runtime", business: Business, booking: Booking, now_utc: datetime) -> bool:
    """Staff saw the money. Tell the customer; returns whether the message went out."""
    booking.deposit_status = "paid"
    session.add(booking)
    conv = session.get(Conversation, booking.conversation_id) if booking.conversation_id else None
    if conv is None:
        return False
    text = (f"Алдын ала төлөм келди, рахмат! Сизди {fmt_slot(booking.start)} күтөбүз." if _kyrgyz(session, conv.id)
            else f"Предоплата получена, спасибо! Ждём вас {fmt_slot(booking.start)}.")
    return deliver_to_chat(session, rt, business, conv, text, now_utc)


def _release(session: Session, booking: Booking) -> Slot | None:
    booking.status = "cancelled"
    session.add(booking)
    slot = session.get(Slot, booking.slot_id) if booking.slot_id else None
    release_slot(session, booking.slot_id, seats_needed(slot, booking.party_size) if slot else 1)
    session.flush()
    if slot is not None:
        session.refresh(slot)
    return slot


def check_deadlines(session: Session, rt: "Runtime", business: Business, now_utc: datetime) -> dict[str, int]:
    """Bookings whose prepayment did not come in time: tell staff, or release them if the business chose so."""
    late = session.exec(select(Booking).where(
        Booking.business_id == business.id, Booking.status == "booked", Booking.deposit_status == "awaiting",
        Booking.deposit_deadline <= now_utc,
    ).order_by(Booking.id)).all()
    if not late:
        return {}
    from . import waitlist
    from .dispatch import notify_admins

    released, overdue, notes = 0, 0, []
    for booking in late:
        who = f"{booking.customer_name}, {booking.customer_phone}"
        if business.deposit_auto_cancel:
            booking.deposit_status = "expired"
            slot = _release(session, booking)
            conv = session.get(Conversation, booking.conversation_id) if booking.conversation_id else None
            kyrgyz = bool(conv) and _kyrgyz(session, conv.id)
            text = (f"Алдын ала төлөм келген жок, ошондуктан {fmt_slot(booking.start)} убактысы бошотулду. "
                    "Кааласаңыз, кайра жазам — ыңгайлуу убакытты жазыңыз." if kyrgyz else
                    f"Предоплата не поступила, поэтому время {fmt_slot(booking.start)} освобождено. "
                    "Если хотите, запишу снова — напишите удобное время.")
            told = deliver_to_chat(session, rt, business, conv, text, now_utc) if conv else False
            offered = waitlist.offer_freed_slot(session, rt, business, slot, now_utc) if slot is not None else 0
            notes.append(f"Запись снята: {who}, {fmt_slot(booking.start)} — предоплата не пришла к сроку."
                         + ("" if told else " Клиенту сообщите сами.")
                         + (f" Время предложено из листа ожидания: {offered}." if offered else ""))
            released += 1
        else:
            booking.deposit_status = "overdue"
            session.add(booking)
            notes.append(f"Предоплата не пришла к сроку: {who}, запись {fmt_slot(booking.start)}. "
                         "Свяжитесь с клиентом или отмените запись в панели.")
            overdue += 1
    notify_admins(rt, business, notes)
    return {"released": released, "overdue": overdue}
