"""Offer one add-on right after a booking: "Хотите добавить дизайн ногтей — 300 сом?".

The owner chooses, per service, one other service to offer with it ("Прайс" → "Что предложить к записи"). The offer
is written by code, not by the model, so the price is the price list's and the prompt does not change:
- after an AI booking for a service that has an add-on with an exact price, the confirmation gets one line;
- "да" (or "ооба", "давайте", "добавьте"…) within two hours adds the add-on to the booking and tells staff to check
  the time; "нет" closes the offer politely; anything else goes to the AI as usual;
- no offer when the same reply already asks for prepayment or intake answers, so one message asks one thing.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from sqlmodel import Session, select

from .lang import is_kyrgyz_message
from .models import Booking, Business, Conversation, Message, Service
from .timeutil import fmt_slot

ANSWER_WINDOW = timedelta(hours=2)
YES = {"да", "давайте", "давай", "добавьте", "добавь", "хочу", "ок", "окей", "ok", "yes", "конечно", "да добавьте",
       "да давайте", "ооба", "макул", "кошуңуз", "кошуп коюңуз", "ооба кошуңуз", "болот", "ага"}
NO = {"нет", "не надо", "не нужно", "нет спасибо", "не", "no", "жок", "керек эмес", "жок рахмат", "спасибо нет"}
_NOT_WORD = re.compile(r"[^\w\s]")


def _norm(text: str) -> str:
    return " ".join(_NOT_WORD.sub(" ", (text or "").lower().replace("ё", "е")).split())


def _service_of(services: list[Service], booking: Booking) -> Service | None:
    name = (booking.service or "").strip().lower()
    if not name:
        return None
    for s in services:
        for candidate in (s.name, s.name_ky):
            c = candidate.strip().lower()
            if c and (c in name or name in c):
                return s
    return None


def _price(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def offer(session: Session, business: Business, booking: Booking, kyrgyz: bool) -> str:
    """The line to add to the booking confirmation ("" when there is nothing to offer); marks the booking."""
    if booking.deposit_status == "awaiting" or booking.intake_status == "asked":
        return ""
    services = list(session.exec(select(Service).where(Service.business_id == business.id)).all())
    base = _service_of([s for s in services if s.upsell_id], booking)
    addon = next((s for s in services if base and s.id == base.upsell_id), None)
    if addon is None or not addon.available or not addon.price_value or addon.id == base.id:
        return ""
    booking.upsell_status, booking.upsell_service, booking.upsell_price = "offered", addon.name, addon.price_value
    session.add(booking)
    if kyrgyz:
        return f"\n\nЖазылууга «{addon.name_ky or addon.name}» кошуп коёлубу — {_price(addon.price_value)} сом? «Ооба» деп жооп бериңиз."
    return f"\n\nХотите добавить «{addon.name}» — {_price(addon.price_value)} сом? Ответьте «да», и я добавлю к записи."


def capture(session: Session, conv: Conversation, text: str, now_utc: datetime) -> tuple[str, str] | None:
    """(reply, staff note) for "да" or "нет" right after an offer; None for any other message."""
    answer = _norm(text)
    if answer not in YES and answer not in NO:
        return None
    booking = session.exec(select(Booking).where(
        Booking.conversation_id == conv.id, Booking.status == "booked", Booking.upsell_status == "offered",
        Booking.created_at >= now_utc - ANSWER_WINDOW,
    ).order_by(Booking.id.desc())).first()
    if booking is None:
        return None
    last_ai = session.exec(select(Message.text).where(Message.conversation_id == conv.id, Message.role == "ai")
                           .order_by(Message.id.desc())).first()
    if not last_ai or f"— {_price(booking.upsell_price)} сом?" not in last_ai:
        return None  # the AI asked something else since: this "да" answers that
    kyrgyz = answer in {"ооба", "макул", "кошуңуз", "кошуп коюңуз", "ооба кошуңуз", "болот", "жок", "керек эмес", "жок рахмат"} \
        or is_kyrgyz_message(text)
    if answer in NO:
        booking.upsell_status = "declined"
        session.add(booking)
        return ("Макул, жазылуу ошол бойдон калат." if kyrgyz else "Хорошо, запись остаётся как есть."), ""
    booking.upsell_status = "accepted"
    booking.service = f"{booking.service} + {booking.upsell_service}"[:200]
    session.add(booking)
    when = fmt_slot(booking.start)
    reply = (f"Кошуп койдум: «{booking.upsell_service}», {when}. Күтөбүз!" if kyrgyz
             else f"Добавила «{booking.upsell_service}» к вашей записи на {when}. Ждём вас!")
    note = (f"Допродажа: {booking.customer_name}, {booking.customer_phone} добавил(а) «{booking.upsell_service}» "
            f"(+{_price(booking.upsell_price)} сом) к записи {when}"
            + (f", {booking.staff_name}" if booking.staff_name else "") + ". Проверьте, хватает ли времени.")
    return reply, note


def accepted_total(session: Session, business_id: int, since_utc: datetime, until_utc: datetime) -> tuple[int, int]:
    """(customers who added an add-on, som) for reports."""
    rows = session.exec(select(Booking.upsell_price).where(
        Booking.business_id == business_id, Booking.upsell_status == "accepted",
        Booking.created_at >= since_utc, Booking.created_at < until_utc)).all()
    return len(rows), sum(rows)
