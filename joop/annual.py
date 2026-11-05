"""The year offer at the end of the second paid month: who to make it to, and the text to send.

Monthly subscribers leave quietly; a business that paid twice has seen what the AI does and is the one to ask for
a year. The founder is reminded in the console (and in the Monday digest) about every business whose second paid
month is ending, with a ready message in the business's own numbers — conversations answered and bookings made
since the first payment, counted from the database. The discount is the founder's decision: `ANNUAL_MONTHS` (a
year for the price of that many months, e.g. 10) turns the text on; until it is set the console only names who
is due. Marked as offered by hand, so the same business is not nagged about twice. Competitors sell yearly plans
with two months free and lock the price for the year (docs: «Joop AI — стратегия с нуля»).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlmodel import Session, select

from . import billing
from .case import _som, build
from .models import Business, Payment, Subscription

SECOND_MONTH_ENDS_WITHIN = timedelta(days=14)
YEAR_DAYS = 365


@dataclass
class Candidate:
    business: Business
    sub: Subscription
    months_paid: int
    first_paid_at: datetime
    price: int  # a month, som
    annual_months: int

    @property
    def annual_price(self) -> int:
        return self.price * self.annual_months

    @property
    def saves(self) -> int:
        return self.price * 12 - self.annual_price


def candidates(session: Session, now: datetime, default_price: int, annual_months: int) -> list[Candidate]:
    """Paying businesses with two or more monthly payments whose paid period ends within two weeks, no year yet."""
    out: list[Candidate] = []
    for sub in session.exec(select(Subscription).where(Subscription.status == "active", Subscription.plan == "pro")).all():
        if sub.cancelled_at or sub.year_offered_at or not sub.paid_until or sub.paid_until - now > SECOND_MONTH_ENDS_WITHIN:
            continue
        if billing.state(sub, now).code not in ("active", "grace"):
            continue  # the month ran out and nobody paid: that is a lost customer, not a year offer
        paid = session.exec(select(Payment).where(Payment.business_id == sub.business_id, Payment.status == "paid").order_by(Payment.paid_at)).all()
        if len(paid) < 2 or any(p.period_days >= YEAR_DAYS for p in paid):
            continue
        price = billing.price_for(sub, default_price)
        business = session.get(Business, sub.business_id)
        if business is None or price <= 0:
            continue
        out.append(Candidate(business, sub, len(paid), paid[0].paid_at or paid[0].created_at, price, annual_months))
    return out


def offer_text(session: Session, c: Candidate, now: datetime) -> str:
    """What the founder sends, in the business's own numbers; empty until ANNUAL_MONTHS is set."""
    if c.annual_months <= 0:
        return ""
    days = max(7, min((now - c.first_paid_at).days or 1, 365))
    case = build(session, c.business, now, days=days)
    until = max(c.sub.paid_until, now) + timedelta(days=YEAR_DAYS)  # the year starts where the paid month ends
    name = c.business.name if c.business.name.startswith("«") else f"«{c.business.name}»"
    return (f"{name}, вы с Joop AI уже {c.months_paid}-й месяц: с первой оплаты ИИ ответил {case.conversations} клиентам и записал "
            f"{case.bookings}. Предложение на год: {_som(c.annual_price)} сом за 12 месяцев вместо {_som(c.price * 12)} — "
            f"{c.annual_months} месяцев по цене, {12 - c.annual_months} в подарок, и цена не меняется до {until:%d.%m.%Y}. "
            "Если удобно — ответьте «да», и я пришлю счёт.")


def digest_line(session: Session, now: datetime, default_price: int, annual_months: int) -> str:
    rows = candidates(session, now, default_price, annual_months)
    return (" Предложить год: " + ", ".join(c.business.name for c in rows) + ".") if rows else ""
