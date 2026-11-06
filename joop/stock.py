"""Stock for goods sold in the chat: the AI never sells what is not on the shelf, and the owner hears when it runs low.

МойСклад's core is "учёт остатков, оповещения о минимальных остатках, инвентаризация". A salon or a cafe needs a
small part of it: shampoo, gift certificates, cakes of the day. A catalog item becomes tracked when the owner types
how many there are; from then on an order the AI takes in the chat checks the count (code, not the model — «осталось 2»),
takes it off when the order is placed, puts it back when the order is cancelled, takes the item off sale at zero and
tells the staff when it falls to the minimum. The «Склад» page is the recount: type what is really there, the
difference is written down as a move with who and when — inventarisation without a separate program.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import update
from sqlmodel import Session, select

from .models import OrderLine, Service, StockMove


def tracked(item: Service) -> bool:
    return item.stock is not None


def short(item: Service, qty: int) -> str:
    """Why this quantity cannot be sold, or "" when it can."""
    if not tracked(item) or qty <= item.stock:
        return ""
    return f"«{item.name}» осталось {item.stock} шт." if item.stock > 0 else f"«{item.name}» закончился"


def _move(session: Session, item: Service, delta: int, reason: str, who: str, now_utc: datetime, order_id: int | None = None) -> None:
    new = max(0, (item.stock or 0) + delta)
    delta, item.stock = new - (item.stock or 0), new  # what really changed: a clamp never invents stock on a return
    if item.stock == 0 and item.available:
        item.available, item.sold_out = False, True  # sold out: off the list the AI offers
    elif item.stock > 0 and item.sold_out:
        item.available, item.sold_out = True, False  # back in stock; an item the owner stopped stays stopped
    session.add(item)
    session.add(StockMove(business_id=item.business_id, service_id=item.id, delta=delta, left=item.stock, reason=reason,
                          who=who[:80], order_id=order_id, created_at=now_utc))


def _held(session: Session, order_id: int) -> dict[int, int]:
    """Pieces this order holds now, per item: takes minus returns."""
    out: dict[int, int] = {}
    for m in session.exec(select(StockMove).where(StockMove.order_id == order_id)).all():
        out[m.service_id] = out.get(m.service_id, 0) - m.delta
    return out


def take_for_order(session: Session, order_id: int, now_utc: datetime, who: str = "ИИ") -> list[str]:
    """Take the ordered goods off the shelf; notes for the staff when an item reaches its minimum or runs out."""
    notes: list[str] = []
    wanted: dict[int, int] = {}
    for line in session.exec(select(OrderLine).where(OrderLine.order_id == order_id)).all():
        if line.item_id:
            wanted[line.item_id] = wanted.get(line.item_id, 0) + line.quantity
    held = _held(session, order_id)
    for item_id, qty in wanted.items():
        item = session.get(Service, item_id)
        need = qty - held.get(item_id, 0)
        if item is None or not tracked(item) or need <= 0:
            continue
        before = item.stock
        # one statement that only succeeds while the pieces are there: two chats ordering the last piece at once
        # cannot both take it
        took = session.execute(update(Service).where(Service.id == item.id, Service.stock >= need)
                               .values(stock=Service.stock - need)).rowcount
        session.refresh(item)
        if took:
            item.stock += need  # _move writes the change and its history from the count before
            before = item.stock
        else:
            notes.append(f"Склад: заказ #{order_id} — «{item.name}» просили {need} шт., а осталось {item.stock}. Свяжитесь с клиентом.")
            before = item.stock
        _move(session, item, -need, "order", who, now_utc, order_id)
        if item.stock == 0:
            notes.append(f"Склад: «{item.name}» закончился — ИИ больше его не предлагает. Пополните остаток в разделе «Склад».")
            continue
        if item.stock_min and before > item.stock_min >= item.stock:
            notes.append(f"Склад: «{item.name}» осталось {item.stock} шт. (минимум {item.stock_min}).")
    return notes


def return_for_order(session: Session, order_id: int, who: str, now_utc: datetime) -> None:
    """A cancelled order puts back what it holds — never more, however often it is cancelled and restored."""
    for item_id, qty in _held(session, order_id).items():
        item = session.get(Service, item_id)
        if item is not None and qty > 0:
            _move(session, item, qty, "return", who, now_utc, order_id)


def recount(session: Session, item: Service, counted: int | None, minimum: int, who: str, now_utc: datetime) -> None:
    """Set what is really there; None stops tracking the item."""
    item.stock_min = max(0, minimum)
    if counted is None:
        item.stock = None
        session.add(item)
        return
    counted = max(0, counted)
    if item.stock is None:
        item.stock = 0
        if counted:
            _move(session, item, counted, "recount", who, now_utc)
        else:
            item.available = False  # tracked from zero: nothing to sell
            session.add(item)
    elif counted != item.stock:
        _move(session, item, counted - item.stock, "recount", who, now_utc)
    else:
        session.add(item)


def low(session: Session, business_id: int) -> list[Service]:
    rows = session.exec(select(Service).where(Service.business_id == business_id, Service.stock != None)).all()  # noqa: E711
    return [s for s in rows if s.stock == 0 or (s.stock_min and s.stock <= s.stock_min)]
