"""«Как в прошлый раз»: the customer's last order, ready to repeat (drinking water, groceries, any regular delivery).

A pack switches it on with ``features: [repeat_order]``. Code finds this customer's last order at the business:
in this chat, or in another chat with the same phone AND the same name (as joop/regulars.py does for bookings,
so a friend's number typed into a chat does not open the friend's orders). The prompt gets its lines with the
catalog numbers, the address and the date, so «два бутыля, как обычно» becomes a proposed order the code then
checks like any other: items exist and are in stock, the total is computed from catalog prices. Items no longer
in the catalog or out of stock are named as such, so the model does not offer them.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

import sqlalchemy as sa
from sqlmodel import Session, select

from .models import Business, Conversation, Order, OrderLine, Service
from .stats import not_test
from .timeutil import utc_to_local

KEEP = timedelta(days=180)  # a water customer may order every week or once a season
_DIGITS = re.compile(r"\D")


def _key(phone: str) -> str:
    digits = _DIGITS.sub("", phone or "")[-9:]
    return digits if len(digits) == 9 else ""


def last_order(session: Session, business: Business, conv: Conversation, now_utc: datetime) -> Order | None:
    key = _key(conv.customer_phone)
    own = Order.conversation_id == conv.id if conv.id else sa.false()
    match = sa.or_(own, Order.customer_phone.like(f"%{key}")) if key else own
    rows = session.exec(select(Order).where(
        Order.business_id == business.id, Order.status != "cancelled", Order.created_at >= now_utc - KEEP,
        sa.or_(own, not_test(Order, business.id)), match,  # the owner's test chat sees its own test orders, no one else's
    ).order_by(Order.id.desc()).limit(10)).all()
    me = (conv.customer_name or conv.display_name or "").strip().casefold()
    for order in rows:
        if order.conversation_id == conv.id or (me and (order.customer_name or "").strip().casefold() == me):
            return order
    return None


def prompt_hint(session: Session, business: Business, conv: Conversation, now_utc: datetime) -> str:
    order = last_order(session, business, conv, now_utc)
    if order is None:
        return ""
    lines = session.exec(select(OrderLine).where(OrderLine.order_id == order.id).order_by(OrderLine.id)).all()
    items = {s.id: s for s in session.exec(select(Service).where(Service.business_id == business.id)).all()}
    parts, gone = [], []
    for line in lines:
        item = items.get(line.item_id)
        if item is None:
            gone.append(f"{line.name} (больше нет в каталоге)")
        elif not item.available or item.sold_out:
            gone.append(f"{item.name} (сейчас нет в наличии)")
        else:
            parts.append(f"[{item.id}] {item.name} × {line.quantity}")
    if not parts and not gone:
        return ""
    when = utc_to_local(order.created_at, business.timezone)
    where = f"доставка: {order.address}" if order.mode == "delivery" and order.address else (
        "доставка" if order.mode == "delivery" else "самовывоз")
    out = ["", f"Прошлый заказ этого клиента №{order.id} от {when:%d.%m} (данные из системы):"]
    if parts:
        out.append("- " + "; ".join(parts) + f"; {where}")
    if gone:
        out.append("- не повторять: " + "; ".join(gone))
    out.append("Если клиент просит «как в прошлый раз», «как обычно» или называет только количество, предложи эти позиции "
               "и этот адрес и спроси подтверждение; новую сумму считает система.")
    return "\n".join(out)
