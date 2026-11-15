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

Each handled call is kept (MissedCall) so the owner's weekly report can say what the calls turned into: written
to, answered, booked or ordered (results()).

The address is protected by a secret, but a leaked secret must not turn the business's WhatsApp into a mailer:
- at most PER_HOUR / PER_DAY callers are written to; above that staff get one note to change the code;
- a number Joop has never talked to is written to first only within the business's own country code;
- a caller Joop already wrote to in the last day and who has not answered is not written to again.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlmodel import Session, select

from .billing import access_ok
from .followups import SERVICE_WINDOW, deliver_to_chat
from .models import Booking, Business, Conversation, Message, MissedCall, Order
from .phone import normalize_phone
from .stats import test_conversations

if TYPE_CHECKING:
    from .runtime import Runtime

DEDUPE = timedelta(minutes=30)
AGAIN = timedelta(hours=24)  # a caller written to this recently and silent since is not written to again
PER_HOUR, PER_DAY = 20, 100  # callers written to: far above a small business's day, far below a mailer's
CODES = ("+996", "+998", "+992", "+993", "+994", "+995", "+374", "+375", "+380", "+7")  # the business's own is found among these
AFTER = timedelta(days=7)  # a reply, booking or order this soon after the call counts as its result
PHONE_KEYS = ("phone", "caller", "caller_id", "call_number", "from", "number")
_recent: dict[tuple[int, str], datetime] = {}  # (business id, phone) -> time of the last handled call, per process
_lock = threading.Lock()

TEXT = ("Здравствуйте! Это {name}. Мы не успели ответить на ваш звонок — напишите здесь, чем помочь, ответим сразу.\n"
        "Саламатсызбы! Бул {name}. Чалууңузга жооп бере алган жокпуз — ушул жерге жазыңыз, дароо жооп беребиз.")  # KY: проверить носителю


@dataclass
class Handled:
    sent: str = ""  # "text" | "template" | "" (nothing reached the caller)
    notes: list[str] = field(default_factory=list)  # for the alerts chat
    skipped: str = ""  # "duplicate" | "blocked" | "no_phone"


def raw_caller(params: dict[str, Any]) -> str:
    """What the phone or the PBX sent as the number. An unencoded "+" in a form body arrives as a space."""
    for key in PHONE_KEYS:
        value = str(params.get(key) or "")
        if value.strip():
            return "+" + value.strip() if value[:1] == " " and value.strip()[:1].isdigit() else value.strip()
    return ""


def caller(params: dict[str, Any]) -> str | None:
    """The caller's number from whatever the phone or the PBX sent, in +E.164 form."""
    raw = raw_caller(params)
    return normalize_phone(raw) if raw else None


def unknown_note(raw: str) -> str:
    """For a call whose number could not be read: hidden, «Unknown», or a format we do not know."""
    shown = "".join(c for c in raw if c.isalnum() or c in "+ -()")[:30].strip()
    return f"Пропущенный звонок: номер не определился{f' ({shown})' if shown else ''}. Проверьте журнал звонков на телефоне."


def _home_code(business: Business) -> str:
    own = normalize_phone(business.phone or "") or "+996"
    return next((c for c in CODES if own.startswith(c)), "+996")


def _first_call(business_id: int, phone: str, now_utc: datetime) -> bool:
    """A burst of rings handled in parallel, before the first one is committed: only one goes on."""
    with _lock:
        for key in [k for k, t in _recent.items() if abs(now_utc - t) > DEDUPE]:
            del _recent[key]
        if (business_id, phone) in _recent:
            return False
        _recent[(business_id, phone)] = now_utc
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
    recent = session.exec(select(MissedCall.id).where(MissedCall.business_id == business.id, MissedCall.phone == phone,
                                                      MissedCall.created_at > now_utc - DEDUPE)).first()
    if recent is not None or not _first_call(business.id, phone, now_utc):  # the table survives a restart, the lock a burst
        return Handled(skipped="duplicate")
    result = _limited(session, business, phone, conv, now_utc) or _handle(session, rt, business, phone, chat_id, conv, now_utc)
    conv = conv or session.exec(select(Conversation).where(Conversation.business_id == business.id, Conversation.channel == "whatsapp",
                                                           Conversation.chat_id == chat_id)).first()
    session.add(MissedCall(business_id=business.id, phone=phone, sent=result.sent, created_at=now_utc,
                           conversation_id=conv.id if conv and result.sent else None))
    return result


