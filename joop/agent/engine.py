"""Reply engine: one incoming message in, one reply plus side effects out.

Side effects stay in the database session passed in (messages, bookings, leads). Sending the reply
and the admin notifications happens in ``dispatch.py``, after the caller commits.
"""

from __future__ import annotations

import hmac
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable

from sqlmodel import Session, select

from ..channels.base import IncomingMessage
from ..models import Booking, Business, Conversation, Faq, Lead, Message, Service, Slot, Staff
from ..phone import normalize_phone
from ..slots import claim_slot, free_slots
from ..timeutil import fmt_slot, is_off_hours, utc_to_local, utcnow
from .llm import AgentReply, LLMClient
from .prompt import CHANNEL_LABELS, build_history, build_system_prompt

log = logging.getLogger(__name__)

HISTORY_LIMIT = 20
HISTORY_WINDOW = timedelta(hours=72)
STAFF_TAKEOVER_PAUSE = timedelta(hours=12)

TEXT_ONLY_REPLY = (
    "Я пока понимаю только текстовые сообщения. Напишите, пожалуйста, текстом — "
    "и я сразу помогу с записью."
)
ERROR_REPLY = (
    "Извините, сейчас не получается ответить. Я передал ваше сообщение администратору, с вами свяжутся."
)
ASK_CONTACTS_REPLY = (
    "Чтобы записать вас, напишите, пожалуйста, имя и номер телефона, например: Айбек, 0555 123 456."
)
DEFAULT_GREETING = (
    "Здравствуйте! Это администратор «{name}». Напишите, что беспокоит или на какую услугу хотите "
    "записаться, — подберу удобное время."
)


@dataclass
class Outcome:
    reply: str | None = None
    admin_notes: list[str] = field(default_factory=list)
    booking_id: int | None = None
    lead_id: int | None = None
    skipped: str = ""  # why nothing was sent, for logs and tests


def handle_incoming(
    session: Session,
    business: Business,
    incoming: IncomingMessage,
    get_llm: Callable[[], LLMClient],
    now_utc: datetime | None = None,
) -> Outcome:
    now = now_utc or utcnow()
    now_local = utc_to_local(now, business.timezone)
    off = is_off_hours(now_local, business.work_start, business.work_end, business.days_off)

    if incoming.external_id and _already_seen(session, business.id, incoming.external_id):
        return Outcome(skipped="duplicate")

    conv = _get_or_create_conversation(session, business, incoming, now)

    if incoming.kind == "echo":
        return _handle_echo(session, business, conv, incoming, now, off)

    text = (incoming.text or "").strip()
    stored = text
    if incoming.kind == "media":
        stored = f"[{incoming.media_label or 'вложение'}]" + (f" {text}" if text else "")
    _add_message(session, business, conv, "customer", stored, now, off, incoming.external_id)
    conv.last_customer_at = now
    if incoming.user_name and not conv.display_name:
        conv.display_name = incoming.user_name[:120]

    if incoming.kind == "command":
        handled = _handle_command(session, business, conv, incoming, text, now, off)
        if handled is not None:
            return handled

    if not business.bot_enabled:
        return Outcome(skipped="bot_disabled")
    if conv.ai_paused_until and conv.ai_paused_until > now:
        return Outcome(skipped="paused")

    if incoming.kind == "media":
        label = incoming.media_label or "вложение"
        lead = _add_lead(session, business, conv, "media", f"Клиент прислал: {label}. Нужно ответить вручную.", now, off)
        _add_message(session, business, conv, "ai", TEXT_ONLY_REPLY, now, off)
        return Outcome(reply=TEXT_ONLY_REPLY, admin_notes=[_lead_note(business, conv, lead, off)], lead_id=lead.id)

    if not text:
        return Outcome(skipped="empty")

    services = session.exec(select(Service).where(Service.business_id == business.id).order_by(Service.sort, Service.id)).all()
    staff = session.exec(select(Staff).where(Staff.business_id == business.id).order_by(Staff.id)).all()
    faqs = session.exec(select(Faq).where(Faq.business_id == business.id).order_by(Faq.id)).all()
    slots = free_slots(session, business.id, now_local)
    system = build_system_prompt(
        business=business,
        services=services,
        staff=staff,
        faqs=faqs,
        slots=slots,
        now_local=now_local,
        conversation=conv,
        channel=incoming.channel,
    )
    history = _history(session, conv, now)

    try:
        result: AgentReply = get_llm().respond(system, history)
    except Exception:
        log.exception("Model call failed for business %s", business.slug)
        lead = _add_lead(session, business, conv, "error", f"ИИ не смог ответить на сообщение: «{text[:300]}»", now, off)
        _add_message(session, business, conv, "ai", ERROR_REPLY, now, off)
        return Outcome(reply=ERROR_REPLY, admin_notes=[_lead_note(business, conv, lead, off)], lead_id=lead.id)

    outcome = Outcome(reply=result.reply)
    if result.booking:
        reply, booking = _try_booking(session, business, conv, result.booking, result.reply, now, now_local, off, incoming.channel)
        outcome.reply = reply
        if booking is not None:
            outcome.booking_id = booking.id
            outcome.admin_notes.append(_booking_note(business, booking, off))
    if result.handoff:
        lead = _add_lead(session, business, conv, "handoff", result.handoff, now, off)
        outcome.lead_id = lead.id
        outcome.admin_notes.append(_lead_note(business, conv, lead, off))

    if outcome.reply:
        _add_message(session, business, conv, "ai", outcome.reply, now, off)
    return outcome


