"""Waitlist: a customer who could not get the time they wanted is told first when a slot that day frees up.

Entries are made by code when the AI takes a booking request without a slot in a business that has slots.
They are offered a freed slot when staff cancel a booking or reopen a slot in the panel. The customer
answers in the chat and the AI books as usual, so a slot is never promised to two people.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from sqlmodel import Session, select

from .followups import deliver_to_chat
from .lang import is_kyrgyz_message
from .models import Business, Conversation, Lead, Message, Slot, Staff, WaitlistEntry
from .niches import get_pack
from .slots import LEAD_MINUTES, requested_time
from .timeutil import fmt_slot, utc_to_local

if TYPE_CHECKING:
    from .runtime import Runtime

KEEP = timedelta(days=14)  # older entries are not offered anything
OFFER_TO = 3  # customers told about one freed slot; the first to answer gets it


def waiting_line(kyrgyz: bool) -> str:
    return " Ошол күнү убакыт бошоп калса, дароо жазам." if kyrgyz else " Если на этот день освободится время, я сразу напишу."


def add_entry(session: Session, business: Business, conv: Conversation, lead: Lead, data: dict, now_utc: datetime,
              customer_text: str) -> WaitlistEntry | None:
    if not get_pack(business.niche).has("booking"):
        return None  # hotels and tours take requests only: nothing to free up
    today = utc_to_local(now_utc, business.timezone).date()
    texts = [str(data.get("preferred_time") or ""), customer_text]
    texts += session.exec(select(Message.text).where(Message.conversation_id == conv.id, Message.role == "customer")
                          .order_by(Message.id.desc()).limit(4)).all()
    wanted = next((t for t in (requested_time(x, today) for x in texts if x) if t), None)
    day = wanted.date() if wanted else None
    entry = session.exec(select(WaitlistEntry).where(WaitlistEntry.conversation_id == conv.id,
                                                     WaitlistEntry.status == "waiting")).first()
    if entry is None:
        entry = WaitlistEntry(business_id=business.id, conversation_id=conv.id, channel=conv.channel, chat_id=conv.chat_id,
                              created_at=now_utc)
    entry.lead_id, entry.day = lead.id, day
    entry.service = str(data.get("service") or "")[:200]
    entry.customer_name, entry.customer_phone = conv.customer_name, conv.customer_phone
    session.add(entry)
    session.flush()
    return entry


def offer_text(slot: Slot, member: Staff | None, kyrgyz: bool) -> str:
    who = f" ({member.name})" if member else ""
    if kyrgyz:
        return (f"Жакшы кабар: убакыт бошоду — {fmt_slot(slot.start)}{who}. Сизди жазып коёюнбу? "
                "Башка бирөө ээлеп ала электе жооп бериңиз.")
    return f"Хорошая новость: освободилось время — {fmt_slot(slot.start)}{who}. Записать вас? Ответьте, пока его не заняли."


def offer_freed_slot(session: Session, rt: "Runtime", business: Business, slot: Slot, now_utc: datetime) -> int:
    """Tell the first customers waiting for this day. Returns how many were told."""
    now_local = utc_to_local(now_utc, business.timezone)
    if slot.status != "free" or slot.start <= now_local + timedelta(minutes=LEAD_MINUTES):
        return 0
    entries = session.exec(select(WaitlistEntry).where(
        WaitlistEntry.business_id == business.id, WaitlistEntry.status == "waiting",
        WaitlistEntry.created_at >= now_utc - KEEP,
    ).order_by(WaitlistEntry.created_at)).all()
    member = session.get(Staff, slot.staff_id)
    told = 0
    for entry in entries:
        if told >= OFFER_TO:
            break
        if entry.day is not None and entry.day != slot.start.date():
            continue
        conv = session.get(Conversation, entry.conversation_id) if entry.conversation_id else None
        last = session.exec(select(Message.text).where(Message.conversation_id == entry.conversation_id,
                                                       Message.role == "customer").order_by(Message.id.desc())).first()
        if deliver_to_chat(session, rt, business, conv, offer_text(slot, member, bool(last) and is_kyrgyz_message(last)), now_utc):
            entry.status, entry.notified_at = "notified", now_utc
            session.add(entry)
            told += 1
    return told


def mark_booked(session: Session, conversation_id: int) -> None:
    for entry in session.exec(select(WaitlistEntry).where(WaitlistEntry.conversation_id == conversation_id,
                                                          WaitlistEntry.status.in_(["waiting", "notified"]))).all():
        entry.status = "booked"
        session.add(entry)
