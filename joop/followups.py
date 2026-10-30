"""After-visit follow-ups: a rating request a few hours after the visit, and an invitation to come again.

Both are off until the company turns them on (panel "Отзывы и возврат"). Messages go only where the
channel allows them: Telegram any time, WhatsApp and Instagram within 24 hours of the customer's last
message. What cannot be sent is listed for the staff to do by hand.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from typing import TYPE_CHECKING

from sqlmodel import Session, select

from .lang import is_kyrgyz_message
from .models import Booking, Business, Conversation, Lead, Message, Service
from .timeutil import fmt_slot, utc_to_local

if TYPE_CHECKING:
    from .runtime import Runtime

SERVICE_WINDOW = timedelta(hours=23)
REVIEW_AFTER = timedelta(hours=2)  # after the start of the visit
REVIEW_UNTIL = timedelta(hours=48)  # do not ask about old visits
RATING_REPLY_WINDOW = timedelta(hours=72)
REVIEW_HOURS = (10, 21)  # local hours when the request may be sent
RETURN_LATE_DAYS = 3  # still invite if the job ran a few days late
_RATING = re.compile(r"^\s*([1-5])\s*(?:/\s*5|из\s*5|балл\w*|звезд\w*|звёзд\w*|жылдыз\w*|упай\w*)?\s*[.!]?\s*$", re.I)
_DIGITS = re.compile(r"\D")


def _plural(n: int, one: str, few: str, many: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return one
    return few if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else many


def _kyrgyz(session: Session, conversation_id: int | None) -> bool:
    if not conversation_id:
        return False
    m = session.exec(select(Message.text).where(Message.conversation_id == conversation_id, Message.role == "customer")
                     .order_by(Message.id.desc())).first()
    return bool(m) and is_kyrgyz_message(m)


def deliver_to_chat(session: Session, rt: "Runtime", business: Business, conv: Conversation | None, text: str,
                    now_utc: datetime) -> bool:
    """Send a message the business starts, where the channel allows it, and keep it in the dialogue."""
    if conv is None or not conv.chat_id:
        return False
    in_window = bool(conv.last_customer_at and now_utc - conv.last_customer_at < SERVICE_WINDOW)
    if conv.channel != "telegram" and not (conv.channel in {"whatsapp", "instagram"} and in_window):
        return False
    client = rt.channel_client(business, conv.channel)
    if not (client and client.send_text(conv.chat_id, text)):
        return False
    session.add(Message(business_id=business.id, conversation_id=conv.id, role="ai", text=text, created_at=now_utc))
    conv.last_message_at = now_utc
    session.add(conv)
    return True


def _deliver(session: Session, rt: "Runtime", business: Business, booking: Booking, text: str, now_utc: datetime) -> bool:
    conv = session.get(Conversation, booking.conversation_id) if booking.conversation_id else None
    return deliver_to_chat(session, rt, business, conv, text, now_utc)


# --- ratings -----------------------------------------------------------------------------------


def review_request_text(business: Business, kyrgyz: bool) -> str:
    if kyrgyz:
        return (f"«{business.name}» келгениңизге рахмат! Сураныч, келгениңизди 1ден 5ке чейин баалаңыз — "
                "бир сан менен жооп бериңиз.")
    return f"Спасибо, что были у нас в «{business.name}»! Оцените, пожалуйста, визит от 1 до 5 — ответьте одной цифрой."


def send_review_requests(session: Session, rt: "Runtime", business: Business, now_utc: datetime) -> int:
    if not business.review_requests:
        return 0
    now_local = utc_to_local(now_utc, business.timezone)
    if not REVIEW_HOURS[0] <= now_local.hour < REVIEW_HOURS[1]:
        return 0
    bookings = session.exec(select(Booking).where(
        Booking.business_id == business.id, Booking.status == "booked", Booking.review_status == "",
        Booking.start <= now_local - REVIEW_AFTER, Booking.start >= now_local - REVIEW_UNTIL,
    )).all()
    sent = 0
    for b in bookings:
        ok = _deliver(session, rt, business, b, review_request_text(business, _kyrgyz(session, b.conversation_id)), now_utc)
        b.review_status, b.review_asked_at = ("asked", now_utc) if ok else ("skipped", None)
        session.add(b)
        sent += ok
    return sent


@dataclass
class RatingResult:
    reply: str
    admin_note: str = ""
    lead_id: int | None = None


def capture_rating(session: Session, business: Business, conv: Conversation, text: str, now_utc: datetime,
                   off: bool = False) -> RatingResult | None:
    """A bare "5" (or "4 из 5") right after a rating request is the rating, not a question for the AI."""
    m = _RATING.match(text or "")
    if not m:
        return None
    booking = session.exec(select(Booking).where(
        Booking.conversation_id == conv.id, Booking.review_status == "asked",
        Booking.review_asked_at >= now_utc - RATING_REPLY_WINDOW,
    ).order_by(Booking.review_asked_at.desc())).first()
    if booking is None:
        return None
    rating = int(m.group(1))
    booking.rating, booking.review_status = rating, "rated"
    session.add(booking)
    kyrgyz = is_kyrgyz_message(text) or _kyrgyz(session, conv.id)
    if rating >= 4:
        if business.review_url:
            reply = (f"Баалаганыңызга рахмат! Мүмкүн болсо, пикир калтырып коюңуз — бул бизге абдан жардам берет: {business.review_url}"
                     if kyrgyz else f"Спасибо за оценку! Если не трудно, оставьте отзыв — это очень помогает нам: {business.review_url}")
        else:
            reply = "Баалаганыңызга рахмат! Сизди дагы күтөбүз." if kyrgyz else "Спасибо за оценку! Будем рады видеть вас снова."
        return RatingResult(reply=reply)
    reply = ("Чынчыл баалаганыңызга рахмат. Бир нерсе туура эмес болгонуна өкүнөбүз — администраторго билдирдим, ал сиз менен байланышат."
             if kyrgyz else "Спасибо, что честно оценили. Жаль, что что-то пошло не так — я передала администратору, он свяжется с вами.")
    who = ", ".join(x for x in (booking.customer_name, booking.customer_phone) if x) or "клиент"
    visit = f"{fmt_slot(booking.start)}" + (f", {booking.service}" if booking.service else "") + (f", {booking.staff_name}" if booking.staff_name else "")
    summary = f"Низкая оценка {rating}/5 после визита ({visit}): {who}. Свяжитесь с клиентом."
    lead = Lead(business_id=business.id, conversation_id=conv.id, kind="handoff", summary=summary,
                customer_name=booking.customer_name, customer_phone=booking.customer_phone, channel=conv.channel,
                chat_id=conv.chat_id, created_at=now_utc, off_hours=off)
    session.add(lead)
    session.flush()
    return RatingResult(reply=reply, admin_note=summary, lead_id=lead.id)


# --- invitations to come again -----------------------------------------------------------------


def _service_for(services: list[Service], booking: Booking) -> Service | None:
    name = (booking.service or "").strip().lower()
    if not name:
        return None
    for s in services:
        if s.repeat_days <= 0:
            continue
        for candidate in (s.name, s.name_ky):
            c = candidate.strip().lower()
            if c and (c in name or name in c):
                return s
    return None


def return_text(business: Business, service: Service, days: int, kyrgyz: bool) -> str:
    if kyrgyz:
        title = service.name_ky or service.name
        return (f"Саламатсызбы! «{business.name}» акыркы жолу «{title}» болгонуна {days} күн өттү. "
                "Кайра жазып коёюнбу? Ыңгайлуу убакытты тандап берем.")
    return (f"Здравствуйте! С прошлого визита в «{business.name}» ({service.name}) прошло {days} "
            f"{_plural(days, 'день', 'дня', 'дней')}. Записать вас снова? Подберу удобное время.")


def _came_back(bookings: list[Booking], b: Booking) -> bool:
    phone = _DIGITS.sub("", b.customer_phone)[-9:]
    for other in bookings:
        if other.id == b.id or other.start <= b.start:
            continue
        if (b.conversation_id and other.conversation_id == b.conversation_id) or (
                len(phone) == 9 and _DIGITS.sub("", other.customer_phone)[-9:] == phone):
            return True
    return False


def send_return_invites(session: Session, rt: "Runtime", business: Business, now_utc: datetime) -> dict[str, int]:
    if not business.return_invites:
        return {"sent": 0, "manual": 0}
    services = list(session.exec(select(Service).where(Service.business_id == business.id, Service.repeat_days > 0)).all())
    if not services:
        return {"sent": 0, "manual": 0}
    today = utc_to_local(now_utc, business.timezone).date()
    longest = max(s.repeat_days for s in services) + RETURN_LATE_DAYS + 1
    all_bookings = list(session.exec(select(Booking).where(
        Booking.business_id == business.id, Booking.status == "booked",
        Booking.start >= datetime.combine(today - timedelta(days=longest), datetime.min.time()),
    )).all())
    sent, manual = 0, []
    for b in all_bookings:
        if b.return_status:
            continue
        service = _service_for(services, b)
        if service is None:
            continue
        due = b.start.date() + timedelta(days=service.repeat_days)
        if not due <= today <= due + timedelta(days=RETURN_LATE_DAYS) or _came_back(all_bookings, b):
            continue
        days = (today - b.start.date()).days
        ok = _deliver(session, rt, business, b, return_text(business, service, days, _kyrgyz(session, b.conversation_id)), now_utc)
        b.return_status = "sent" if ok else "manual"
        session.add(b)
        if ok:
            sent += 1
        else:
            manual.append(f"{b.customer_name or 'клиент'}, {b.customer_phone or 'телефон не указан'} — {service.name}, {days} дн. назад")
    if manual:
        from .dispatch import notify_admins  # the engine imports this module; dispatch imports the engine

        notify_admins(rt, business, ["Пора пригласить снова (написать не получилось — свяжитесь сами):\n" + "\n".join(manual)])
    return {"sent": sent, "manual": len(manual)}


# --- numbers for the panel ---------------------------------------------------------------------


@dataclass
class FollowupStats:
    rated: int
    average: float | None
    low: int
    asked: int
    invited: int
    returned: int


def stats(session: Session, business_id: int, since: datetime) -> FollowupStats:
    rows = list(session.exec(select(Booking).where(Booking.business_id == business_id, Booking.start >= since)).all())
    everything = list(session.exec(select(Booking).where(Booking.business_id == business_id, Booking.status == "booked")).all())
    ratings = [b.rating for b in rows if b.rating]
    invited = [b for b in rows if b.return_status in {"sent", "manual"}]
    return FollowupStats(
        rated=len(ratings), average=round(sum(ratings) / len(ratings), 1) if ratings else None,
        low=sum(1 for r in ratings if r <= 3), asked=sum(1 for b in rows if b.review_status in {"asked", "rated"}),
        invited=len(invited), returned=sum(1 for b in invited if _came_back(everything, b)),
    )
