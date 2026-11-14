"""«Пора повторить заказ?»: a reminder at the customer's own pace (drinking water and other regular deliveries).

On when the business turned on «Пригласить снова» and its pack has ``repeat_order``. For every chat with orders,
the code takes the latest order and the customer's usual interval: the median gap between their last orders
(two or more), else the largest «через, дней» of the items they ordered. On the day it is due (and for a week
after) the customer gets one message naming the last order; «да» is answered by the AI from joop/repeat_order.py,
which proposes the same order for the code to check. No reminder after a newer order, a cancelled one, in a test
chat, or in a chat that said «стоп» (which works after a reminder too: joop/broadcasts.py).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from statistics import median
from typing import TYPE_CHECKING

from sqlmodel import Session, select

from .followups import _kyrgyz, deliver_to_chat
from .models import Business, Conversation, Order, OrderLine, Service
from .niches import get_pack
from .stats import not_test
from .timeutil import utc_to_local

if TYPE_CHECKING:
    from .runtime import Runtime

LOOK_BACK = timedelta(days=180)
LATE_DAYS = 7  # past this, a reminder reads as spam: skip it
MIN_GAP, MAX_GAP = 3, 90  # days; anything else is a one-off, not a habit


def interval(orders: list[Order], items: dict[int, Service], lines: list[OrderLine]) -> int:
    """The customer's usual number of days between orders; 0 when there is no habit to go by."""
    dates = sorted(o.created_at.date() for o in orders)
    gaps = [(b - a).days for a, b in zip(dates, dates[1:]) if (b - a).days > 0]
    if gaps:
        days = int(median(gaps))
        return days if MIN_GAP <= days <= MAX_GAP else 0
    return max((items[line.item_id].repeat_days for line in lines if line.item_id in items), default=0)


def text(business: Business, order: Order, lines: list[OrderLine], kyrgyz: bool) -> str:
    when = utc_to_local(order.created_at, business.timezone)
    what = ", ".join(f"{line.quantity} × {line.name}" for line in lines)
    if kyrgyz:  # проверить носителю
        return (f"Саламатсызбы! Акыркы буйрутмаңыз №{order.id} {when:%d.%m} болгон: {what}. Кайталайлыбы? "
                "«Ооба» деп жазыңыз — ошол эле дарекке жөнөтөбүз. Эскертме керек болбосо, «стоп» деп жазыңыз.")
    return (f"Здравствуйте! Ваш прошлый заказ №{order.id} от {when:%d.%m}: {what}. Повторить? Ответьте «да» — оформим "
            "на тот же адрес. Если напоминания не нужны, напишите «стоп».")


def send_due(session: Session, rt: "Runtime", business: Business, now_utc: datetime) -> dict[str, int]:
    if not business.return_invites or not get_pack(business.niche).offers("repeat_order"):
        return {}
    today = utc_to_local(now_utc, business.timezone).date()
    rows = session.exec(select(Order).where(
        Order.business_id == business.id, Order.conversation_id.is_not(None),
        Order.created_at >= now_utc - LOOK_BACK, not_test(Order, business.id),
    ).order_by(Order.created_at)).all()
    by_chat: dict[int, list[Order]] = {}
    for o in rows:
        by_chat.setdefault(o.conversation_id, []).append(o)
    items = {s.id: s for s in session.exec(select(Service).where(Service.business_id == business.id)).all()}
    sent = failed = 0
    for conv_id, orders in by_chat.items():
        last = orders[-1]
        if last.reminded_at is not None or last.status == "cancelled":  # a cancelled latest order is no habit to repeat
            continue
        orders = [o for o in orders if o.status != "cancelled"]
        conv = session.get(Conversation, conv_id)
        if conv is None or conv.silenced:
            continue
        lines = list(session.exec(select(OrderLine).where(OrderLine.order_id == last.id).order_by(OrderLine.id)).all())
        days = interval(orders[-5:], items, lines)
        if not days or not lines:
            continue
        due = utc_to_local(last.created_at, business.timezone).date() + timedelta(days=days)
        if not due <= today <= due + timedelta(days=LATE_DAYS):
            continue
        ok = deliver_to_chat(session, rt, business, conv, text(business, last, lines, _kyrgyz(session, conv.id)), now_utc)
        last.reminded_at = now_utc  # one try per order: a channel that refused (WhatsApp after 24 hours) is not retried daily
        last.reminder_ok = ok
        session.add(last)
        sent, failed = sent + ok, failed + (not ok)
    return {"sent": sent, "failed": failed} if sent or failed else {}
