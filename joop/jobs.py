"""Order status for items left for work (dry cleaning, repairs, tailoring, car service).

The AI tells a customer the status only for a job it can tie to them: the WhatsApp number they write
from, or the receipt number together with the phone given at drop-off. When staff mark a job ready, the
customer gets a message in the chat that asked about it (or in their WhatsApp chat).
"""

from __future__ import annotations

import re
import secrets
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from sqlmodel import Session, select

from .followups import deliver_to_chat
from .lang import is_kyrgyz_message
from .memberships import phone_key
from .models import Business, Conversation, Job, Message

if TYPE_CHECKING:
    from .runtime import Runtime

STATUSES = {"accepted": "принят", "in_progress": "в работе", "ready": "готов, можно забирать", "issued": "выдан",
            "cancelled": "отменён"}
KEEP = timedelta(days=120)  # older jobs are not looked up from chats
_NUMBER = re.compile(r"(?<![\d+])\d{3,6}(?!\d)")
_PHONE = re.compile(r"(?:\+?996|0)[\s\-()]*\d(?:[\s\-()]*\d){8}")


MAX_CANDIDATES = 2  # more receipt numbers than this in one chat looks like guessing: look nothing up


def next_number(session: Session, business_id: int) -> str:
    """A random 5-digit receipt number: sequential numbers could be guessed one after another."""
    used = set(session.exec(select(Job.number).where(Job.business_id == business_id)).all())
    while True:
        number = str(secrets.randbelow(90000) + 10000)
        if number not in used:
            return number


def _recent_customer_texts(session: Session, conv: Conversation, now_utc: datetime) -> list[str]:
    return list(session.exec(select(Message.text).where(Message.conversation_id == conv.id, Message.role == "customer",
                                                        Message.created_at >= now_utc - timedelta(hours=72))
                             .order_by(Message.id.desc()).limit(6)).all())


def for_chat(session: Session, business: Business, conv: Conversation, now_utc: datetime, latest: str = "") -> list[Job]:
    texts = [latest] + _recent_customer_texts(session, conv, now_utc)
    typed = {phone_key(m) for t in texts for m in _PHONE.findall(t or "")} | {phone_key(conv.customer_phone)}
    typed.discard("")
    phone_parts = {d for t in texts for m in _PHONE.findall(t or "") for d in _NUMBER.findall(m)}
    numbers = {n for t in texts for n in _NUMBER.findall(t or "")} - phone_parts
    if len(numbers) > MAX_CANDIDATES:
        numbers = set()
    trusted = phone_key(conv.chat_id) if conv.channel == "whatsapp" else ""
    jobs = session.exec(select(Job).where(Job.business_id == business.id, Job.status != "cancelled",
                                          Job.created_at >= now_utc - KEEP).order_by(Job.created_at.desc())).all()
    found = [j for j in jobs if (trusted and j.phone_key == trusted) or (j.number in numbers and j.phone_key in typed)]
    for j in found:
        # Ready notices go to the chat that asked: the customer's own WhatsApp always, another chat only if
        # no chat was tied to the job yet, so nobody can redirect someone else's notice later.
        if j.status != "issued" and j.conversation_id != conv.id and (
                (trusted and j.phone_key == trusted) or j.conversation_id is None):
            j.conversation_id = conv.id
            session.add(j)
    return found[:5]


def describe(job: Job) -> str:
    out = f"№{job.number}: {job.item} — {STATUSES.get(job.status, job.status)}"
    if job.ready_by and job.status in {"accepted", "in_progress"}:
        out += f", срок готовности {job.ready_by:%d.%m}"
    if job.price:
        out += f", стоимость {job.price}"
    if job.note:
        out += f" ({job.note})"
    return out


def prompt_hint(session: Session, business: Business, conv: Conversation, now_utc: datetime, latest: str) -> str:
    if conv.id is None:
        return ""
    found = for_chat(session, business, conv, now_utc, latest)
    if found:
        lines = ["", "Заказы этого клиента (данные из системы, статус меняют сотрудники):"]
        lines += [f"- {describe(j)}" for j in found]
        lines.append("О готовности, сроках и стоимости заказа отвечай только по этим данным. Если срок прошёл, "
                     "а заказ не готов, извинись и заполни handoff, чтобы сотрудник уточнил.")
        return "\n".join(lines)
    return ("\nЕсли клиент спрашивает о готовности своего заказа, попроси номер квитанции и телефон, указанный при сдаче. "
            "Пока заказ не найден в данных выше, статус, сроки и стоимость не называй и не придумывай.")


def ready_text(business: Business, job: Job, kyrgyz: bool) -> str:
    where = ", ".join(x for x in (business.address, business.hours_text) if x)
    if kyrgyz:
        out = f"Сиздин №{job.number} буйрутмаңыз даяр: {job.item}. Алып кетсеңиз болот"
        return out + (f" — {where}." if where else ".") + (f" Баасы: {job.price}." if job.price else "")
    out = f"Ваш заказ №{job.number} готов: {job.item}. Можно забирать"
    return out + (f" — {where}." if where else ".") + (f" К оплате: {job.price}." if job.price else "")


def _chat_for(session: Session, business: Business, job: Job) -> Conversation | None:
    if job.conversation_id:
        return session.get(Conversation, job.conversation_id)
    if not job.phone_key:
        return None
    return session.exec(select(Conversation).where(Conversation.business_id == business.id, Conversation.channel == "whatsapp",
                                                   Conversation.chat_id.endswith(job.phone_key))).first()


def notify_ready(session: Session, rt: "Runtime", business: Business, job: Job, now_utc: datetime) -> bool:
    conv = _chat_for(session, business, job)
    if conv is None:
        return False
    last = session.exec(select(Message.text).where(Message.conversation_id == conv.id, Message.role == "customer")
                        .order_by(Message.id.desc())).first()
    ok = deliver_to_chat(session, rt, business, conv, ready_text(business, job, bool(last) and is_kyrgyz_message(last)), now_utc)
    if ok:
        job.ready_notified = True
        session.add(job)
    return ok
