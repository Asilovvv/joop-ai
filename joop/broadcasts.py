"""Broadcasts: one message from the business to a group of its customers.

Groups come from what the system already knows: who wrote, who came, who has not been back for a while,
who had a given service, who wrote but never booked. A message goes only where the channel allows a
message the business starts: Telegram any time; WhatsApp and Instagram within 24 hours of the customer's
last message (outside it Meta wants a paid, pre-approved template, so those customers are counted and left
out). The web chat has no address to write to later, so its visitors are not in any group.

Rules that keep it from turning into spam:
- every message ends with how to unsubscribe, and "стоп" after a broadcast (or "отписаться" any time)
  turns broadcasts off for that customer; "подписаться" turns them back on;
- at most one broadcast a day per business;
- sending happens only between SEND_HOURS local time, BATCH messages per scheduler tick, so a long list
  does not hit Telegram's limits or wake anybody at night;
- the owner sees the count before sending and can send a test to their own Telegram first.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from sqlmodel import Session, select

from .followups import SERVICE_WINDOW, _kyrgyz, deliver_to_chat
from .lang import is_kyrgyz_message
from .models import Booking, Broadcast, BroadcastDelivery, Business, Conversation
from .timeutil import utc_to_local

if TYPE_CHECKING:
    from .runtime import Runtime

CHANNELS = ("telegram", "whatsapp", "instagram")  # web chat visitors cannot be reached later
WINDOW_CHANNELS = ("whatsapp", "instagram")
MAX_TEXT = 1000
MIN_GAP = timedelta(hours=24)
SEND_HOURS = (10, 20)  # local time: from 10:00 to 19:59
BATCH = 100  # messages per business per scheduler tick
LAPSED_DAYS = 60

SEGMENTS = {
    "all": "Все, кто писал",
    "visited": "Были у нас",
    "lapsed": "Давно не были",
    "service": "Были на услуге",
    "no_booking": "Писали, но не записались",
}
BOOKING_SEGMENTS = {"visited", "lapsed", "service", "no_booking"}

FOOTER = "Чтобы не получать такие сообщения, ответьте «стоп»."
FOOTER_KY = "Мындай кабарларды албаш үчүн «стоп» деп жазыңыз."
OPT_OUT_REPLY = "Готово, больше не будем присылать рассылки. На вопросы отвечу как обычно."
OPT_OUT_REPLY_KY = "Макул, мындан ары кабар жибербейбиз. Суроолоруңузга мурдагыдай жооп берем."
OPT_IN_REPLY = "Готово, будем присылать новости и акции. Чтобы отписаться, ответьте «стоп»."
OPT_IN_REPLY_KY = "Макул, жаңылыктарды жана акцияларды жиберип турабыз. Баш тартуу үчүн «стоп» деп жазыңыз."

STOP_ALWAYS = {"отписаться", "отписка", "отпишите", "отпишите меня", "unsubscribe"}
STOP_KY = {"токто", "токтот", "токтотуңуз", "жибербеңиз", "керек эмес"}
STOP_AFTER_BROADCAST = {"стоп", "stop", "хватит", "не присылайте", "не пишите"} | STOP_KY
START = {"подписаться", "subscribe", "возобновить рассылку"}
_NOT_WORD = re.compile(r"[^\w\s]")
_SPACES = re.compile(r"\s+")


def _norm(text: str) -> str:
    return _SPACES.sub(" ", _NOT_WORD.sub(" ", (text or "").lower().replace("ё", "е"))).strip()


def opt_change(session: Session, conv: Conversation, text: str) -> bool | None:
    """True: the customer unsubscribes; False: subscribes again; None: the message is about something else.

    A bare "стоп" counts only after this customer got a broadcast: in the middle of a booking it means "wait".
    """
    t = _norm(text)
    if t in START:
        return False
    if t in STOP_ALWAYS:
        return True
    if t in STOP_AFTER_BROADCAST and conv.id is not None:
        got = session.exec(select(BroadcastDelivery.id).where(
            BroadcastDelivery.conversation_id == conv.id, BroadcastDelivery.status == "sent")).first()
        return True if got is not None else None
    return None


def opt_reply(opted_out: bool, text: str) -> str:
    kyrgyz = _norm(text) in STOP_KY or is_kyrgyz_message(text)
    if opted_out:
        return OPT_OUT_REPLY_KY if kyrgyz else OPT_OUT_REPLY
    return OPT_IN_REPLY_KY if kyrgyz else OPT_IN_REPLY


def segments_for(books: bool) -> dict[str, str]:
    return {k: v for k, v in SEGMENTS.items() if books or k not in BOOKING_SEGMENTS}


def segment_label(b: Broadcast) -> str:
    label = SEGMENTS.get(b.segment, b.segment)
    if b.segment == "lapsed":
        return f"{label} {b.segment_arg}+ дней"
    if b.segment == "service":
        return f"{label} «{b.segment_arg}»"
    return label


# --- who is in a group -------------------------------------------------------------------------


def _group(session: Session, business: Business, segment: str, arg: str, now_utc: datetime) -> list[Conversation]:
    """Conversations in the group, unsubscribed ones included (the preview counts them)."""
    convs = list(session.exec(select(Conversation).where(
        Conversation.business_id == business.id, Conversation.channel.in_(CHANNELS),
        Conversation.last_customer_at != None,  # noqa: E711  (someone actually wrote)
    ).order_by(Conversation.id)).all())
    if segment == "all":
        return convs
    now_local = utc_to_local(now_utc, business.timezone)
    rows = session.exec(select(Booking.conversation_id, Booking.start, Booking.service, Booking.status).where(
        Booking.business_id == business.id, Booking.conversation_id != None)).all()  # noqa: E711
    if segment == "no_booking":
        any_booking = {r[0] for r in rows}
        return [c for c in convs if c.id not in any_booking]
    booked = [r for r in rows if r[3] == "booked"]
    past = [r for r in booked if r[1] < now_local]
    if segment == "visited":
        ids = {r[0] for r in past}
    elif segment == "lapsed":
        days = _days(arg)
        last: dict[int, datetime] = {}
        for cid, start, _, _ in past:
            last[cid] = max(last.get(cid, start), start)
        upcoming = {r[0] for r in booked if r[1] >= now_local}
        ids = {cid for cid, start in last.items() if start < now_local - timedelta(days=days) and cid not in upcoming}
    elif segment == "service":
        name = arg.strip().lower()
        ids = {r[0] for r in past if name and name in (r[2] or "").lower()}
    else:
        return []
    return [c for c in convs if c.id in ids]


def _days(arg: str) -> int:
    try:
        return max(7, min(int(arg), 730))
    except (TypeError, ValueError):
        return LAPSED_DAYS


def _reachable(conv: Conversation, now_utc: datetime) -> bool:
    if conv.channel == "telegram":
        return True
    return bool(conv.channel in WINDOW_CHANNELS and conv.last_customer_at and now_utc - conv.last_customer_at < SERVICE_WINDOW)


@dataclass
class Preview:
    telegram: int = 0
    window: int = 0  # WhatsApp and Instagram customers who wrote within the last 24 hours
    outside: int = 0  # WhatsApp and Instagram customers outside the window: they will not get it
    opted_out: int = 0

    @property
    def reachable(self) -> int:
        return self.telegram + self.window


def preview(session: Session, business: Business, segment: str, arg: str, now_utc: datetime) -> Preview:
    p = Preview()
    for c in _group(session, business, segment, arg, now_utc):
        if c.broadcast_opt_out:
            p.opted_out += 1
        elif c.channel == "telegram":
            p.telegram += 1
        elif _reachable(c, now_utc):
            p.window += 1
        else:
            p.outside += 1
    return p


def opted_out_count(session: Session, business: Business) -> int:
    return len(session.exec(select(Conversation.id).where(
        Conversation.business_id == business.id, Conversation.broadcast_opt_out == True)).all())  # noqa: E712


# --- starting and sending ----------------------------------------------------------------------


def compose(b: Broadcast, kyrgyz: bool) -> str:
    ky = kyrgyz and bool(b.text_ky)
    return f"{b.text_ky if ky else b.text}\n\n{FOOTER_KY if ky else FOOTER}"


def next_allowed(session: Session, business: Business) -> datetime | None:
    """When the next broadcast may start (UTC), counted from the last one that sent anything; None if none did."""
    last = session.exec(select(Broadcast).where(
        Broadcast.business_id == business.id, (Broadcast.sent > 0) | (Broadcast.status == "sending"),
    ).order_by(Broadcast.created_at.desc())).first()
    return last.created_at + MIN_GAP if last else None


def start(session: Session, business: Business, text: str, text_ky: str, segment: str, arg: str, books: bool,
          now_utc: datetime) -> tuple[Broadcast | None, str]:
    """Create the broadcast and its recipients. Returns (broadcast, "") or (None, reason in Russian)."""
    text, text_ky = (text or "").strip(), (text_ky or "").strip()
    if not text:
        return None, "Напишите текст рассылки."
    if len(text) > MAX_TEXT or len(text_ky) > MAX_TEXT:
        return None, f"Текст длиннее {MAX_TEXT} символов — сократите его."
    if segment not in segments_for(books):
        return None, "Выберите группу клиентов."
    if segment == "service" and not arg.strip():
        return None, "Выберите услугу."
    allowed = next_allowed(session, business)
    if allowed and allowed > now_utc:
        when = utc_to_local(allowed, business.timezone).strftime("%d.%m %H:%M")
        return None, f"Рассылка — не чаще раза в сутки, чтобы клиенты не отписывались. Следующую можно с {when}."
    people = [c for c in _group(session, business, segment, arg, now_utc)
              if not c.broadcast_opt_out and _reachable(c, now_utc)]
    if not people:
        return None, "В этой группе сейчас некому отправить."
    arg = str(_days(arg)) if segment == "lapsed" else arg.strip()[:120] if segment == "service" else ""
    b = Broadcast(business_id=business.id, text=text, text_ky=text_ky, segment=segment, segment_arg=arg,
                  total=len(people), created_at=now_utc)
    session.add(b)
    session.flush()
    for c in people:
        session.add(BroadcastDelivery(broadcast_id=b.id, conversation_id=c.id))
    return b, ""


def cancel(session: Session, b: Broadcast, now_utc: datetime) -> None:
    if b.status != "sending":
        return
    for d in session.exec(select(BroadcastDelivery).where(BroadcastDelivery.broadcast_id == b.id,
                                                          BroadcastDelivery.status == "pending")).all():
        d.status = "skipped"
        session.add(d)
        b.skipped += 1
    b.status, b.finished_at = "cancelled", now_utc
    session.add(b)


def finished_note(b: Broadcast) -> str:
    note = f"Рассылка «{b.text[:60]}{'…' if len(b.text) > 60 else ''}» отправлена: получили {b.sent} из {b.total}."
    if b.skipped:
        note += (f" Не дошло {b.skipped}: клиент отписался, в WhatsApp и Instagram прошло больше суток "
                 "с его сообщения, или клиент заблокировал бота.")
    return note


def send_due(session: Session, rt: "Runtime", business: Business, now_utc: datetime) -> dict:
    """Send the next batch of every running broadcast; report what finished."""
    hour = utc_to_local(now_utc, business.timezone).hour
    if not SEND_HOURS[0] <= hour < SEND_HOURS[1]:
        return {}
    running = session.exec(select(Broadcast).where(Broadcast.business_id == business.id, Broadcast.status == "sending")
                           .order_by(Broadcast.id)).all()
    budget, sent, notes = BATCH, 0, []
    for b in running:
        batch = session.exec(select(BroadcastDelivery).where(
            BroadcastDelivery.broadcast_id == b.id, BroadcastDelivery.status == "pending",
        ).order_by(BroadcastDelivery.id).limit(budget)).all()
        for d in batch:
            conv = session.get(Conversation, d.conversation_id)
            ok = bool(conv) and not conv.broadcast_opt_out and deliver_to_chat(
                session, rt, business, conv, compose(b, _kyrgyz(session, conv.id)), now_utc)
            d.status, d.sent_at = ("sent", now_utc) if ok else ("skipped", None)
            session.add(d)
            if ok:
                b.sent += 1
                sent += 1
            else:
                b.skipped += 1
        budget -= len(batch)
        left = session.exec(select(BroadcastDelivery.id).where(BroadcastDelivery.broadcast_id == b.id,
                                                               BroadcastDelivery.status == "pending")).first()
        if left is None:
            b.status, b.finished_at = "done", now_utc
            notes.append(finished_note(b))
        session.add(b)
        if budget <= 0:
            break
    if notes:
        from .dispatch import notify_admins

        notify_admins(rt, business, notes)
    return {"sent": sent, "finished": len(notes)} if sent or notes else {}
