"""The two pilot numbers that say whether a business stays: dialogues the owner checked in week one, and retention.

The strategy (docs: «Joop AI — стратегия с нуля», "Метрики") counts activation and money, not sign-ups, and names
two early signs of churn: an owner who never reads the first real dialogues leaves without saying why, and the
only number competitors die on is how many pilots still pay after 90 days. Both are counted here from the
database for the founder's «Пилот» page:

- week one: real conversations (not the panel's test chat, not the site demo) that started within seven days of
  the business's first real customer message, and how many of them a person opened in the panel in those days
  (`Conversation.reviewed_at`, set on the first look);
- retention: of the businesses signed up at least 30 (90) days ago, how many are kept — paying, on the free plan,
  or still in a trial — now. Businesses without a subscription row (created by hand) are not judged.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlmodel import Session, select

from . import billing
from .models import Business, Conversation, Subscription
from .pilot import DEMO_PREFIX
from .stats import real_conversation
from .trust import REAL_CHANNELS, first_live_at

WEEK = timedelta(days=7)
KEPT = ("active", "free", "trial")


@dataclass
class Row:
    business: str
    signed_up: datetime
    live_at: datetime | None  # the first real customer message
    week_one_conversations: int = 0
    week_one_reviewed: int = 0
    status: str = ""
    kept: bool = False

    def age_days(self, now: datetime) -> int:
        return (now - self.signed_up).days


@dataclass
class Summary:
    kept_30: tuple[int, int] = (0, 0)  # kept, judged
    kept_90: tuple[int, int] = (0, 0)
    week_one_conversations: int = 0
    week_one_reviewed: int = 0


def _week_one(session: Session, business: Business, live_at: datetime) -> tuple[int, int]:
    end = live_at + WEEK
    convs = session.exec(select(Conversation).where(
        Conversation.business_id == business.id, Conversation.channel.in_(REAL_CHANNELS), real_conversation(),
        Conversation.created_at >= live_at - timedelta(minutes=1), Conversation.created_at < end,
    )).all()
    reviewed = sum(1 for c in convs if c.reviewed_at is not None and c.reviewed_at < end)
    return len(convs), reviewed


def report(session: Session, now: datetime) -> tuple[list[Row], Summary]:
    """One row per business with a subscription (oldest first), and the totals the strategy asks for."""
    subs = {s.business_id: s for s in session.exec(select(Subscription)).all()}
    businesses = session.exec(select(Business).where(Business.slug.not_like(f"{DEMO_PREFIX}%"), Business.id.in_(list(subs) or [0]))
                              .order_by(Business.created_at)).all()
    rows: list[Row] = []
    summary = Summary()
    for b in businesses:
        st = billing.state(subs[b.id], now)
        row = Row(business=b.name, signed_up=b.created_at, live_at=first_live_at(session, b), status=st.label, kept=st.code in KEPT)
        if row.live_at is not None:
            row.week_one_conversations, row.week_one_reviewed = _week_one(session, b, row.live_at)
        rows.append(row)
    summary.week_one_conversations = sum(r.week_one_conversations for r in rows)
    summary.week_one_reviewed = sum(r.week_one_reviewed for r in rows)
    for days, name in ((30, "kept_30"), (90, "kept_90")):
        judged = [r for r in rows if r.age_days(now) >= days]
        setattr(summary, name, (sum(r.kept for r in judged), len(judged)))
    return rows, summary

