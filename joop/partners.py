"""Referral program: partners bring businesses through /r/<code> and earn a share of every payment."""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlmodel import Session, select

from . import billing
from .models import Business, Partner, PartnerPayout, Payment, Referral

CODE_RE = re.compile(r"^[a-z0-9-]{3,40}$")


def new_partner(session: Session, name: str, phone: str = "", percent: int = 20, code_base: str = "") -> Partner:
    from .web.saas import slugify  # transliteration lives with sign-up

    base = (slugify(code_base or name)[:16].strip("-") or "partner")
    code = base
    while session.exec(select(Partner.id).where(Partner.code == code)).first() is not None:
        code = f"{base}-{secrets.randbelow(900) + 100}"
    partner = Partner(name=name.strip()[:120], phone=phone.strip()[:40], code=code, secret=secrets.token_urlsafe(18),
                      percent=max(0, min(percent, 50)))
    session.add(partner)
    return partner


def find_active(session: Session, code: str) -> Partner | None:
    code = (code or "").strip().lower()
    if not CODE_RE.match(code):
        return None
    return session.exec(select(Partner).where(Partner.code == code, Partner.active == True)).first()  # noqa: E712


def attach(session: Session, business_id: int, partner: Partner) -> None:
    if session.exec(select(Referral.id).where(Referral.business_id == business_id)).first() is None:
        session.add(Referral(business_id=business_id, partner_id=partner.id))


@dataclass
class PartnerStats:
    partner: Partner
    businesses: list[dict] = field(default_factory=list)
    paying: int = 0
    revenue_som: int = 0  # all paid payments of referred businesses
    revenue_30d_som: int = 0
    earned_som: int = 0
    paid_out_som: int = 0

    @property
    def owed_som(self) -> int:
        return max(0, self.earned_som - self.paid_out_som)


def stats(session: Session, partner: Partner, now: datetime) -> PartnerStats:
    st = PartnerStats(partner)
    ids = list(session.exec(select(Referral.business_id).where(Referral.partner_id == partner.id)).all())
    since = now - timedelta(days=30)
    for bid in ids:
        b = session.get(Business, bid)
        sub = billing.get_subscription(session, bid)
        state = billing.state(sub, now) if sub else None
        paid = session.exec(select(Payment).where(Payment.business_id == bid, Payment.status == "paid")).all()
        total = sum(p.amount_som for p in paid)
        st.revenue_som += total
        st.revenue_30d_som += sum(p.amount_som for p in paid if p.paid_at and p.paid_at >= since)
        if state and state.code == "active":
            st.paying += 1
        st.businesses.append({"name": b.name if b else "?", "created_at": b.created_at if b else None,
                              "state": state.label if state else "—", "paid_som": total})
    st.earned_som = st.revenue_som * partner.percent // 100
    st.paid_out_som = int(session.exec(
        select(func.coalesce(func.sum(PartnerPayout.amount_som), 0)).where(PartnerPayout.partner_id == partner.id)
    ).one() or 0)
    return st
