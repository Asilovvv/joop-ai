"""The owner's test chat with the AI: the panel's «Тестовый чат» and the app's. Channel "console", so it is counted
nowhere (joop/stats.py), and the sign-up example answers in it, since there trying the example is the point.

One code for both: a message within the daily limit goes through the engine as a customer's would; «Новый диалог»
cancels the test's bookings, frees their times and starts a fresh chat."""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import func
from sqlmodel import Session, select

from . import waitlist
from .agent.engine import handle_incoming
from .channels.base import IncomingMessage
from .db import new_session
from .models import Booking, Business, Conversation, Message, Slot, WaitlistEntry
from .slots import release_slot, seats_needed
from .timeutil import utcnow

log = logging.getLogger(__name__)

CHAT_ID = "panel-test"
DAILY_LIMIT = 60  # test-chat messages per business per day: open sign-up must not burn the AI budget
MAX_TEXT = 1000


@dataclass
class Sent:
    """What to tell the owner, (text, "ok" | "error"), after one message; `answered` when the AI took it."""

    notes: list[tuple[str, str]] = field(default_factory=list)
    answered: bool = False


def conversation(s: Session, b: Business) -> Conversation | None:
    return s.exec(select(Conversation).where(Conversation.business_id == b.id, Conversation.channel == "console",
                                             Conversation.chat_id == CHAT_ID)).first()


def messages(s: Session, b: Business, last: int = 40) -> list[Message]:
    conv = conversation(s, b)
    return s.exec(select(Message).where(Message.conversation_id == conv.id).order_by(Message.id)).all()[-last:] if conv else []


def send(rt, business_id: int, text: str, base_url: str, limit: int | None = None) -> Sent:
    """One message from the owner as a customer. Times a test booking freed are offered to the waiting list after
    the session is closed (no network sends inside a transaction)."""
    limit = DAILY_LIMIT if limit is None else limit
    text = text.strip()[:MAX_TEXT]
    if not text:
        return Sent()
    with new_session() as s:
        b = s.get(Business, business_id)
        since = utcnow() - timedelta(days=1)
        used = s.exec(
            select(func.count()).select_from(Message).join(Conversation, Message.conversation_id == Conversation.id)
            .where(Message.business_id == b.id, Conversation.channel == "console", Message.role == "customer", Message.created_at >= since)
        ).one()
        if used >= limit:
            return Sent([(f"В тестовом чате не больше {limit} сообщений в сутки. Подключите Telegram и проверьте там.", "error")])
        incoming = IncomingMessage("console", CHAT_ID, "command" if text.startswith("/") else "text", text, "Тест",
                                   f"console:{CHAT_ID}:{secrets.token_hex(6)}")
        try:
            outcome = handle_incoming(s, b, incoming, rt.get_llm, base_url=base_url, get_altegio=rt.altegio)
            s.commit()
        except Exception:
            s.rollback()
            log.exception("Test chat failed for %s", b.slug)
            return Sent([("ИИ сейчас недоступен. Попробуйте через минуту.", "error")])
    done = Sent(answered=not outcome.skipped)
    if outcome.skipped == "subscription":
        done.notes.append(("Пробный период закончился — оплатите подписку, чтобы ИИ отвечал.", "error"))
    elif outcome.skipped == "bot_disabled":
        done.notes.append(("ИИ выключен в настройках.", "error"))
    for note in outcome.admin_notes:
        done.notes.append(("Уведомление администратору: " + note.splitlines()[0], "ok"))
    if outcome.freed_slot_ids:  # a test booking cancelled or moved: its real time goes to the waiting list, as «Новый диалог» does
        from .dispatch import offer_freed

        offer_freed(rt, b, outcome.freed_slot_ids)
    if outcome.booking_id:
        done.notes.append(("Это тестовая запись: она видна в «Записях» и занимает время. Напоминаний по ней не будет"
                           + (", в Altegio она не отправлена" if b.altegio_location_id else "")
                           + ". Кнопка «Новый диалог» её отменит.", "ok"))
    return done


def reset(s: Session, rt, b: Business) -> int:
    """«Новый диалог»: the test's bookings cancelled, a fresh chat; the old dialogue stays in the panel. Commits."""
    conv = conversation(s, b)
    cancelled = 0
    if conv:
        cancelled = undo_test_bookings(s, rt, b, conv)
        conv.chat_id = f"{CHAT_ID}-{secrets.token_hex(4)}"  # keep the dialogue in the panel, start a fresh chat
        s.add(conv)
        s.commit()
    return cancelled


def undo_test_bookings(s: Session, rt, b: Business, conv: Conversation) -> int:
    """A new test dialogue leaves nothing behind on the schedule: the test's bookings are cancelled, their times
    freed (and offered to customers on the waiting list, as after any cancellation), its waiting-list entries closed."""
    now = utcnow()
    count = 0
    for booking in s.exec(select(Booking).where(Booking.conversation_id == conv.id, Booking.status == "booked")).all():
        booking.status = "cancelled"
        s.add(booking)
        slot = s.get(Slot, booking.slot_id) if booking.slot_id else None
        release_slot(s, booking.slot_id, seats_needed(slot, booking.party_size) if slot else 1)
        s.flush()
        if slot is not None:
            s.refresh(slot)
            waitlist.offer_freed_slot(s, rt, b, slot, now)
        count += 1
    for entry in s.exec(select(WaitlistEntry).where(WaitlistEntry.conversation_id == conv.id,
                                                    WaitlistEntry.status.in_(["waiting", "notified"]))).all():
        entry.status = "cancelled"
        s.add(entry)
    return count