# --- helpers -----------------------------------------------------------------------------------


def _already_seen(session: Session, business_id: int, external_id: str) -> bool:
    found = session.exec(
        select(Message.id).where(Message.business_id == business_id, Message.external_id == external_id)
    ).first()
    return found is not None


def _get_or_create_conversation(session: Session, business: Business, incoming: IncomingMessage, now: datetime) -> Conversation:
    conv = session.exec(
        select(Conversation).where(
            Conversation.business_id == business.id,
            Conversation.channel == incoming.channel,
            Conversation.chat_id == incoming.chat_id,
        )
    ).first()
    if conv is None:
        conv = Conversation(
            business_id=business.id,
            channel=incoming.channel,
            chat_id=incoming.chat_id,
            display_name=(incoming.user_name or "")[:120],
            created_at=now,
            last_message_at=now,
        )
        session.add(conv)
        session.flush()
    return conv


def _add_message(
    session: Session,
    business: Business,
    conv: Conversation,
    role: str,
    text: str,
    now: datetime,
    off: bool,
    external_id: str = "",
) -> Message:
    msg = Message(
        business_id=business.id,
        conversation_id=conv.id,
        role=role,
        text=text,
        created_at=now,
        off_hours=off,
        external_id=external_id or "",
    )
    session.add(msg)
    conv.last_message_at = now
    session.add(conv)
    return msg


def _add_lead(session: Session, business: Business, conv: Conversation, kind: str, summary: str, now: datetime, off: bool) -> Lead:
    lead = Lead(
        business_id=business.id,
        conversation_id=conv.id,
        kind=kind,
        summary=summary[:1000],
        customer_name=conv.customer_name or conv.display_name,
        customer_phone=conv.customer_phone,
        channel=conv.channel,
        chat_id=conv.chat_id,
        created_at=now,
        off_hours=off,
    )
    session.add(lead)
    session.flush()
    return lead


def _history(session: Session, conv: Conversation, now: datetime) -> list[dict]:
    rows = session.exec(
        select(Message)
        .where(Message.conversation_id == conv.id, Message.created_at >= now - HISTORY_WINDOW)
        .order_by(Message.id.desc())
        .limit(HISTORY_LIMIT)
    ).all()
    return build_history(list(reversed(rows)))


def _norm(text: str) -> str:
    return " ".join((text or "").split()).casefold()


def _is_own_text(echo: str, sent: list[str]) -> bool:
    """Does an echo match one of our replies? Channels may cut long texts, so a long echo may be a prefix."""
    e = _norm(echo).rstrip("…").strip()
    if not e:
        return False
    for t in sent:
        t = _norm(t)
        if e == t or (len(e) >= 20 and t.startswith(e)):
            return True
    return False


def _handle_echo(
    session: Session, business: Business, conv: Conversation, incoming: IncomingMessage, now: datetime, off: bool
) -> Outcome:
    """A message the business sent from its own app. Ours -> ignore; typed by staff -> pause the AI."""
    text = (incoming.text or "").strip()
    recent_ai = session.exec(
        select(Message.text)
        .where(Message.conversation_id == conv.id, Message.role == "ai")
        .order_by(Message.id.desc())
        .limit(5)
    ).all()
    if _is_own_text(text, list(recent_ai)):
        return Outcome(skipped="own_echo")
    _add_message(session, business, conv, "staff", text or "[сообщение администратора]", now, off, incoming.external_id)
    conv.ai_paused_until = now + STAFF_TAKEOVER_PAUSE
    session.add(conv)
    return Outcome(skipped="staff_reply")


