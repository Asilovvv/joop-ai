"""The founder's one line a week: paying businesses and what the AI did, in Telegram every Monday morning.

The strategy (docs: «Joop AI — стратегия с нуля», "Метрики") ends with "одна цифра в неделю в журнал плана:
платящих N, записей через ИИ M". Nobody keeps a journal by hand, so the scheduler writes the line itself: on
Monday after 09:00 Bishkek it counts the week that ended on Sunday, stores the line (`FounderDigest`, the
journal) and sends it to the founder's Telegram when the founder bot is set up. One line per week, whatever
restarts happen in between: the stored row is the lock. The site's demo businesses and the owners' test chats
are left out, as everywhere.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from sqlalchemy import func
from sqlmodel import Session, select

from . import billing, health, retention
from .models import Booking, Business, FounderDigest, Lead, Message, Subscription
from .pilot import DEMO_PREFIX
from .stats import TEST_CHANNEL, real_messages
from .timeutil import DEFAULT_TZ, local_to_utc, utc_to_local

log = logging.getLogger(__name__)

SEND_HOUR = 9  # Monday, Bishkek time
TZ = DEFAULT_TZ


def _som(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def week_of(now_utc: datetime) -> date:
    """The Monday that starts the week just ended (the line is written on the next Monday)."""
    today = utc_to_local(now_utc, TZ).date()
    return today - timedelta(days=today.weekday() + 7)


def text(session: Session, now_utc: datetime, price_som: int) -> str:
    start = week_of(now_utc)
    since = local_to_utc(datetime.combine(start, datetime.min.time()), TZ)
    until = since + timedelta(days=7)
    real = list(session.exec(select(Business.id).where(Business.slug.not_like(f"{DEMO_PREFIX}%"))).all()) or [0]
    paying = free = trial = 0
    for sub in session.exec(select(Subscription).where(Subscription.business_id.in_(real))).all():
        code = billing.state(sub, now_utc).code
        paying += code == "active"
        free += code == "free"
        trial += code == "trial"
    mrr = billing.mrr(session, now_utc, price_som)
    bookings = session.exec(select(func.count()).select_from(Booking).where(
        Booking.business_id.in_(real), Booking.source == "ai", Booking.channel != TEST_CHANNEL,
        Booking.created_at >= since, Booking.created_at < until)).one()
    conversations = session.exec(select(func.count(func.distinct(Message.conversation_id))).where(
        Message.business_id.in_(real), Message.role == "customer", real_messages(),
        Message.created_at >= since, Message.created_at < until)).one()

    def leads(kind: str) -> int:
        return session.exec(select(func.count()).select_from(Lead).where(
            Lead.business_id.in_(real), Lead.kind == kind, Lead.channel != TEST_CHANNEL,
            Lead.created_at >= since, Lead.created_at < until)).one()

    signups = session.exec(select(func.count()).select_from(Subscription).where(
        Subscription.business_id.in_(real), Subscription.created_at >= since, Subscription.created_at < until)).one()
    cancels = session.exec(select(func.count()).select_from(Subscription).where(
        Subscription.business_id.in_(real), Subscription.cancelled_at >= since, Subscription.cancelled_at < until)).one()
    kept, judged = retention.report(session, now_utc)[1].kept_90
    kept_line = f"{kept} из {judged}" if judged else "— (некого судить)"
    end = start + timedelta(days=6)
    return (f"Joop AI, неделя {start:%d.%m}–{end:%d.%m}. Платящих {paying} ({_som(mrr)} сом/мес), бесплатных {free}, в пробном {trial}. "
            f"Записей через ИИ {bookings}, диалогов {conversations}, передано людям {leads('handoff')}, сбоев {leads('error')}. "
            f"Новых регистраций {signups}, отмен {cancels}. Удержание через 90 дней: {kept_line}.")


def due(session: Session, now_utc: datetime) -> bool:
    local = utc_to_local(now_utc, TZ)
    if local.weekday() != 0 or local.hour < SEND_HOUR:
        return False
    return session.exec(select(FounderDigest.id).where(FounderDigest.week_start == week_of(now_utc))).first() is None


def maybe_send(session: Session, rt, now_utc: datetime) -> FounderDigest | None:
    """On Monday morning: write the week's line once and send it to the founder when the bot is set up."""
    if not due(session, now_utc):
        return None
    row = FounderDigest(week_start=week_of(now_utc), text=text(session, now_utc, rt.settings.price_som))
    session.add(row)
    session.commit()  # the lock first: a failed send is not resent, the line is in the console
    try:
        row.sent = bool(health.tell_founder(rt, row.text))
    except Exception:
        log.exception("Founder digest was not sent")
    session.add(row)
    session.commit()
    return row


def recent(session: Session, limit: int = 12) -> list[FounderDigest]:
    return list(session.exec(select(FounderDigest).order_by(FounderDigest.week_start.desc()).limit(limit)).all())

