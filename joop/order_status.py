"""«Где мой заказ?»: the order's status in the chat, and a message to the customer when it moves on.

Staff move an order on the «Заказы» page: Принять → В пути (delivery) or Готов к выдаче (pickup) → Выполнен.
At «Принять» and at «В пути / Готов к выдаче» the customer gets a short message in the chat the order came from.
The AI answers «где мой заказ?» from the same statuses, and only for orders placed in this very chat: nobody
learns about someone else's order by typing their name or phone number.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from sqlmodel import Session, select

from .followups import _kyrgyz, deliver_to_chat
from .models import Business, Conversation, Message, Order, OrderLine
from .stats import TEST_CHANNEL
from .timeutil import utc_to_local

if TYPE_CHECKING:
    from .runtime import Runtime

STATUSES = {"new": "Новый", "accepted": "Принят", "sent": "В пути", "done": "Выполнен", "cancelled": "Отменён"}
NOTIFY = {"accepted", "sent"}  # the steps a customer hears about without asking
# The only moves the panel accepts: a stale tab cannot send an order back, or revive a cancelled one with a message.
NEXT = {"new": ("accepted", "cancelled"), "accepted": ("sent", "done", "cancelled"), "sent": ("done", "cancelled")}


def can_move(order: Order, status: str) -> bool:
    return status in NEXT.get(order.status, ())
KEEP = timedelta(days=30)  # older orders are not brought into the chat
SHOWN = 3


def label(order: Order) -> str:
    """The panel's name of the order's status: «sent» is «В пути» for delivery and «Готов к выдаче» for pickup."""
    if order.status == "sent" and order.mode != "delivery":
        return "Готов к выдаче"
    return STATUSES.get(order.status, order.status)


def sent_label(order: Order) -> str:
    return "В пути" if order.mode == "delivery" else "Готов к выдаче"


def _for_customer(order: Order) -> str:
    delivery = order.mode == "delivery"
    return {
        "new": "принят, ждёт подтверждения сотрудника",
        "accepted": "подтверждён, ещё не отправлен" if delivery else "подтверждён, ещё не готов к выдаче",
        "sent": "передан в доставку, в пути" if delivery else "готов, можно забирать",
        "done": "выполнен",
        "cancelled": "отменён",
    }.get(order.status, order.status)


def _som(value: int) -> str:
    return f"{value:,} сом".replace(",", " ")


def for_chat(session: Session, conv: Conversation, now_utc: datetime) -> list[Order]:
    if conv.id is None:
        return []
    return list(session.exec(select(Order).where(Order.conversation_id == conv.id, Order.created_at >= now_utc - KEEP)
                             .order_by(Order.id.desc()).limit(SHOWN)).all())


def describe(session: Session, business: Business, order: Order) -> str:
    rows = session.exec(select(OrderLine).where(OrderLine.order_id == order.id).order_by(OrderLine.id)).all()
    when = utc_to_local(order.created_at, business.timezone)
    parts = [f"№{order.id} от {when:%d.%m}: " + ", ".join(f"{r.quantity} × {r.name}" for r in rows)]
    if order.total is not None:
        parts.append(_som(order.total))
    parts.append(f"доставка: {order.address}" if order.mode == "delivery" and order.address else
                 "доставка" if order.mode == "delivery" else "самовывоз")
    return "; ".join(parts) + f" — статус: {_for_customer(order)}"


def prompt_hint(session: Session, business: Business, conv: Conversation, now_utc: datetime) -> str:
    orders = for_chat(session, conv, now_utc)
    if not orders:
        return ""
    lines = ["", "Заказы клиента в этом чате (данные из системы, статус меняют сотрудники):"]
    lines += [f"- {describe(session, business, o)}" for o in orders]
    lines.append("На вопросы о заказе («где мой заказ», «когда привезут») отвечай только по этим данным; сроки доставки — "
                 "только из данных компании. Если клиент ждёт дольше обещанного или спрашивает о заказе, которого здесь нет, "
                 "извинись и заполни handoff, чтобы сотрудник уточнил.")
    return "\n".join(lines)


def where_to_collect(business: Business) -> str:
    """Address and hours for a «come and collect» message; hours copied from the sign-up example are not facts."""
    from . import samples

    hours = "" if samples.hours_are_example(business) else business.hours_text
    return ", ".join(x for x in (business.address, hours) if x)


def notice_text(business: Business, order: Order, kyrgyz: bool) -> str | None:
    """What the customer hears when staff move the order on; None for steps that are not announced.
    Kyrgyz wording: проверить носителю."""
    where = where_to_collect(business)
    total = _som(order.total) if order.total is not None else ""
    if order.status == "accepted":
        if kyrgyz:
            return f"Сиздин №{order.id} буйрутмаңыз ырасталды." + (f" Суммасы: {total}." if total else "")
        return f"Ваш заказ №{order.id} подтверждён." + (f" Сумма: {total}." if total else "")
    if order.status == "sent" and order.mode == "delivery":
        if kyrgyz:
            return f"Сиздин №{order.id} буйрутмаңыз жеткирүүгө берилди, жолдо."
        return f"Ваш заказ №{order.id} передан в доставку и уже в пути."
    if order.status == "sent":
        if kyrgyz:
            return f"Сиздин №{order.id} буйрутмаңыз даяр, алып кетсеңиз болот" + (f" — {where}." if where else ".")
        return f"Ваш заказ №{order.id} готов, можно забирать" + (f" — {where}." if where else ".")
    return None


def notify(session: Session, rt: "Runtime", business: Business, order: Order, now_utc: datetime) -> tuple[bool | None, str]:
    """Tell the customer about the order's new status: (None, "") when there is nothing to tell (a silent step, or the
    order did not come from a chat), (True, "") when it went out, (False, why) when the channel would not take it."""
    from .staff_reply import blocked

    conv = session.get(Conversation, order.conversation_id) if order.conversation_id else None
    if order.status not in NOTIFY or conv is None:
        return None, ""
    text = notice_text(business, order, _kyrgyz(session, conv.id))
    if text is None:
        return None, ""
    if conv.channel in (TEST_CHANNEL, "web"):
        # The test chat shows it where the owner tested; the site chat picks up «staff» messages while it is open.
        session.add(Message(business_id=business.id, conversation_id=conv.id, role="ai" if conv.channel == TEST_CHANNEL else "staff",
                            text=text, created_at=now_utc))
        conv.last_message_at = now_utc
        session.add(conv)
        return True, ""
    if deliver_to_chat(session, rt, business, conv, text, now_utc):
        return True, ""
    return False, blocked(conv, now_utc) or "Канал не принял сообщение или чат заблокирован."
