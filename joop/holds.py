"""Reservations that expire (pharmacies): a pickup order not collected in time goes back on the shelf by itself.

A pack sets ``hold_days`` (pharmacy: 1 = «до конца следующего дня»). The hold counts from the day the order became
the customer's to collect: the day staff marked it «Готов к выдаче», or — for an order nobody touched, still «Новый»
— the day it was placed. After the end of that day + hold_days, in the business's own time zone, the scheduler
cancels it: its goods are returned to stock, the customer is told in the chat it came from, and the staff get one
note (with a phone to call when the channel would not take the message). An order staff accepted but have not
readied (the medicine is on its way) is not released, and neither is a delivery: it is on its way, not on a shelf.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import TYPE_CHECKING

from sqlmodel import Session, select

from . import stock
from .dispatch import notify_admins
from .followups import _kyrgyz, deliver_to_chat
from .models import Business, Conversation, Message, Order
from .niches import get_pack
from .stats import TEST_CHANNEL, is_test
from .timeutil import local_to_utc, utc_to_local

if TYPE_CHECKING:
    from .runtime import Runtime

HELD = ("new", "sent")  # «Принят» = staff are getting it ready: not on the shelf yet


def expires_at(business: Business, order: Order, hold_days: int) -> datetime:
    """UTC moment the reservation ends: local midnight after day «ready (or placed) + hold_days»."""
    since = order.sent_at if order.status == "sent" and order.sent_at else order.created_at
    placed = utc_to_local(since, business.timezone).date()
    return local_to_utc(datetime.combine(placed + timedelta(days=hold_days + 1), time.min), business.timezone)


def notice(order: Order, kyrgyz: bool) -> str:
    if kyrgyz:  # проверить носителю
        return f"Сиздин №{order.id} буйрутмаңыздын сактоо мөөнөтү бүттү, товар сатууга кайтарылды. Дагы керек болсо, жазыңыз — кайра калтырабыз."
    return f"Срок хранения заказа №{order.id} истёк, товар вернулся в продажу. Если ещё нужно — напишите, отложим снова."


def release_expired(session: Session, rt: "Runtime", business: Business, now_utc: datetime) -> list[int]:
    hold_days = get_pack(business.niche).hold_days
    if hold_days <= 0:
        return []
    rows = session.exec(select(Order).where(Order.business_id == business.id, Order.mode == "pickup",
                                            Order.status.in_(HELD)).order_by(Order.id)).all()
    released, real, call = [], [], []
    for order in rows:
        if now_utc < expires_at(business, order, hold_days):
            continue
        stock.return_for_order(session, order.id, "срок хранения", now_utc)
        order.status = "cancelled"
        session.add(order)
        released.append(order.id)
        conv = session.get(Conversation, order.conversation_id) if order.conversation_id else None
        told = False
        if conv is not None:
            text = notice(order, _kyrgyz(session, conv.id))
            if conv.channel in (TEST_CHANNEL, "web"):  # the test chat and the site chat show it as they show order notices
                session.add(Message(business_id=business.id, conversation_id=conv.id,
                                    role="ai" if conv.channel == TEST_CHANNEL else "staff", text=text, created_at=now_utc))
                told = True
            else:  # WhatsApp and Instagram refuse outside 24 hours: staff call instead
                told = deliver_to_chat(session, rt, business, conv, text, now_utc)
        if conv is not None and is_test(conv):
            continue
        real.append(order.id)
        if not told:
            call.append(f"№{order.id} — {order.customer_name or 'клиент'}, {order.customer_phone or 'телефон не указан'}")
    if real:
        note = "Снят резерв (срок хранения истёк, товар вернулся на склад): " + ", ".join(f"№{n}" for n in real) + "."
        if call:
            note += "\nКлиенту написать не получилось — позвоните: " + "; ".join(call) + "."
        notify_admins(rt, business, [note])
    return released
