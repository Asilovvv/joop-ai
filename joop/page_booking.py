"""Booking by link without a chat: /m/<slug>/book (joop/web/booking_page.py).

The customer picks a free time, gives a name and a phone, and the booking lands in the schedule under the rules the
AI books by (joop/api.py `book`): a real person's free time after the niche's lead time, a working subscription, a
table big enough for the party. Altegio sells the same as its core product (strategy «Лучшие идеи», 19.11.2026); here
it is the first use a new business gets with no model key and no Meta verification: one link for the Instagram bio,
2GIS and a QR code.

Nobody chats with this customer, so there is no prepayment (nowhere to send the details: the API's rule), the
reminder the day before goes to staff as «напомните вручную» (joop/scheduler.py), and the confirmation page offers a
calendar file with an alarm. The source is "page": the AI's figures do not count these bookings.

A public form is a spam target: a signed form token that must be a few seconds old, a hidden field people never fill,
and limits per address (in memory), per phone and per business a day (in the database).
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import date, datetime, time, timedelta

from sqlmodel import Session, func, select

from . import api
from .billing import access_ok
from .models import Booking, Business, Slot, Staff
from .niches import get_pack
from .phone import display_phone
from .timeutil import fmt_slot, local_to_utc

SOURCE = "page"
MIN_FILL = 2  # seconds: a person reads the form and types a name and a phone; a script posts at once
MAX_FILL = 2 * 3600  # a form this old shows times long gone: pick again
PER_PHONE_AHEAD = 3  # upcoming page bookings for one phone: a mother books herself and two children
PER_BUSINESS_DAY = 100  # page bookings a business takes a day: a flood stops here
PER_ADDRESS_DAY = 10  # from one address a day (an office or a café shares one): counted in memory by the web module
MAX_PARTY = 20  # the guests field of a table booking


def unavailable(session: Session, business: Business, now_utc: datetime) -> str:
    """"" when customers can book on the page, else why not: page | niche | altegio | off | unpaid."""
    if not business.menu_enabled:
        return "page"
    if not get_pack(business.niche).has("booking"):
        return "niche"
    if business.altegio_location_id:
        return "altegio"  # the salon's schedule and its own online booking live in Altegio
    if not business.page_booking:
        return "off"
    if not access_ok(session, business.id, now_utc):
        return "unpaid"
    return ""


def free_times(session: Session, business: Business, now_local: datetime) -> list[tuple[Slot, Staff]]:
    """The next fortnight's bookable times, earliest first: the API's (sign-up example people excluded)."""
    return api.bookable(session, business, None, now_local)


def one_per_time(rows: list[tuple[Slot, Staff]]) -> list[tuple[Slot, Staff]]:
    """«Любой специалист»: one free time per start, the first person by name (Altegio's «any professional»)."""
    seen: dict[datetime, tuple[Slot, Staff]] = {}
    for slot, member in sorted(rows, key=lambda r: (r[0].start, r[1].name, r[0].id)):
        seen.setdefault(slot.start, (slot, member))
    return list(seen.values())


def by_day(rows: list[tuple[Slot, Staff]]) -> dict[date, list[tuple[Slot, Staff]]]:
    days: dict[date, list[tuple[Slot, Staff]]] = {}
    for slot, member in rows:
        days.setdefault(slot.start.date(), []).append((slot, member))
    return days


def party_limit(slot: Slot, member: Staff) -> int:
    """How many guests the form may ask for: a table's seats (capped); 1 for a person's time or a class seat, where
    each person books their own place."""
    return min(member.capacity, MAX_PARTY) if member.capacity else 1


# --- signed tokens ----------------------------------------------------------------------------------------


def _sign(secret: str, text: str) -> str:
    return hmac.new(secret.encode(), text.encode(), hashlib.sha256).hexdigest()[:32]


def form_token(secret: str, business_id: int, slot_id: int, issued: int) -> str:
    return f"{issued}.{_sign(secret, f'form|{business_id}|{slot_id}|{issued}')}"


def form_age(secret: str, business_id: int, slot_id: int, token: str, now: float) -> float | None:
    """Seconds since this business's form for this time was shown; None when the token is not one."""
    issued, _, sig = (token or "").partition(".")
    if not issued.isdigit() or len(issued) > 12:
        return None
    if not hmac.compare_digest(sig, _sign(secret, f"form|{business_id}|{slot_id}|{issued}")):
        return None
    return now - int(issued)


def done_token(secret: str, booking: Booking) -> str:
    """The confirmation page's address: only the person who booked has it."""
    return f"{booking.id}.{_sign(secret, f'done|{booking.business_id}|{booking.id}')}"


def booking_for(session: Session, business: Business, secret: str, token: str) -> Booking | None:
    raw, _, sig = (token or "").partition(".")
    if not raw.isdigit() or len(raw) > 12:
        return None
    booking = session.get(Booking, int(raw))
    if booking is None or booking.business_id != business.id or booking.source != SOURCE:
        return None
    return booking if hmac.compare_digest(sig, _sign(secret, f"done|{business.id}|{booking.id}")) else None


# --- the reminder in Telegram ---------------------------------------------------------------------------

REMIND_START = "b"  # t.me/<bot>?start=b<booking id>_<signature>: the confirmation page's «Напомнить в Telegram»
KY_MARK = "_ky"  # appended when the customer booked on the Kyrgyz page: the bot answers in Kyrgyz


def reminder_coming(business: Business, booking: Booking, now_local: datetime) -> bool:
    """Will the reminder round on the eve of the visit still run (joop/scheduler.py: once a day at reminder_hour, for
    tomorrow's bookings)? Not for a visit today, nor for tomorrow's once today's round is done or its hours passed."""
    from .scheduler import JOB_WINDOW_HOURS

    eve, today = booking.start.date() - timedelta(days=1), now_local.date()
    if eve != today:
        return eve > today
    return business.last_reminder_date != today.isoformat() and now_local.hour < business.reminder_hour + JOB_WINDOW_HOURS


def remind_link(business: Business, booking: Booking, now_local: datetime, lang: str = "ru") -> str:
    """One tap ties the booking to the customer's Telegram chat with the business's bot: the reminder the day before
    then goes there with its «да» question, instead of to staff as «напомните вручную». Signed with the bot token,
    which only the server holds (Telegram allows 64 characters of letters, digits and _)."""
    if not (business.telegram_bot_token and business.telegram_bot_username and business.bot_enabled):
        return ""
    if not reminder_coming(business, booking, now_local):
        return ""  # never promise a reminder nobody will send: staff already have the phone in their alert
    return (f"https://t.me/{business.telegram_bot_username}?start={REMIND_START}{booking.id}_{_remind_sig(business, booking.id)}"
            + (KY_MARK if lang == "ky" else ""))


def _remind_sig(business: Business, booking_id: int) -> str:
    return _sign(business.telegram_bot_token, f"remind|{business.id}|{booking_id}")[:20]


def take_reminder(session: Session, business: Business, argument: str, channel: str, chat_id: str,
                  conversation_id: int | None, now_local: datetime) -> Booking | None:
    """/start b<id>_<sig> in Telegram: the page booking now has this chat. None when the link is not one of ours,
    the booking is gone or past, or it already has a chat."""
    if channel != "telegram" or not argument.startswith(REMIND_START):
        return None
    raw, _, sig = argument[len(REMIND_START):].partition("_")
    if not raw.isdigit() or len(raw) > 12 or not business.telegram_bot_token:
        return None
    booking = session.get(Booking, int(raw))
    if (booking is None or booking.business_id != business.id or booking.source != SOURCE or booking.status != "booked"
            or booking.start <= now_local or booking.chat_id or not reminder_coming(business, booking, now_local)
            or not hmac.compare_digest(sig, _remind_sig(business, booking.id))):
        return None
    booking.channel, booking.chat_id, booking.conversation_id = channel, chat_id, conversation_id
    session.add(booking)
    return booking


# --- limits and the staff's note ---------------------------------------------------------------------------


def refused(session: Session, business: Business, phone: str, now_local: datetime, now_utc: datetime) -> str:
    """Why this phone may not book on the page now: "phone" (it already has PER_PHONE_AHEAD upcoming page bookings),
    "busy" (the business took PER_BUSINESS_DAY page bookings today), "" when it may."""
    ahead = session.exec(select(func.count()).select_from(Booking).where(
        Booking.business_id == business.id, Booking.source == SOURCE, Booking.status == "booked",
        Booking.customer_phone == phone, Booking.start >= now_local)).one()
    if ahead >= PER_PHONE_AHEAD:
        return "phone"
    midnight = local_to_utc(datetime.combine(now_local.date(), time.min), business.timezone)
    today = session.exec(select(func.count()).select_from(Booking).where(
        Booking.business_id == business.id, Booking.source == SOURCE, Booking.created_at >= midnight)).one()
    return "busy" if today >= PER_BUSINESS_DAY else ""


def staff_note(booking: Booking) -> str:
    """For the staff's alerts chat: nobody chatted with this customer, so the phone is how to reach them. A booking
    staff made from the panel's browser says so: the customer did not book by themselves."""
    return (f"Новая запись со страницы: {booking.customer_name}, {display_phone(booking.customer_phone)}"
            + (f", {booking.service}" if booking.service else "")
            + (f", гостей: {booking.party_size}" if booking.party_size > 1 else "")
            + f" — {fmt_slot(booking.start)}, {booking.staff_name}. "
            + ("Записал сотрудник на странице записи." if booking.by_staff else "Клиент записался сам, без переписки."))


# --- calendar file -------------------------------------------------------------------------------------


def _escape(text: str) -> str:
    return (text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", ""))


def _fold(line: str) -> list[str]:
    """RFC 5545: lines of at most 75 octets, continued on the next line after a space; never inside a character."""
    out, current = [], ""
    for ch in line:
        limit = 75 if not out else 74  # a continuation line starts with the space
        if len((current + ch).encode()) > limit:
            out.append(current)
            current = ch
        else:
            current += ch
    out.append(current)
    return [out[0]] + [" " + part for part in out[1:]]


def ics(business: Business, booking: Booking, minutes: int, address: str, phone: str, now_utc: datetime) -> str:
    """One event with an alarm two hours before: the customer's phone reminds them, as no chat will.
    `address` and `phone` as customers may read them (samples.customer_contact: never the sign-up example's)."""
    start = local_to_utc(booking.start, business.timezone)
    end = start + timedelta(minutes=minutes if minutes > 0 else 60)
    title = f"{booking.service or 'Запись'} — {business.name}"
    details = ", ".join(x for x in (booking.staff_name, display_phone(phone) if phone else "") if x)
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Joop AI//booking page//RU", "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
             "BEGIN:VEVENT", f"UID:booking-{booking.id}-{booking.business_id}@joop", f"DTSTAMP:{now_utc:%Y%m%dT%H%M%SZ}",
             f"DTSTART:{start:%Y%m%dT%H%M%SZ}", f"DTEND:{end:%Y%m%dT%H%M%SZ}", f"SUMMARY:{_escape(title)}"]
    if address:
        lines.append(f"LOCATION:{_escape(address)}")
    if details:
        lines.append(f"DESCRIPTION:{_escape(details)}")
    lines += ["BEGIN:VALARM", "TRIGGER:-PT2H", "ACTION:DISPLAY", f"DESCRIPTION:{_escape(title)}", "END:VALARM",
              "END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(part for line in lines for part in _fold(line)) + "\r\n"
