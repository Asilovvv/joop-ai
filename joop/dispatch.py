"""Glue between channels and the engine: process a message, then deliver the reply and notifications."""

from __future__ import annotations

import logging
from datetime import datetime

from .agent.engine import Outcome, handle_incoming
from .channels.base import IncomingMessage
from .db import new_session
from .models import Business
from .runtime import Runtime

log = logging.getLogger(__name__)


def process_incoming(rt: Runtime, business_id: int, incoming: IncomingMessage, now_utc: datetime | None = None) -> Outcome:
    with new_session() as session:
        business = session.get(Business, business_id)
        if business is None:
            return Outcome(skipped="unknown_business")
        try:
            outcome = handle_incoming(session, business, incoming, rt.get_llm, now_utc, base_url=rt.settings.public_base_url,
                                       get_altegio=rt.altegio)
            session.commit()
        except Exception:
            session.rollback()
            log.exception("Failed to process a %s message for %s", incoming.channel, business.slug)
            return Outcome(skipped="error")
    deliver(rt, business, incoming.channel, incoming.chat_id, outcome)
    return outcome


def deliver(rt: Runtime, business: Business, channel: str, chat_id: str, outcome: Outcome) -> None:
    if outcome.reply:
        client = rt.channel_client(business, channel)
        if client is None:
            log.warning("No %s credentials for %s; reply not sent", channel, business.slug)
        elif not client.send_text(chat_id, outcome.reply):
            log.warning("Reply to %s via %s was not delivered", business.slug, channel)
    if outcome.admin_notes:
        notify_admins(rt, business, outcome.admin_notes)


def admin_chat_ids(business: Business) -> list[str]:
    return [x.strip() for x in (business.admin_chat_ids or "").split(",") if x.strip()]


def notify_admins(rt: Runtime, business: Business, notes: list[str]) -> int:
    """Send notes to every linked admin chat through the business's Telegram bot. Returns messages sent."""
    telegram = rt.telegram(business)
    chats = admin_chat_ids(business)
    if telegram is None or not chats:
        log.info("Admin notifications for %s are not set up; %d note(s) kept only in the panel", business.slug, len(notes))
        return 0
    sent = 0
    for note in notes:
        for chat_id in chats:
            if telegram.send_text(chat_id, note):
                sent += 1
    return sent
