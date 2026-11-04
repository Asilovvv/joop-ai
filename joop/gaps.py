"""Empty slots in the week ahead, and the customers to invite into them.

The one move that turns an AI administrator from a saving into revenue (docs: «Joop AI — стратегия с нуля»,
"Пустые окна"): instead of waiting for someone to write, the business fills next week's free times with its own
regulars. Code lists who is due — the service's repeat interval has passed, or a regular has not been seen for
a month — who has no upcoming booking, did not opt out and was not invited in the last two weeks; for each, a
drafted message with the two nearest free times, preferring the specialist they last saw. The owner sends one
at a time or all at once; WhatsApp and Instagram customers outside the 24-hour window are listed as calls, with
the phone, because no message can reach them. Nothing goes out without a click. The Altegio marketplace's free
"who to invite" app only prints the list; Joop also sends.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import func
from sqlmodel import Session, select

from .followups import SERVICE_WINDOW, _kyrgyz, _service_for, deliver_to_chat
from .models import Booking, Business, Conversation, Service, Slot, Staff
from .slots import free_slots
from .stats import TEST_CHANNEL
from .timeutil import fmt_slot, local_to_utc

if TYPE_CHECKING:
    from .runtime import Runtime

DAYS = 7
ABSENT_DAYS = 30  # a regular not seen this long is worth a message even without a service interval
MIN_VISITS = 2  # ...if they came at least twice
QUIET_DAYS = 14  # one invitation, then leave them alone for two weeks
LIMIT = 30
_DIGITS = re.compile(r"\D")


@dataclass
class Candidate:
    conversation_id: int
    name: str
    phone: str
    channel: str
    reason: str
    service: str
    staff: str
    last_visit: datetime
    reachable: bool
    slots: list[tuple[datetime, str]] = field(default_factory=list)
    text: str = ""


@dataclass
class Day:
    date: datetime
    free: int
    total: int


def week(session: Session, business: Business, now_local: datetime) -> list[Day]:
    """Free and total slots per day for the next seven days."""
    start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    rows = session.exec(select(Slot.start, Slot.status).join(Staff, Staff.id == Slot.staff_id).where(
        Slot.business_id == business.id, Staff.active == True, Slot.start >= now_local,  # noqa: E712
        Slot.start < start + timedelta(days=DAYS),
    )).all()
    days = []
    for i in range(DAYS):
        day = start + timedelta(days=i)
        on_day = [st for at, st in rows if at.date() == day.date()]
        if on_day:
            days.append(Day(day, sum(1 for st in on_day if st == "free"), len(on_day)))
    return days


def _key(phone: str) -> str:
    d = _DIGITS.sub("", phone or "")[-9:]
    return d if len(d) == 9 else ""


def _text(business: Business, name: str, service: str, staff: str, slots: list[tuple[datetime, str]], kyrgyz: bool) -> str:
    times = " или ".join(fmt_slot(at) for at, _ in slots)
    who = staff or (slots[0][1] if slots else "")
    title = business.name if "«" in business.name else f"«{business.name}»"
    if kyrgyz:
        head = f"Саламатсызбы, {name}! " if name else "Саламатсызбы! "
        return (head + f"{title} салонунда{(' ' + who + ' чеберде') if who else ''} бош убакыт бар: {times}. "
                + (f"«{service}» кызматына жазып коёюнбу? " if service else "Жазып коёюнбу? ") + "«Ооба» деп же башка ыңгайлуу убакытты жазыңыз.")
    head = f"Здравствуйте, {name}! " if name else "Здравствуйте! "
    return (head + f"В {title} есть свободное время{(' у ' + who) if who else ''}: {times}. "
            + (f"Записать вас на «{service}»? " if service else "Записать вас? ") + "Напишите «да» или другое удобное время.")


def candidates(session: Session, business: Business, now_local: datetime) -> list[Candidate]:
    today = now_local.date()
    now_utc = local_to_utc(now_local, business.timezone)
    services = list(session.exec(select(Service).where(Service.business_id == business.id)).all())
    staff_ids = {s.name: s.id for s in session.exec(select(Staff).where(Staff.business_id == business.id, Staff.active == True)).all()}  # noqa: E712
    bookings = session.exec(select(Booking).where(
        Booking.business_id == business.id, Booking.status == "booked", Booking.channel != TEST_CHANNEL,
    ).order_by(Booking.start.desc())).all()
    by_phone: dict[str, list[Booking]] = {}
    for b in bookings:
        key = _key(b.customer_phone) or (f"conv:{b.conversation_id}" if b.conversation_id else "")
        if key:
            by_phone.setdefault(key, []).append(b)
    out: list[Candidate] = []
    for key, rows in by_phone.items():
        if any(b.start >= now_local for b in rows):
            continue  # already coming
        last = rows[0]
        if last.conversation_id is None:
            continue  # no chat to write to (a booking made in the panel by phone)
        conv = session.get(Conversation, last.conversation_id)
        if conv is None or conv.channel == TEST_CHANNEL or conv.broadcast_opt_out:
            continue
        if conv.invited_at and now_utc - conv.invited_at < timedelta(days=QUIET_DAYS):
            continue
        service = _service_for([s for s in services if s.repeat_days > 0], last)
        days_ago = (today - last.start.date()).days
        if service is not None and days_ago + DAYS >= service.repeat_days:
            reason = f"пора: {service.name} раз в {service.repeat_days} дн., прошло {days_ago}"
            service_name = service.name
        elif days_ago >= ABSENT_DAYS and len(rows) >= MIN_VISITS:
            reason = f"давно не был(а): {days_ago} дн., визитов {len(rows)}"
            service_name = last.service or ""
        else:
            continue
        staff_id = staff_ids.get(last.staff_name or "")
        pair = free_slots(session, business.id, now_local, days=DAYS, limit=2, staff_id=staff_id) if staff_id else []
        if not pair:
            pair = free_slots(session, business.id, now_local, days=DAYS, limit=2)
        if not pair:
            continue  # nothing to invite into
        slots = [(slot.start, st.name) for slot, st in pair]
        in_window = bool(conv.last_customer_at and now_utc - conv.last_customer_at < SERVICE_WINDOW)
        reachable = conv.channel == "telegram" or (conv.channel in ("whatsapp", "instagram") and in_window)
        name = conv.customer_name or last.customer_name or ""
        out.append(Candidate(conversation_id=conv.id, name=name, phone=last.customer_phone or conv.customer_phone, channel=conv.channel,
                             reason=reason, service=service_name, staff=last.staff_name if staff_id else "", last_visit=last.start,
                             reachable=reachable, slots=slots,
                             text=_text(business, name, service_name, last.staff_name if staff_id else "", slots, _kyrgyz(session, conv.id))))
        if len(out) >= LIMIT:
            break
    out.sort(key=lambda c: (not c.reachable, c.last_visit))
    return out


def send(session: Session, rt: "Runtime", business: Business, cand: Candidate, now_utc: datetime) -> bool:
    conv = session.get(Conversation, cand.conversation_id)
    ok = deliver_to_chat(session, rt, business, conv, cand.text, now_utc)
    if ok:
        conv.invited_at = now_utc
        session.add(conv)
    return ok


def week_numbers(session: Session, business: Business, since_utc: datetime) -> tuple[int, int]:
    """Invitations sent in the period, and how many of those customers booked afterwards."""
    convs = session.exec(select(Conversation).where(
        Conversation.business_id == business.id, Conversation.invited_at >= since_utc, Conversation.channel != TEST_CHANNEL,
    )).all()
    booked = sum(session.exec(select(func.count()).select_from(Booking).where(
        Booking.conversation_id == c.id, Booking.created_at >= c.invited_at)).one() > 0 for c in convs)
    return len(convs), booked

