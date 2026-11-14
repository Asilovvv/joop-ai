"""Reservations that expire (pharmacies): a pickup order not collected in time goes back on the shelf by itself.

A pack sets ``hold_days`` (pharmacy: 1 = «до конца следующего дня»). A pickup order placed on day D and still not
done or cancelled after the end of day D + hold_days, in the business's own time zone, is cancelled by the
scheduler: its goods are returned to stock, the customer is told in the chat it came from, and the staff get one
note. Delivery orders are never released: they are on their way, not on a shelf.
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

OPEN = ("new", "accepted", "sent")


def expires_at(business: Business, order: Order, hold_days: int) -> datetime:
    """UTC moment the reservation ends: local midnight after day «placed + hold_days»."""
    placed = utc_to_local(order.created_at, business.timezone).date()
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
                                            Order.status.in_(OPEN)).order_by(Order.id)).all()
    released, real = [], []
    for order in rows:
        if now_utc < expires_at(business, order, hold_days):
            continue
        stock.return_for_order(session, order.id, "срок хранения", now_utc)
        order.status = "cancelled"
        session.add(order)
        released.append(order.id)
        conv = session.get(Conversation, order.conversation_id) if order.conversation_id else None
        if conv is None:
            real.append(order.id)
            continue
        text = notice(order, _kyrgyz(session, conv.id))
        if conv.channel in (TEST_CHANNEL, "web"):  # the test chat and the site chat show it as they show order notices
            session.add(Message(business_id=business.id, conversation_id=conv.id,
                                role="ai" if conv.channel == TEST_CHANNEL else "staff", text=text, created_at=now_utc))
        else:
            deliver_to_chat(session, rt, business, conv, text, now_utc)
        if not is_test(conv):
            real.append(order.id)
    if real:
        notify_admins(rt, business, ["Снят резерв (срок хранения истёк, товар вернулся на склад): "
                                     + ", ".join(f"№{n}" for n in real) + "."])
    return released
