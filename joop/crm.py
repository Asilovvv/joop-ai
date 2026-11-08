"""amoCRM / Kommo: every booking, request and order the AI takes becomes a deal in the business's CRM.

Many businesses in Bishkek keep their sales in amoCRM (Kommo is its international version). The owner creates a
private integration there, generates a long-lived token and pastes it with the account address into the panel;
from then on each new booking, request and order goes to the CRM as a deal with the customer's contact and a note.

API facts this module relies on (developers.kommo.com; amoCRM uses the same API v4 at {subdomain}.amocrm.ru):
- a long-lived token of a private integration ("Keys and scopes" → "Generate long-lived token", 1 day to 5 years),
  sent as `Authorization: Bearer <token>`; it has no refresh token;
- GET /api/v4/account checks the token;
- POST /api/v4/leads/complex creates deals, each with at most one contact (up to 50 per request; the answer is a
  list of {id, contact_id, company_id, request_id, merged});
- POST /api/v4/leads/notes adds notes to deals.

Deals are sent by the scheduler, one at a time, so a deal the CRM rejects (HTTP 400) is skipped and does not hold
the others back. Each item keeps the deal id in `crm_id` ("-" when the CRM rejected it), so nothing goes twice.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

import httpx
from sqlmodel import Session, select

from .models import Booking, Business, Lead, Order, OrderLine
from .stats import not_test
from .timeutil import fmt_slot

log = logging.getLogger(__name__)

HOSTS = ("amocrm.ru", "amocrm.com", "kommo.com")  # the API is reached only on these, never on an address typed freely
LOOK_BACK = timedelta(days=3)  # older items are not sent when the CRM is connected later
BATCH = 20  # items per scheduler tick
MIN_INTERVAL = 0.15  # seconds between calls: amoCRM allows a few requests a second
LEAD_KINDS = {"request": "Заявка на запись", "lead": "Заявка", "handoff": "Вопрос администратору", "media": "Вложение от клиента"}
CHANNELS = {"telegram": "Telegram", "whatsapp": "WhatsApp", "instagram": "Instagram", "web": "Чат на сайте"}


class CrmError(Exception):
    def __init__(self, status: int, message: str = "") -> None:
        super().__init__(f"{status} {message}".strip())
        self.status, self.message = status, message


def base_url(address: str) -> str:
    """"mycompany.amocrm.ru", "https://mycompany.kommo.com/leads" -> "https://mycompany.amocrm.ru"; "" if not a CRM host."""
    text = (address or "").strip().lower()
    if not text:
        return ""
    host = (urlsplit(text if "://" in text else "https://" + text).hostname or "").strip(".")
    parts = host.split(".")
    if len(parts) != 3 or not parts[0] or ".".join(parts[1:]) not in HOSTS:
        return ""
    if not all(ch.isalnum() or ch == "-" for ch in parts[0]):
        return ""
    return f"https://{host}"


class AmoClient:
    def __init__(self, http: httpx.Client, base: str, token: str, min_interval: float = MIN_INTERVAL) -> None:
        self.http, self.base, self._headers = http, base.rstrip("/"), {"Authorization": f"Bearer {token}"}
        self.min_interval, self._last = min_interval, 0.0

    def _call(self, method: str, path: str, body: Any = None) -> Any:
        wait = self._last + self.min_interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        try:
            r = self.http.request(method, f"{self.base}/api/v4/{path}", json=body, headers=self._headers, timeout=20.0)
        except httpx.HTTPError as exc:
            raise CrmError(0, type(exc).__name__) from exc
        if r.status_code >= 400:
            try:
                detail = str(r.json().get("title") or r.json().get("detail") or "")[:200]
            except (ValueError, AttributeError):
                detail = ""
            raise CrmError(r.status_code, detail)
        try:
            return r.json() if r.content else None
        except ValueError:
            return None

    def account(self) -> dict:
        data = self._call("GET", "account")
        return data if isinstance(data, dict) else {}

    def add_deal(self, deal: dict) -> int:
        data = self._call("POST", "leads/complex", [deal])
        items = data if isinstance(data, list) else []  # [{id, contact_id, company_id, request_id, merged}]
        if not items or not isinstance(items[0], dict) or not items[0].get("id"):
            raise CrmError(200, "no deal id in the answer")
        return int(items[0]["id"])

    def add_note(self, deal_id: int, text: str) -> None:
        self._call("POST", "leads/notes", [{"entity_id": deal_id, "note_type": "common", "params": {"text": text}}])


# --- what goes to the CRM ----------------------------------------------------------------------


def _deal(name: str, customer: str, phone: str, price: int, tags: list[str], pipeline_id: int) -> dict:
    contact: dict[str, Any] = {"first_name": (customer or "Клиент")[:100]}
    if phone:
        contact["custom_fields_values"] = [{"field_code": "PHONE", "values": [{"value": phone, "enum_code": "WORK"}]}]
    deal: dict[str, Any] = {"name": name[:250], "price": max(0, int(price or 0)),
                            "_embedded": {"contacts": [contact], "tags": [{"name": t} for t in tags if t]}}
    if pipeline_id > 0:
        deal["pipeline_id"] = pipeline_id
    return deal


def _dialogue(base: str, conversation_id: int | None) -> str:
    return f"Диалог: {base.rstrip('/')}/panel/conversations/{conversation_id}" if base and conversation_id else ""


@dataclass
class Item:
    row: Any  # Booking, Lead or Order: gets crm_id
    deal: dict
    note: str


def due_items(session: Session, business: Business, now_utc: datetime, base: str = "") -> list[Item]:
    """New bookings, requests and orders to send; the panel's test chat stays out of the CRM."""
    since = now_utc - LOOK_BACK
    pipeline = business.crm_pipeline_id
    items: list[Item] = []
    for b in session.exec(select(Booking).where(Booking.business_id == business.id, Booking.crm_id == "",
                                                Booking.source == "ai", Booking.created_at >= since,
                                                not_test(Booking)).order_by(Booking.id)).all():
        what = b.service or "приём"
        lines = [f"Запись через ИИ: {what}, {fmt_slot(b.start)}" + (f", {b.staff_name}" if b.staff_name else ""),
                 f"Канал: {CHANNELS.get(b.channel, b.channel)}"]
        if b.deposit_due:
            lines.append(f"Предоплата: {b.deposit_due} сом")
        if b.status == "cancelled":
            lines.append("Запись уже отменена.")
        lines.append(_dialogue(base, b.conversation_id))
        items.append(Item(b, _deal(f"Запись: {what} — {fmt_slot(b.start)}", b.customer_name, b.customer_phone, 0,
                                   ["Joop AI", "запись"], pipeline), "\n".join(x for x in lines if x)))
    for x in session.exec(select(Lead).where(Lead.business_id == business.id, Lead.crm_id == "", Lead.kind.in_(LEAD_KINDS),
                                             Lead.created_at >= since, not_test(Lead)).order_by(Lead.id)).all():
        title = LEAD_KINDS[x.kind]
        lines = [f"{title}: {x.summary}", x.details, f"Канал: {CHANNELS.get(x.channel, x.channel)}" if x.channel else "",
                 _dialogue(base, x.conversation_id)]
        items.append(Item(x, _deal(f"{title}: {x.summary or 'клиент'}"[:120], x.customer_name, x.customer_phone, 0,
                                   ["Joop AI", "заявка"], pipeline), "\n".join(v for v in lines if v)))
    for o in session.exec(select(Order).where(Order.business_id == business.id, Order.crm_id == "",
                                              Order.created_at >= since, not_test(Order)).order_by(Order.id)).all():
        rows = session.exec(select(OrderLine).where(OrderLine.order_id == o.id)).all()
        lines = [f"{r.name} × {r.quantity}" for r in rows]
        lines += [("Доставка: " + o.address) if o.mode == "delivery" else "Самовывоз",
                  f"Время: {o.wanted_time}" if o.wanted_time else "", f"Комментарий: {o.comment}" if o.comment else "",
                  f"Итого: {o.total} сом" if o.total is not None else "Итог посчитает администратор: не у всех позиций точная цена",
                  _dialogue(base, o.conversation_id)]
        items.append(Item(o, _deal(f"Заказ №{o.id}", o.customer_name, o.customer_phone, o.total or 0, ["Joop AI", "заказ"],
                                   pipeline), "\n".join(v for v in lines if v)))
    items.sort(key=lambda i: i.row.created_at)
    return items[:BATCH]


