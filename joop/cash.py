"""Visit payments and the day's cash: what came in, by what, by whom — typed as one tap, counted by code.

МойСклад and Bitrix24 sell "финансовый учёт" as a separate module with invoices and acts. A salon needs one
thing: after the visit, how much the customer paid and how (cash, card, transfer), and at the end of the day the
total by master. Joop asks for exactly that: on a past booking the amount is pre-filled from the price list (plus
the accepted add-on) and one tap with the method records it. The «Касса» page shows the day and the month by
method, master and service; the morning summary carries yesterday's total. Nothing is a tax document — it is the
owner's own count, exported like the customers.

The fiscal receipt is not Joop's: in Kyrgyzstan settlements with individuals go through a cash register (ККМ) from the
State Tax Service registry (Tax Code art. 128), and Joop is not one. What Joop does is keep the master from forgetting
it: each payment carries a «чек ККМ пробит» mark, the day counts the payments without one, and once the business uses
the mark the morning summary does too.
See docs/kkm-kg.md.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta

from sqlmodel import Session, select

from .models import Booking, Business, Service
from .stats import not_test

METHODS = {"cash": "наличные", "card": "карта", "transfer": "перевод"}
MAX_PAYMENT = 10_000_000  # som; anything above is a typo


def suggested(session: Session, booking: Booking) -> int:
    """The price-list amount for this visit: the service's exact price plus the accepted add-on; 0 when unknown."""
    name = booking.service or ""
    extra = 0
    if booking.upsell_status == "accepted" and " + " in name:
        name, extra = name.rsplit(" + ", 1)[0], booking.upsell_price
    row = session.exec(select(Service).where(Service.business_id == booking.business_id, Service.price_value != None)).all()  # noqa: E711
    prices = {s.name.casefold(): s.price_value for s in row}
    return (prices.get(name.casefold(), 0) or 0) + extra


def record(booking: Booking, amount: int, method: str, now_utc: datetime, receipt: bool = False) -> None:
    booking.paid_som = max(0, amount)
    booking.paid_method = method if method in METHODS else ""
    booking.paid_at = now_utc if amount > 0 else None
    booking.receipt_at = now_utc if amount > 0 and receipt else None


def mark_receipt(booking: Booking, now_utc: datetime) -> None:
    if booking.paid_som:
        booking.receipt_at = now_utc


@dataclass
class Day:
    date: datetime
    rows: list[Booking]
    total: int = 0
    by_method: dict[str, int] = field(default_factory=dict)
    by_staff: dict[str, int] = field(default_factory=dict)
    unpaid: list[Booking] = field(default_factory=list)  # visits that passed without a payment: ask the master
    no_receipt: list[Booking] = field(default_factory=list)  # paid, but no fiscal receipt marked


@dataclass
class Month:
    total: int = 0
    visits: int = 0
    by_staff: list[tuple[str, int]] = field(default_factory=list)
    by_service: list[tuple[str, int]] = field(default_factory=list)
    by_method: dict[str, int] = field(default_factory=dict)


def _visits(session: Session, business: Business, start: datetime, end: datetime, staff_id: int | None = None) -> list[Booking]:
    own = [Booking.staff_id == staff_id] if staff_id else []
    return session.exec(select(Booking).where(Booking.business_id == business.id, Booking.status == "booked", not_test(Booking),
                                              Booking.start >= start, Booking.start < end, *own).order_by(Booking.start)).all()


def day(session: Session, business: Business, date_local: datetime, now_local: datetime, staff_id: int | None = None) -> Day:
    start = datetime.combine(date_local.date(), time.min)
    rows = _visits(session, business, start, start + timedelta(days=1), staff_id)
    d = Day(date=start, rows=rows)
    for b in rows:
        if b.paid_som:
            d.total += b.paid_som
            d.by_method[b.paid_method] = d.by_method.get(b.paid_method, 0) + b.paid_som
            d.by_staff[b.staff_name or "—"] = d.by_staff.get(b.staff_name or "—", 0) + b.paid_som
            if b.receipt_at is None:
                d.no_receipt.append(b)
        elif b.start < now_local:
            d.unpaid.append(b)
    return d


def month(session: Session, business: Business, date_local: datetime, staff_id: int | None = None) -> Month:
    start = datetime.combine(date_local.date().replace(day=1), time.min)
    end = (start + timedelta(days=32)).replace(day=1)
    m = Month()
    staff: Counter = Counter()
    services: Counter = Counter()
    for b in _visits(session, business, start, end, staff_id):
        if not b.paid_som:
            continue
        m.total += b.paid_som
        m.visits += 1
        staff[b.staff_name or "—"] += b.paid_som
        services[(b.service or "визит").rsplit(" + ", 1)[0]] += b.paid_som
        m.by_method[b.paid_method] = m.by_method.get(b.paid_method, 0) + b.paid_som
    m.by_staff, m.by_service = staff.most_common(), services.most_common(8)
    return m


def digest_line(session: Session, business: Business, now_local: datetime) -> str:
    """Yesterday's cash for the morning summary; empty when nothing was recorded."""
    d = day(session, business, now_local - timedelta(days=1), now_local)
    if not d.total:
        return ""
    parts = ", ".join(f"{METHODS.get(k, k)} {som(v)}" for k, v in d.by_method.items())
    line = f"Касса за вчера: {som(d.total)} сом ({parts}), оплачено визитов {sum(1 for b in d.rows if b.paid_som)}."
    if d.no_receipt and _marks_receipts(session, business, now_local):
        line += f" Без отметки о чеке ККМ: {len(d.no_receipt)} — проверьте, что чек пробит."
    return line


def _marks_receipts(session: Session, business: Business, now_local: datetime) -> bool:
    """The business uses the «чек ККМ» mark (some payment this month or last carries it): only then is a missing one news."""
    since = datetime.combine((now_local.date().replace(day=1) - timedelta(days=1)).replace(day=1), time.min)
    return session.exec(select(Booking.id).where(Booking.business_id == business.id, Booking.receipt_at != None,  # noqa: E711
                                                 Booking.start >= since)).first() is not None


def som(n: int) -> str:
    return f"{n:,}".replace(",", " ")
