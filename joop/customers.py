"""The customer card: everything the business knows about one person, assembled from what the AI already wrote down.

The CRMs an integrator sells (amoCRM, Bitrix24, МойСклад, Altéjo) all have a "work with customers" screen that a
person fills in; the integrator's own advice is "CRM нужно вести", and that is why it dies in a salon. Joop's
card is not typed by anyone: a customer is a phone (the last nine digits, as loyalty and regulars match them),
and the card is the bookings, orders, ratings and dialogues the AI already stored for that phone, plus two
fields a person may add — a note and tags. Chats without a phone are listed by name under their messenger id,
so nobody is lost. The list exports to CSV for the owner's own spreadsheet.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import datetime

from sqlmodel import Session, select

from .models import Booking, Business, Conversation, Customer, Order, Service
from .stats import TEST_CHANNEL

_DIGITS = re.compile(r"\D")
TAG_LIMIT = 200
NOTE_LIMIT = 1000


def key_of(phone: str | None, channel: str = "", chat_id: str = "") -> str:
    """Nine digits of the phone; without a phone, the chat itself («telegram:1001»)."""
    digits = _DIGITS.sub("", phone or "")[-9:]
    if len(digits) == 9:
        return digits
    return f"{channel}:{chat_id}" if channel and chat_id else ""


@dataclass
class Card:
    key: str
    name: str = ""
    phone: str = ""
    channels: set[str] = field(default_factory=set)
    conversations: list[Conversation] = field(default_factory=list)
    bookings: list[Booking] = field(default_factory=list)
    orders: list[Order] = field(default_factory=list)
    spend_som: int = 0
    last_contact: datetime | None = None
    note: str = ""
    tags: str = ""

    @property
    def visits(self) -> int:
        return sum(1 for b in self.bookings if b.status == "booked")

    @property
    def last_visit(self) -> datetime | None:
        past = [b.start for b in self.bookings if b.status == "booked"]
        return max(past) if past else None

    @property
    def rating(self) -> float | None:
        marks = [b.rating for b in self.bookings if b.rating]
        return round(sum(marks) / len(marks), 1) if marks else None

    @property
    def tag_list(self) -> list[str]:
        return [t.strip() for t in self.tags.split(",") if t.strip()]


def _prices(session: Session, business_id: int) -> dict[str, int]:
    return {s.name.casefold(): s.price_value for s in session.exec(select(Service).where(
        Service.business_id == business_id, Service.price_value != None)).all()}  # noqa: E711


def cards(session: Session, business: Business) -> dict[str, Card]:
    """Every customer of the business, keyed; nothing typed by hand except notes and tags."""
    out: dict[str, Card] = {}

    def card(key: str) -> Card:
        if key not in out:
            out[key] = Card(key=key)
        return out[key]

    for conv in session.exec(select(Conversation).where(Conversation.business_id == business.id, Conversation.channel != TEST_CHANNEL)).all():
        key = key_of(conv.customer_phone, conv.channel, conv.chat_id)
        if not key:
            continue
        c = card(key)
        c.conversations.append(conv)
        c.channels.add(conv.channel)
        c.name = c.name or conv.customer_name or conv.display_name
        c.phone = c.phone or conv.customer_phone
        if conv.last_customer_at and (c.last_contact is None or conv.last_customer_at > c.last_contact):
            c.last_contact = conv.last_customer_at
    prices = _prices(session, business.id)
    for b in session.exec(select(Booking).where(Booking.business_id == business.id, Booking.channel != TEST_CHANNEL)).all():
        key = key_of(b.customer_phone, b.channel, "") or _conv_key(out, b.conversation_id)
        if not key:
            continue
        c = card(key)
        c.bookings.append(b)
        c.name = c.name or b.customer_name
        c.phone = c.phone or b.customer_phone
        if b.status == "booked" and b.service and b.service.casefold() in prices:
            c.spend_som += prices[b.service.casefold()]
    for o in session.exec(select(Order).where(Order.business_id == business.id, Order.status != "cancelled", Order.channel != TEST_CHANNEL)).all():
        key = key_of(o.customer_phone, o.channel, "") or _conv_key(out, o.conversation_id)
        if not key:
            continue
        c = card(key)
        c.orders.append(o)
        c.name = c.name or o.customer_name
        c.phone = c.phone or o.customer_phone
        c.spend_som += o.total or 0
    for row in session.exec(select(Customer).where(Customer.business_id == business.id)).all():
        if row.key in out:
            out[row.key].note, out[row.key].tags = row.note, row.tags
    for c in out.values():
        c.bookings.sort(key=lambda b: b.start, reverse=True)
        c.orders.sort(key=lambda o: o.created_at, reverse=True)
    return out


def _conv_key(out: dict[str, Card], conversation_id: int | None) -> str:
    if not conversation_id:
        return ""
    for key, c in out.items():
        if any(conv.id == conversation_id for conv in c.conversations):
            return key
    return ""


def listing(session: Session, business: Business, query: str = "", tag: str = "") -> list[Card]:
    rows = [c for c in cards(session, business).values()
            if c.phone or c.bookings or c.orders or c.channels - {"web"}]  # an anonymous site visitor is not a customer yet
    q = query.strip().casefold()
    qd = _DIGITS.sub("", query)
    if q:
        rows = [c for c in rows if q in c.name.casefold() or (qd and qd in _DIGITS.sub("", c.phone))]
    if tag:
        rows = [c for c in rows if tag in c.tag_list]
    rows.sort(key=lambda c: (c.last_contact or c.last_visit or datetime.min), reverse=True)
    return rows


def save_note(session: Session, business: Business, key: str, note: str, tags: str) -> Customer:
    row = session.exec(select(Customer).where(Customer.business_id == business.id, Customer.key == key)).first()
    if row is None:
        row = Customer(business_id=business.id, key=key)
    row.note = note.strip()[:NOTE_LIMIT]
    row.tags = ", ".join(dict.fromkeys(t.strip() for t in tags.split(",") if t.strip()))[:TAG_LIMIT]
    session.add(row)
    return row


def export_csv(rows: list[Card], tz: str) -> str:
    from .timeutil import utc_to_local

    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Имя", "Телефон", "Каналы", "Визитов", "Последний визит", "Последнее обращение", "Сумма по прайсу, сом", "Оценка", "Теги", "Заметка"])
    for c in rows:
        w.writerow([c.name, c.phone, ", ".join(sorted(c.channels)), c.visits,
                    c.last_visit.strftime("%d.%m.%Y") if c.last_visit else "",
                    utc_to_local(c.last_contact, tz).strftime("%d.%m.%Y") if c.last_contact else "",
                    c.spend_som, c.rating or "", c.tags, c.note])
    return "﻿" + buf.getvalue()  # the BOM makes Excel read UTF-8