def push_due(session: Session, client: AmoClient, business: Business, now_utc: datetime, base: str = "") -> dict[str, int]:
    """Send new bookings, requests and orders as deals. Stops at the first error that is not about one item."""
    sent = skipped = 0
    for item in due_items(session, business, now_utc, base):
        try:
            deal_id = client.add_deal(item.deal)
        except CrmError as exc:
            if exc.status in (400, 422):  # this item's data: skip it, keep going
                item.row.crm_id = "-"
                session.add(item.row)
                skipped += 1
                business.crm_error = f"amoCRM не принял одну сделку ({exc.status} {exc.message})".strip()
                continue
            business.crm_error = ("amoCRM не принимает ключ: создайте новый долгосрочный токен и вставьте его в «Каналы»."
                                  if exc.status in (401, 403) else f"amoCRM не ответил ({exc.status or 'нет связи'}). Повторим позже.")
            log.warning("amoCRM push for %s stopped: %s", business.slug, exc)
            break
        item.row.crm_id = str(deal_id)
        session.add(item.row)
        sent += 1
        if item.note:
            try:
                client.add_note(deal_id, item.note)
            except CrmError as exc:  # the deal is there; a lost note is not worth a second deal
                log.warning("amoCRM note for deal %s failed: %s", deal_id, exc)
    else:
        if sent and not skipped:
            business.crm_error = ""  # all went through: an old problem is over
    if sent or skipped:
        business.crm_synced_at = now_utc
    session.add(business)
    return {"sent": sent, "skipped": skipped} if sent or skipped else {}


def connected(business: Business) -> bool:
    return bool(base_url(business.crm_domain) and business.crm_token)

