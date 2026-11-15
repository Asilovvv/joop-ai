"""«Напишем, когда появится»: a customer who asked for a sold-out item hears when it is back (shops, pharmacies, parts).

The model is not asked anything new. When a customer's message names an item the stock count marked sold out
(«маски есть?» → «Маски медицинские, 50 шт.»), the code adds one fixed line to the reply and keeps a watch. When
stock comes back, the scheduler tells each watching chat once, in the chat it came from. Watches older than
KEEP are dropped silently: a month later the customer has bought it elsewhere. «стоп» stops all of it.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from sqlmodel import Session, select

from .followups import _kyrgyz, deliver_to_chat
from .models import Business, Conversation, Message, Order, OrderLine, Service, StockWatch
from .stats import TEST_CHANNEL

if TYPE_CHECKING:
    from .runtime import Runtime

KEEP = timedelta(days=30)
MAX_ITEMS = 3  # «маски» may match a few sold-out masks; more is a vague question, not a wish
_WORD = re.compile(r"[а-яёөүңa-z]{4,}")


def _stem(word: str) -> str:
    return word[:4]  # «маска», «маски», «масок» share «мас»+: four letters cover Russian and Kyrgyz endings


def asked_for(text: str, sold_out: list[Service]) -> list[Service]:
    """Sold-out items whose first word (its first 4 letters) the customer used: «маски» → «Маски медицинские»."""
    said = {_stem(w) for w in _WORD.findall((text or "").lower())}
    found = []
    for item in sold_out:
        words = _WORD.findall(re.split(r"[,(]", item.name or "", maxsplit=1)[0].lower())
        if words and _stem(words[0]) in said:
            found.append(item)
    return found[:MAX_ITEMS] if len(found) <= MAX_ITEMS else []


def watch_line(session: Session, business: Business, conv: Conversation, text: str, now_utc: datetime, kyrgyz: bool) -> str:
    """Keep a watch for each sold-out item the message names and return the line added to the reply ("" if none)."""
    sold_out = list(session.exec(select(Service).where(Service.business_id == business.id, Service.sold_out)).all())
    items = asked_for(text, sold_out)
    if not items or conv.id is None or conv.silenced:
        return ""
    for item in items:
        open_watch = session.exec(select(StockWatch.id).where(StockWatch.conversation_id == conv.id,
                                                              StockWatch.service_id == item.id,
                                                              StockWatch.notified_at.is_(None))).first()
        if open_watch is None:
            session.add(StockWatch(business_id=business.id, conversation_id=conv.id, service_id=item.id, created_at=now_utc))
    names = ", ".join(f"«{i.name}»" for i in items)
    if kyrgyz:  # проверить носителю
        return f"\n{names} кайра келгенде, ушул жерге жазабыз. Керек эмес болсо, «стоп» деп жазыңыз."
    return f"\nКогда {names} снова появится, напишем вам сюда. Не нужно — напишите «стоп»."


def notice(item: Service, kyrgyz: bool) -> str:
    if kyrgyz:  # проверить носителю
        return f"«{item.name}» кайра сатыкта бар, баасы {item.price}. Калтырып коёлубу?"
    return f"«{item.name}» снова в наличии, цена {item.price}. Отложить для вас?"


def notify_back(session: Session, rt: "Runtime", business: Business, now_utc: datetime) -> dict[str, int]:
    """Tell watching chats about items back in stock; drop watches older than KEEP. Each watch is used once."""
    sent = failed = expired = 0
    rows = session.exec(select(StockWatch).where(StockWatch.business_id == business.id, StockWatch.notified_at.is_(None))).all()
    for watch in rows:
        if watch.created_at < now_utc - KEEP:
            watch.notified_at, expired = now_utc, expired + 1
            session.add(watch)
            continue
        item, conv = session.get(Service, watch.service_id), session.get(Conversation, watch.conversation_id)
        if item is None or conv is None:
            continue
        if not item.available or item.sold_out:
            continue  # still out, or the owner stopped selling it
        watch.notified_at = now_utc
        session.add(watch)
        if conv.silenced:
            continue
        text = notice(item, _kyrgyz(session, conv.id))
        if conv.channel in (TEST_CHANNEL, "web"):
            session.add(Message(business_id=business.id, conversation_id=conv.id,
                                role="ai" if conv.channel == TEST_CHANNEL else "staff", text=text, created_at=now_utc))
            ok = True
        else:
            ok = deliver_to_chat(session, rt, business, conv, text, now_utc)
        watch.sent = ok
        sent, failed = sent + ok, failed + (not ok)
    return {k: v for k, v in {"sent": sent, "failed": failed, "expired": expired}.items() if v}


AFTER = timedelta(days=7)  # an order this soon after the message counts as brought by it


def results(session: Session, business_id: int, since: datetime) -> tuple[int, int, int]:
    """(customers told, orders of that item from them within a week, their total in som) for messages sent since."""
    told = session.exec(select(StockWatch).where(StockWatch.business_id == business_id, StockWatch.sent,
                                                 StockWatch.notified_at >= since)).all()
    bought: dict[int, int] = {}
    for watch in told:
        rows = session.exec(select(Order).join(OrderLine, OrderLine.order_id == Order.id).where(
            Order.conversation_id == watch.conversation_id, OrderLine.item_id == watch.service_id, Order.status != "cancelled",
            Order.created_at >= watch.notified_at, Order.created_at <= watch.notified_at + AFTER)).all()
        for order in rows:
            bought[order.id] = order.total or 0
    return len(told), len(bought), sum(bought.values())
