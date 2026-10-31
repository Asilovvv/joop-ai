"""Questions the AI handed to people: candidates for the FAQ.

A handoff usually means the business's data had no answer. The panel shows the customer's own
words next to the FAQ form, so the owner answers once and the AI answers the next customer itself.
Complaints and personal requests are handoffs too; the owner simply skips them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlmodel import Session, select

from .lang import is_kyrgyz_message
from .models import Business, Faq, Lead, Message
from .timeutil import utc_to_local

WINDOW = timedelta(days=30)
SHOWN = 8
SCANNED = 60  # newest handoffs looked at; older ones wait until these are answered or age out
MIN_LETTERS = 4  # "2" (a rating) or "ок" is not a question

_LETTER = re.compile(r"[^\W\d_]")


@dataclass
class Gap:
    lead_id: int
    at: datetime  # local time of the business
    text: str  # the customer's message
    note: str  # what the AI asked the staff to do
    kyrgyz: bool


def _norm(text: str) -> str:
    return " ".join((text or "").split()).casefold().strip(" ?!.,")


def open_gaps(session: Session, business: Business, now_utc: datetime) -> list[Gap]:
    faqs = session.exec(select(Faq).where(Faq.business_id == business.id)).all()
    known = {_norm(f.question) for f in faqs} | {_norm(f.question_ky) for f in faqs if f.question_ky}
    answered = {f.source_lead_id for f in faqs if f.source_lead_id}
    leads = session.exec(
        select(Lead).where(
            Lead.business_id == business.id, Lead.kind == "handoff", Lead.created_at >= now_utc - WINDOW,
            Lead.conversation_id.is_not(None),  # type: ignore[union-attr]
        ).order_by(Lead.created_at.desc(), Lead.id.desc()).limit(SCANNED)
    ).all()
    gaps: list[Gap] = []
    seen: set[str] = set()
    for lead in leads:
        if lead.id in answered:
            continue
        msg = session.exec(
            select(Message).where(
                Message.conversation_id == lead.conversation_id, Message.role == "customer",
                Message.created_at <= lead.created_at,
            ).order_by(Message.created_at.desc(), Message.id.desc()).limit(1)
        ).first()
        text = (msg.text if msg else "").strip()
        key = _norm(text)
        if len(_LETTER.findall(text)) < MIN_LETTERS or key in known or key in seen:
            continue
        seen.add(key)
        gaps.append(Gap(lead.id, utc_to_local(lead.created_at, business.timezone), text[:300], lead.summary[:200],
                        is_kyrgyz_message(text)))
        if len(gaps) >= SHOWN:
            break
    return gaps
