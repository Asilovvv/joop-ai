"""A missed call becomes a WhatsApp message: «мы пропустили ваш звонок — напишите здесь».

Many customers in Kyrgyzstan still phone, and a call nobody answers is a lost customer. Joop cannot take calls,
but it can turn the missed one into a chat the AI answers. The phone (an Android app such as MacroDroid on the
owner's phone, or a virtual PBX) posts each missed call to /webhooks/missed-call/<slug> with the business's
secret token, and here:

- within WhatsApp's 24-hour window (the caller wrote recently) the message is free-form text;
- outside it WhatsApp allows only an approved template, so the owner names one (Business.wa_missed_call_template,
  {{1}} = the business name); without one, or without WhatsApp, staff only get a note to call back;
- staff always get a note in the alerts chat, so the call is not lost either way;
- several rings from one number within DEDUPE count once; a blocked chat gets nothing; a switched-off AI or a
  lapsed subscription means a note to staff only, as for messages.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlmodel import Session, select

from .billing import access_ok
from .followups import SERVICE_WINDOW, deliver_to_chat
from .models import Business, Conversation, Message
from .phone import normalize_phone

if TYPE_CHECKING:
    from .runtime import Runtime

DEDUPE = timedelta(minutes=30)
PHONE_KEYS = ("phone", "caller", "caller_id", "call_number", "from", "number")
_recent: dict[tuple[int, str], float] = {}  # (business id, phone) -> time of the last handled call, per process
_lock = threading.Lock()

TEXT = ("Здравствуйте! Это {name}. Мы не успели ответить на ваш звонок — напишите здесь, чем помочь, ответим сразу.\n"
        "Саламатсызбы! Бул {name}. Чалууңузга жооп бере алган жокпуз — ушул жерге жазыңыз, дароо жооп беребиз.")  # KY: проверить носителю


@dataclass
class Handled:
    sent: str = ""  # "text" | "template" | "" (nothing reached the caller)
    notes: list[str] = field(default_factory=list)  # for the alerts chat
    skipped: str = ""  # "duplicate" | "blocked" | "no_phone"


def caller(params: dict[str, Any]) -> str | None:
    """The caller's number from whatever the phone or the PBX sent, in +E.164 form."""
    for key in PHONE_KEYS:
        value = params.get(key)
        if value:
            return normalize_phone(str(value))
    return None


def _first_call(business_id: int, phone: str) -> bool:
    now = time.monotonic()
    with _lock:
        for key in [k for k, t in _recent.items() if now - t > DEDUPE.total_seconds()]:
            del _recent[key]
        if (business_id, phone) in _recent:
            return False
        _recent[(business_id, phone)] = now
        return True


def reset() -> None:
    with _lock:
        _recent.clear()


def handle(session: Session, rt: "Runtime", business: Business, phone: str, now_utc: datetime) -> Handled:
    """Write to the caller where WhatsApp allows it and tell staff. The caller commits."""
    chat_id = phone.lstrip("+")  # WhatsApp chats are kept by the number without "+" (channels/meta.py)
    conv = session.exec(select(Conversation).where(Conversation.business_id == business.id, Conversation.channel == "whatsapp",
                                                   Conversation.chat_id == chat_id)).first()
    if conv is not None and conv.blocked_at:
        return Handled(skipped="blocked")
    if not _first_call(business.id, phone):
        return Handled(skipped="duplicate")
    who = f"{conv.customer_name or conv.display_name} ({phone})" if conv and (conv.customer_name or conv.display_name) else phone
    client = rt.whatsapp(business)
    if client is None or not business.bot_enabled or not access_ok(session, business.id, now_utc):
        return Handled(notes=[f"Пропущенный звонок: {who}. Перезвоните."])
    text = TEXT.format(name=business.name)
    in_window = bool(conv and conv.last_customer_at and now_utc - conv.last_customer_at < SERVICE_WINDOW)
    if in_window and deliver_to_chat(session, rt, business, conv, text, now_utc):
        return Handled(sent="text", notes=[f"Пропущенный звонок: {who}. Joop написал в WhatsApp, ИИ ответит, если клиент напишет."])
    template = business.wa_missed_call_template.strip()
    if template and client.send_template(chat_id, template, business.wa_template_lang, [business.name]):
        if conv is None:
            conv = Conversation(business_id=business.id, channel="whatsapp", chat_id=chat_id, customer_phone=phone,
                                created_at=now_utc, last_message_at=now_utc)
            session.add(conv)
            session.flush()
        session.add(Message(business_id=business.id, conversation_id=conv.id, role="ai", created_at=now_utc,
                            text=f"[Шаблон WhatsApp «{template}»: мы пропустили ваш звонок]"))
        conv.last_message_at = now_utc
        session.add(conv)
        return Handled(sent="template", notes=[f"Пропущенный звонок: {who}. Joop написал в WhatsApp, ИИ ответит, если клиент напишет."])
    why = "WhatsApp не принял сообщение" if template else "в WhatsApp можно написать первым только шаблоном — укажите его в «Каналах»"
    return Handled(notes=[f"Пропущенный звонок: {who}. Перезвоните ({why})."])


def process(rt: "Runtime", business_id: int, phone: str, now_utc: datetime | None = None) -> Handled:
    """The webhook's background task: handle the call, commit, then send the notes to the alerts chat."""
    from .db import new_session
    from .dispatch import notify_admins
    from .timeutil import utcnow

    with new_session() as session:
        business = session.get(Business, business_id)
        if business is None:
            return Handled(skipped="no_phone")
        result = handle(session, rt, business, phone, now_utc or utcnow())
        session.commit()
        session.refresh(business)
    if result.notes:
        notify_admins(rt, business, result.notes)
    return result
