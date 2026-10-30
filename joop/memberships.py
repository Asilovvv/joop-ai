"""Passes and packages of visits: staff record them, the AI answers "сколько у меня осталось?".

A chat is matched to a pass only on a phone the business can trust: the WhatsApp number the customer
writes from, or a phone typed in Telegram/Instagram by someone who has already been to a visit booked
from that chat. A phone typed by a stranger reveals nothing.
"""

from __future__ import annotations

import re
from datetime import date, datetime

from sqlmodel import Session, select

from .models import Booking, Business, Conversation, Membership

_DIGITS = re.compile(r"\D")


def phone_key(phone: str) -> str:
    digits = _DIGITS.sub("", phone or "")
    return digits[-9:] if len(digits) >= 9 else ""


def left(m: Membership) -> int | None:
    """Visits left, None for an unlimited pass."""
    return None if not m.visits_total else max(0, m.visits_total - m.visits_used)


def usable(m: Membership, today: date) -> bool:
    return m.active and (m.valid_until is None or m.valid_until >= today) and (left(m) is None or left(m) > 0)


def trusted_phone(session: Session, conv: Conversation, now_local: datetime) -> str:
    if conv.channel == "whatsapp":
        return phone_key(conv.chat_id)
    key = phone_key(conv.customer_phone)
    if not key:
        return ""
    visited = session.exec(select(Booking.id).where(Booking.conversation_id == conv.id, Booking.status == "booked",
                                                    Booking.start < now_local)).first()
    return key if visited else ""


def for_chat(session: Session, business: Business, conv: Conversation, now_local: datetime) -> list[Membership]:
    key = trusted_phone(session, conv, now_local)
    if not key:
        return []
    return list(session.exec(select(Membership).where(Membership.business_id == business.id, Membership.phone_key == key,
                                                      Membership.active == True)  # noqa: E712
                             .order_by(Membership.created_at.desc())).all())


def describe(m: Membership, today: date) -> str:
    parts = [f"«{m.title}»"]
    n = left(m)
    parts.append("безлимит" if n is None else f"осталось {n} из {m.visits_total} посещений")
    if m.valid_until:
        parts.append(("действует до " if m.valid_until >= today else "истёк ") + f"{m.valid_until:%d.%m.%Y}")
    return ", ".join(parts)


def prompt_hint(session: Session, business: Business, conv: Conversation, now_local: datetime) -> str:
    if conv.id is None:
        return ""
    items = for_chat(session, business, conv, now_local)
    today = now_local.date()
    if items:
        lines = ["", "Абонементы этого клиента (данные администратора):"]
        lines += [f"- {describe(m, today)}" for m in items[:3]]
        lines.append("Об остатке и сроке абонемента отвечай только по этим данным. Если посещений не осталось "
                     "или срок истёк, предложи продлить: это оформляет администратор (заполни handoff).")
        return "\n".join(lines)
    return ("\nЕсли клиент спрашивает об остатке абонемента, данных в переписке нет: не называй цифры, скажи, что "
            "уточнишь у администратора, и заполни handoff.")