def _handle_command(
    session: Session, business: Business, conv: Conversation, incoming: IncomingMessage, text: str, now: datetime, off: bool
) -> Outcome | None:
    command, _, argument = text.partition(" ")
    command = command.split("@", 1)[0].lower()
    if command == "/start":
        reply = (business.greeting or DEFAULT_GREETING).format(name=business.name)
        _add_message(session, business, conv, "ai", reply, now, off)
        return Outcome(reply=reply)
    if command == "/admin":
        code = argument.strip()
        if incoming.channel == "telegram" and code and business.admin_link_code and hmac.compare_digest(code, business.admin_link_code):
            ids = [x for x in business.admin_chat_ids.split(",") if x.strip()]
            if incoming.chat_id not in ids:
                ids.append(incoming.chat_id)
            business.admin_chat_ids = ",".join(ids)
            session.add(business)
            return Outcome(reply="Готово. Сюда будут приходить уведомления о новых записях и заявках.")
        return Outcome(reply="Код не подошёл. Код есть в панели управления: «Настройки» → «Уведомления в Telegram».")
    return None  # other slash-texts are answered like normal messages


def _alternatives(session: Session, business: Business, now_local: datetime, staff_id: int | None) -> list[str]:
    rows = free_slots(session, business.id, now_local, staff_id=staff_id, limit=3) if staff_id else []
    if not rows:
        rows = free_slots(session, business.id, now_local, limit=3)
    return [f"{fmt_slot(slot.start)} ({member.name})" for slot, member in rows]


def _try_booking(
    session: Session,
    business: Business,
    conv: Conversation,
    data: dict,
    reply: str,
    now: datetime,
    now_local: datetime,
    off: bool,
    channel: str,
) -> tuple[str, Booking | None]:
    name = (data.get("name") or "").strip()[:120]
    phone = normalize_phone(data.get("phone"))
    if not name or not phone:
        return ASK_CONTACTS_REPLY, None

    slot_id = data.get("slot_id")
    slot = session.get(Slot, slot_id) if slot_id else None
    member = session.get(Staff, slot.staff_id) if slot else None
    usable = (
        slot is not None
        and slot.business_id == business.id
        and slot.status == "free"
        and slot.start > now_local
        and member is not None
        and member.active
    )
    if not usable or not claim_slot(session, slot.id):
        options = _alternatives(session, business, now_local, slot.staff_id if slot else None)
        if options:
            text = "Извините, это время уже занято. Свободно: " + "; ".join(options) + ". Какое удобно?"
        else:
            text = "Извините, это время уже занято. Оставьте удобное время — администратор перезвонит и подберёт запись."
        return text, None

    booking = Booking(
        business_id=business.id,
        slot_id=slot.id,
        conversation_id=conv.id,
        staff_id=member.id,
        staff_name=member.name,
        start=slot.start,
        service=(data.get("service") or "").strip()[:200],
        customer_name=name,
        customer_phone=phone,
        channel=channel,
        chat_id=conv.chat_id,
        created_at=now,
        created_off_hours=off,
    )
    session.add(booking)
    conv.customer_name = name
    conv.customer_phone = phone
    session.add(conv)
    session.flush()
    return reply, booking


def _booking_note(business: Business, booking: Booking, off: bool) -> str:
    when = " (в нерабочее время)" if off else ""
    lines = [
        f"Новая запись через ИИ{when}",
        f"{booking.customer_name}, {booking.customer_phone}",
        f"{booking.service or 'приём'} — {fmt_slot(booking.start)}, {booking.staff_name}",
        f"Канал: {CHANNEL_LABELS.get(booking.channel, booking.channel)}",
    ]
    return "\n".join(lines)


def _lead_note(business: Business, conv: Conversation, lead: Lead, off: bool) -> str:
    when = " (в нерабочее время)" if off else ""
    who = ", ".join(x for x in [lead.customer_name, lead.customer_phone] if x) or "имя не указано"
    lines = [
        f"Заявка администратору{when}",
        lead.summary,
        f"Клиент: {who}",
        f"Канал: {CHANNEL_LABELS.get(conv.channel, conv.channel)}",
    ]
    return "\n".join(lines)
