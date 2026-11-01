"""Reminders to staff about requests nobody has answered.

The AI hands a customer to a person (a complaint, a question it cannot answer, a booking without a free time,
a voice message, a failed reply). If nobody answers, the customer is lost and the owner never learns why. During
working hours, a request still open after `Business.lead_nudge_minutes` (30 by default) is sent to the staff's
Telegram once, several in one message. The clock runs only in working hours: a request that came at night is
due that long after opening. A request counts as answered when staff mark it "Готово" in the panel or reply in
that chat (a reply typed in WhatsApp Business or Instagram reaches Joop as an echo). The morning summary also
counts what is still open.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import TYPE_CHECKING

from sqlmodel import Session, select

from .models import Business, Lead, Message
from .timeutil import is_off_hours, local_to_utc, parse_hhmm, utc_to_local

if TYPE_CHECKING:
    from .runtime import Runtime

KINDS = ("handoff", "request", "lead", "media", "error")
LOOK_BACK = timedelta(days=3)  # older requests are not nudged: the morning summary still counts them
LISTED = 5
CHANNELS = {"telegram": "Telegram", "whatsapp": "WhatsApp", "instagram": "Instagram", "web": "чат на сайте"}


def _answered(session: Session, lead: Lead) -> bool:
    if not lead.conversation_id:
        return False
    return session.exec(select(Message.id).where(
        Message.conversation_id == lead.conversation_id, Message.role == "staff", Message.created_at > lead.created_at,
    )).first() is not None


def overdue(session: Session, business: Business, now_utc: datetime) -> list[Lead]:
    """Open requests to remind staff about now: none outside working hours or when reminders are off."""
    wait = timedelta(minutes=business.lead_nudge_minutes)
    if business.lead_nudge_minutes <= 0:
        return []
    now_local = utc_to_local(now_utc, business.timezone)
    if is_off_hours(now_local, business.work_start, business.work_end, business.days_off):
        return []
    start = parse_hhmm(business.work_start) or time(9, 0)
    opened = local_to_utc(datetime.combine(now_local.date(), start), business.timezone)
    leads = session.exec(select(Lead).where(
        Lead.business_id == business.id, Lead.status == "new", Lead.nudged_at == None,  # noqa: E711
        Lead.kind.in_(KINDS), Lead.created_at <= now_utc - wait, Lead.created_at >= now_utc - LOOK_BACK,
    ).order_by(Lead.created_at)).all()
    return [x for x in leads if max(x.created_at, opened) <= now_utc - wait and not _answered(session, x)]


def _line(lead: Lead) -> str:
    who = ", ".join(x for x in (lead.customer_name, lead.customer_phone) if x) or "клиент"
    where = CHANNELS.get(lead.channel, lead.channel)
    summary = (lead.summary or "").strip()
    summary = summary if len(summary) <= 90 else summary[:89] + "…"
    return f"— {who}" + (f" ({where})" if where else "") + (f": {summary}" if summary else "")


def nudge_text(business: Business, leads: list[Lead]) -> str:
    n = len(leads)
    head = (f"Ждёт ответа больше {business.lead_nudge_minutes} мин: " +
            (f"{n} заявка" if n % 10 == 1 and n % 100 != 11 else f"{n} заявки" if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14
             else f"{n} заявок"))
    lines = [head] + [_line(x) for x in leads[:LISTED]]
    if n > LISTED:
        lines.append(f"…и ещё {n - LISTED}.")
    lines.append("Ответьте клиентам и отметьте «Готово» в разделе «Заявки».")
    return "\n".join(lines)


def send(session: Session, rt: "Runtime", business: Business, now_utc: datetime) -> int:
    """Remind staff once per request. Returns how many requests were in the reminder."""
    if not business.admin_chat_ids.strip():
        return 0  # nobody linked a Telegram chat: the panel still lists the requests
    leads = overdue(session, business, now_utc)
    if not leads:
        return 0
    from .dispatch import notify_admins

    if not notify_admins(rt, business, [nudge_text(business, leads)]):
        return 0  # try again next tick
    for lead in leads:
        lead.nudged_at = now_utc
        session.add(lead)
    return len(leads)


def open_count(session: Session, business: Business, now_utc: datetime) -> int:
    """Requests still open after an hour, for the morning summary."""
    return len(session.exec(select(Lead.id).where(
        Lead.business_id == business.id, Lead.status == "new", Lead.kind.in_(KINDS),
        Lead.created_at <= now_utc - timedelta(hours=1),
    )).all())
