"""Answer the customers an outage left waiting, once the AI works again.

When a model call fails (the Anthropic balance ran out, the key is wrong, the API is down), the customer gets
ERROR_REPLY ("сейчас не получается ответить, администратор свяжется") and staff get a request of kind "error".
At night or at the weekend nobody may answer it, and the customer is lost even though the AI is back in a few
minutes. Every scheduler tick this module looks for such conversations and answers them with the normal reply
path (prices from the price list, bookings checked by code), starting with an apology for the delay.

A conversation is answered only while all of this holds:
- its last message is still ERROR_REPLY (no staff reply, no later answer, no newer customer message answered);
- the request of kind "error" is still open (staff did not mark it done) and is at most RECOVERY_WINDOW old;
- the channel can send later: Telegram, WhatsApp, Instagram (inside Meta's 24-hour window, since the window here
  is shorter); the site chat shows only replies to an open page, so its requests stay with staff;
- the AI is on for the business, the subscription is active and staff did not take the chat over.

While the model still fails, nothing is stored and the next try waits RETRY_EVERY, for every business.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from sqlmodel import Session, select

from .agent.engine import ERROR_REPLY, _model_reply
from .billing import access_ok
from .dispatch import deliver, notify_admins
from .models import Business, Conversation, Lead, Message

if TYPE_CHECKING:
    from .runtime import Runtime

log = logging.getLogger(__name__)

RECOVERY_WINDOW = timedelta(hours=12)
RETRY_EVERY = timedelta(minutes=5)
CHANNELS = ("telegram", "whatsapp", "instagram")
CHANNEL_NAMES = {"telegram": "Telegram", "whatsapp": "WhatsApp", "instagram": "Instagram"}
CLOSED_BY = "ИИ после сбоя"
PER_TICK = 20  # answers per business per tick; the rest wait for the next tick

_lock = threading.Lock()
_next_try: datetime | None = None


def waiting(session: Session, business: Business, now: datetime) -> list[tuple[Conversation, list[Lead]]]:
    """Conversations left with ERROR_REPLY as the last word, oldest first, with their open error requests."""
    leads = session.exec(select(Lead).where(
        Lead.business_id == business.id, Lead.kind == "error", Lead.status == "new",
        Lead.created_at >= now - RECOVERY_WINDOW, Lead.channel.in_(CHANNELS),
    ).order_by(Lead.created_at)).all()
    by_conv: dict[int, list[Lead]] = {}
    for lead in leads:
        if lead.conversation_id:
            by_conv.setdefault(lead.conversation_id, []).append(lead)
    found = []
    for conv_id, conv_leads in by_conv.items():
        conv = session.get(Conversation, conv_id)
        if conv is None or (conv.ai_paused_until and conv.ai_paused_until > now):
            continue
        last = session.exec(select(Message).where(Message.conversation_id == conv_id).order_by(Message.id.desc())).first()
        if last is None or last.role != "ai" or last.text != ERROR_REPLY:
            continue
        found.append((conv, conv_leads))
    return found


def _last_customer_text(session: Session, conv: Conversation) -> str:
    text = session.exec(select(Message.text).where(Message.conversation_id == conv.id, Message.role == "customer")
                        .order_by(Message.id.desc())).first()
    return (text or "").strip()


def answer_waiting(session: Session, rt: "Runtime", business: Business, now: datetime) -> int:
    """Answer waiting customers of one business. Returns how many got an answer."""
    global _next_try
    with _lock:
        if _next_try is not None and now < _next_try:
            return 0
    if not business.bot_enabled or not access_ok(session, business.id, now):
        return 0
    items = waiting(session, business, now)[:PER_TICK]
    answered: list[str] = []
    for conv, leads in items:
        text = _last_customer_text(session, conv)
        if not text:
            continue
        try:
            outcome = _model_reply(session, business, conv, conv.channel, text, now, rt.get_llm,
                                   rt.settings.public_base_url, rt.altegio, late=True)
        except Exception:
            session.rollback()
            with _lock:
                _next_try = now + RETRY_EVERY
            log.info("The AI still does not answer; waiting customers of %s are tried again later", business.slug)
            break
        if not outcome.reply:
            session.rollback()
            continue
        for lead in leads:
            lead.status, lead.closed_by = "done", CLOSED_BY
            session.add(lead)
        session.commit()  # stored before sending: a crash must not send the same answer twice
        deliver(rt, business, conv.channel, conv.chat_id, outcome)
        who = conv.customer_name or conv.display_name or "клиент без имени"
        answered.append(f"{who} ({CHANNEL_NAMES.get(conv.channel, conv.channel)})")
    if answered:
        with _lock:
            _next_try = None
        notify_admins(rt, business, [summary(answered)])
    return len(answered)


def summary(answered: list[str]) -> str:
    listed = "\n".join(f"— {x}" for x in answered[:10])
    more = f"\nи ещё {len(answered) - 10}" if len(answered) > 10 else ""
    return (f"ИИ снова отвечает. Клиенты, которые ждали ответа после сбоя, получили ответ ({len(answered)}):\n"
            f"{listed}{more}\nИх заявки в панели закрыты; переписка — в разделе «Диалоги».")


def reset() -> None:
    """For tests."""
    global _next_try
    with _lock:
        _next_try = None