def _limited(session: Session, business: Business, phone: str, conv: Conversation | None, now_utc: datetime) -> Handled | None:
    """Staff only, nothing to the caller: a flood (a leaked code), a stranger abroad, or a caller already written to."""
    who = f"{conv.customer_name or conv.display_name} ({phone})" if conv and (conv.customer_name or conv.display_name) else phone

    def written_since(start: datetime) -> int:
        return len(session.exec(select(MissedCall.id).where(MissedCall.business_id == business.id, MissedCall.sent != "",
                                                            MissedCall.created_at > start)).all())

    for limit, period, words in ((PER_HOUR, timedelta(hours=1), "за час"), (PER_DAY, timedelta(days=1), "за сутки")):
        count = written_since(now_utc - period)
        if count >= limit:
            flood = (f"Пропущенных звонков {words} больше {limit}: Joop пока не пишет звонившим, чтобы WhatsApp не принял это "
                     "за рассылку. Если это не ваши звонки, смените код в «Каналах» → «Пропущенные звонки».")
            first = not session.exec(select(MissedCall.id).where(MissedCall.business_id == business.id, MissedCall.sent == "",
                                                                 MissedCall.created_at > now_utc - period,
                                                                 MissedCall.created_at > _last_sent(session, business.id))).first()
            return Handled(notes=([flood] if first else []) + [f"Пропущенный звонок: {who}. Перезвоните."])
    if conv is None and not phone.startswith(_home_code(business)):
        return Handled(notes=[f"Пропущенный звонок: {who} — номер другой страны, Joop не пишет первым незнакомым "
                              "иностранным номерам. Перезвоните."])
    before = session.exec(select(MissedCall).where(MissedCall.business_id == business.id, MissedCall.phone == phone,
                                                   MissedCall.sent != "", MissedCall.created_at > now_utc - AGAIN)
                          .order_by(MissedCall.created_at.desc())).first()
    if before is not None and before.conversation_id and not session.exec(select(Message.id).where(
            Message.conversation_id == before.conversation_id, Message.role == "customer",
            Message.created_at > before.created_at)).first():
        return Handled(notes=[f"Пропущенный звонок: {who}, снова. Joop уже написал ему в WhatsApp, ответа пока нет — перезвоните."])
    return None


def _last_sent(session: Session, business_id: int) -> datetime:
    """When Joop last wrote to a caller: the flood note goes once per flood, not once per call."""
    last = session.exec(select(MissedCall.created_at).where(MissedCall.business_id == business_id, MissedCall.sent != "")
                        .order_by(MissedCall.created_at.desc())).first()
    return last or datetime.min


def _handle(session: Session, rt: "Runtime", business: Business, phone: str, chat_id: str, conv: Conversation | None,
            now_utc: datetime) -> Handled:
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


def results(session: Session, business: Business, since: datetime) -> tuple[int, int, int, int]:
    """(missed calls, of them written to, of those the caller wrote back, then booked or ordered) for calls since.

    A reply, booking or order counts for the latest call before it in the same chat, within AFTER of that call, so
    a customer who called twice and booked once is one booking. Test chats and the business's own number (the owner
    trying it) are left out."""
    tests = set(session.exec(test_conversations(business.id)).all())
    own = normalize_phone(business.phone or "")
    calls = [c for c in session.exec(select(MissedCall).where(MissedCall.business_id == business.id, MissedCall.created_at >= since)
                                     .order_by(MissedCall.created_at)).all()
             if c.conversation_id not in tests and c.phone != own]
    written = [c for c in calls if c.sent and c.conversation_id]
    replied = booked = 0
    for i, call in enumerate(written):
        later = [c.created_at for c in written[i + 1:] if c.conversation_id == call.conversation_id]
        until = min([call.created_at + AFTER] + later)
        wrote = session.exec(select(Message.id).where(Message.conversation_id == call.conversation_id, Message.role == "customer",
                                                      Message.created_at > call.created_at, Message.created_at <= until)).first()
        if wrote is None:
            continue
        replied += 1
        visit = session.exec(select(Booking.id).where(Booking.conversation_id == call.conversation_id, Booking.status != "cancelled",
                                                      Booking.created_at > call.created_at, Booking.created_at <= until)).first()
        order = None if visit is not None else session.exec(select(Order.id).where(
            Order.conversation_id == call.conversation_id, Order.status != "cancelled",
            Order.created_at > call.created_at, Order.created_at <= until)).first()
        if visit is not None or order is not None:
            booked += 1
    return len(calls), len(written), replied, booked
