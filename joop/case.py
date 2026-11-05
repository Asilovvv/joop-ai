"""A case with real numbers: what the AI did for one business over a period, as a page to publish.

The strategy's content loop (docs: «Joop AI — стратегия с нуля», "как находить клиентов"): nobody among the local
competitors publishes a case with a named Bishkek business and numbers; the first to do so wins. Every number here
is counted from the database — conversations, how many came outside working hours, bookings the AI made and what
they are worth at the business's own price list, ratings — nothing estimated, nothing typed in. The founder opens
the page from the console, screenshots it for Instagram or sends the link, in Russian or Kyrgyz. Only exact prices
count; bookings without one are named as not counted.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlmodel import Session, select

from .followups import stats as followup_stats
from .models import Booking, Business, Lead, Message, Order, Service
from .niches import get_pack
from .stats import TEST_CHANNEL, real_messages


@dataclass
class Case:
    business: Business
    lang: str
    days: int
    since: datetime
    until: datetime
    conversations: int = 0
    off_conversations: int = 0
    bookings: int = 0
    off_bookings: int = 0
    valued: int = 0
    value_som: int = 0
    orders: int = 0
    handoffs: int = 0
    rated: int = 0
    average_rating: float | None = None
    returned: int = 0

    @property
    def off_pct(self) -> int:
        return round(100 * self.off_conversations / self.conversations) if self.conversations else 0

    @property
    def niche(self) -> str:
        return get_pack(self.business.niche).label

    def headline(self) -> str:
        n, off, booked, som = self.conversations, self.off_conversations, self.bookings, _som(self.value_som)
        if self.lang == "ky":
            text = f"{self.days} күндө ИИ {n} кардарга жооп берди, анын {off} — жумуш убактысынан тышкары, жана {booked} жазды"
            return text + (f"; прайс боюнча бул болжол менен {som} сом." if self.value_som else ".")
        text = f"За {self.days} дней ИИ ответил {_ru(n, 'клиенту', 'клиентам', 'клиентам')}, {off} из них — в нерабочее время, и записал {booked}"
        return text + (f"; по прайсу это около {som} сом." if self.value_som else ".")


def _som(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def _ru(n: int, one: str, few: str, many: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} {one}"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return f"{n} {few}"
    return f"{n} {many}"


def build(session: Session, business: Business, now_utc: datetime, days: int = 30, lang: str = "ru") -> Case:
    days = max(7, min(days, 365))
    until, since = now_utc, now_utc - timedelta(days=days)
    c = Case(business=business, lang="ky" if lang == "ky" else "ru", days=days, since=since, until=until)
    window = (Message.business_id == business.id, Message.role == "customer", Message.created_at >= since,
              Message.created_at < until, real_messages(business.id))
    c.conversations = session.exec(select(func.count(func.distinct(Message.conversation_id))).where(*window)).one() or 0
    c.off_conversations = session.exec(select(func.count(func.distinct(Message.conversation_id))).where(
        *window, Message.off_hours == True)).one() or 0  # noqa: E712
    prices = {s.name.casefold(): s.price_value for s in session.exec(select(Service).where(
        Service.business_id == business.id, Service.price_value != None)).all()}  # noqa: E711
    bookings = session.exec(select(Booking).where(
        Booking.business_id == business.id, Booking.source == "ai", Booking.channel != TEST_CHANNEL,
        Booking.created_at >= since, Booking.created_at < until)).all()
    c.bookings = len(bookings)
    c.off_bookings = sum(1 for b in bookings if b.created_off_hours)
    for b in bookings:
        name, extra = b.service or "", 0
        if b.upsell_status == "accepted" and " + " in name:
            name, extra = name.rsplit(" + ", 1)[0], b.upsell_price
        if name and name.casefold() in prices:
            c.valued += 1
            c.value_som += prices[name.casefold()] + extra
    orders = session.exec(select(Order).where(Order.business_id == business.id, Order.status != "cancelled", Order.channel != TEST_CHANNEL,
                                              Order.created_at >= since, Order.created_at < until)).all()
    c.orders = len(orders)
    c.value_som += sum(o.total for o in orders if o.total)
    c.handoffs = session.exec(select(func.count()).select_from(Lead).where(
        Lead.business_id == business.id, Lead.kind == "handoff", Lead.channel != TEST_CHANNEL,
        Lead.created_at >= since, Lead.created_at < until)).one() or 0
    fs = followup_stats(session, business.id, since)
    c.rated, c.average_rating, c.returned = fs.rated, fs.average, fs.returned
    return c
