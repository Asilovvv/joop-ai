"""Joop's own API and webhooks: the business's data goes to 1C, Google Sheets, Make or n8n without anyone copying it.

amoCRM, Bitrix24 and Altéjo sell "интеграции и API: вебхуки и REST API для кастомных связок". Joop gives a business
the same two doors, both off until the owner opens them in «API и вебхуки»:

- a read-only REST API under /api/v1 — bookings, orders, requests and customers as JSON, with `since` for
  incremental pulls; one key per business, shown once and stored only as a hash, sent as `Authorization: Bearer`;
- webhooks — when the AI books, takes an order or a request, or staff record a payment, Joop POSTs the event to the
  owner's https address, signed with HMAC-SHA256 of the body (`X-Joop-Signature: sha256=…`), from the scheduler,
  retried for up to a day. The address must be https and resolve to a public host: an API that posts to a
  business's own server must not become a way to reach Joop's internal network.

Nothing here writes into Joop: the API reads, webhooks announce. The test chat stays out.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import secrets
import socket
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import httpx
from sqlmodel import Session, select

from .models import Booking, Business, Lead, Order, OrderLine, WebhookDelivery
from .stats import TEST_CHANNEL

KEY_PREFIX = "joop_"
LOOK_BACK = timedelta(days=3)  # events older than this are not sent when webhooks are switched on later
BATCH = 30  # webhook posts per scheduler tick
GIVE_UP = timedelta(hours=24)  # an event its address has refused this long is not sent any more
BUDGET = 15.0  # seconds of webhook sending per business per tick
TIMEOUT = httpx.Timeout(5.0, connect=3.0)
PAGE = 200  # API rows per call
RATE = 120  # API calls a minute per key
LEAD_KINDS = ("request", "lead", "handoff")  # what a customer asked for; media and error rows are Joop's own
_calls: dict[str, list[float]] = {}


# --- keys -------------------------------------------------------------------------------------------------


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def new_key(business: Business) -> str:
    """A fresh key; only its hash and last four characters are kept. The caller shows the key once."""
    key = KEY_PREFIX + secrets.token_urlsafe(32)
    business.api_key_hash, business.api_key_hint = _hash(key), key[-4:]
    return key


def business_for_key(session: Session, key: str) -> Business | None:
    if not key.startswith(KEY_PREFIX) or len(key) > 100:
        return None
    digest = _hash(key)
    b = session.exec(select(Business).where(Business.api_key_hash == digest)).first()
    return b if b is not None and hmac.compare_digest(b.api_key_hash, digest) else None


def allow(key_hash: str, now: float | None = None) -> bool:
    """At most RATE calls a minute per key."""
    now = now if now is not None else time.monotonic()
    recent = [t for t in _calls.get(key_hash, []) if now - t < 60]
    if len(recent) >= RATE:
        _calls[key_hash] = recent
        return False
    recent.append(now)
    _calls[key_hash] = recent
    if len(_calls) > 5000:
        _calls.clear()
    return True


# --- what the API and webhooks say ------------------------------------------------------------------------


def _iso(dt: datetime | None, utc: bool = True) -> str | None:
    if dt is None:
        return None
    return dt.isoformat(timespec="seconds") + ("Z" if utc else "")


def booking_json(b: Booking) -> dict:
    return {"id": b.id, "created_at": _iso(b.created_at), "start_local": _iso(b.start, utc=False), "service": b.service,
            "staff": b.staff_name, "customer": {"name": b.customer_name, "phone": b.customer_phone}, "channel": b.channel,
            "status": b.status, "source": b.source, "confirmed": b.confirmed_at is not None,
            "paid": {"som": b.paid_som, "method": b.paid_method, "at": _iso(b.paid_at)} if b.paid_som else None}


def order_json(session: Session, o: Order) -> dict:
    lines = session.exec(select(OrderLine).where(OrderLine.order_id == o.id).order_by(OrderLine.id)).all()
    return {"id": o.id, "created_at": _iso(o.created_at), "status": o.status, "mode": o.mode, "address": o.address,
            "wanted_time": o.wanted_time, "total": o.total, "delivery_fee": o.delivery_fee, "channel": o.channel,
            "customer": {"name": o.customer_name, "phone": o.customer_phone}, "comment": o.comment,
            "lines": [{"name": x.name, "quantity": x.quantity, "unit_price": x.unit_price, "note": x.note} for x in lines]}


def lead_json(x: Lead) -> dict:
    return {"id": x.id, "created_at": _iso(x.created_at), "kind": x.kind, "summary": x.summary, "details": x.details,
            "stage": x.stage, "status": x.status, "channel": x.channel, "customer": {"name": x.customer_name, "phone": x.customer_phone}}


def customer_json(c) -> dict:
    return {"key": c.key, "name": c.name, "phone": c.phone, "channels": sorted(c.channels), "visits": c.visits,
            "last_visit_local": _iso(c.last_visit, utc=False), "spend_som": c.spend_som, "last_contact": _iso(c.last_contact),
            "tags": [t.strip() for t in c.tags.split(",") if t.strip()], "note": c.note}


def customers_page(session: Session, business: Business, offset: int = 0) -> list[dict]:
    from .customers import listing

    return [customer_json(c) for c in listing(session, business)[max(0, offset):max(0, offset) + PAGE]]


def _since(value: str) -> datetime | None:
    """A naive UTC moment from ISO text; an offset such as +06:00 is honoured, no offset means UTC."""
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None
    except ValueError:
        return None
    if dt is not None and dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def rows(session: Session, business: Business, what: str, since: str = "", after_id: int = 0) -> list[dict]:
    """One page of bookings, orders or leads, oldest first, from `since` (UTC ISO) or after an id."""
    model = {"bookings": Booking, "orders": Order, "leads": Lead}[what]
    query = select(model).where(model.business_id == business.id, model.channel != TEST_CHANNEL, model.id > after_id)
    if model is Lead:
        query = query.where(Lead.kind.in_(LEAD_KINDS))
    start = _since(since)
    if start:
        query = query.where(model.created_at >= start)
    found = session.exec(query.order_by(model.id).limit(PAGE)).all()
    if what == "bookings":
        return [booking_json(b) for b in found]
    if what == "orders":
        return [order_json(session, o) for o in found]
    return [lead_json(x) for x in found]


# --- webhooks ---------------------------------------------------------------------------------------------


def _public_ip(host: str, port: int = 443) -> str:
    """The address to connect to when every address the host resolves to is public, else "".

    Loopback, private, link-local, reserved and multicast ranges are refused, IPv4-mapped IPv6 included.
    """
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError, OSError):
        return ""
    found = []
    for info in infos:
        a = ipaddress.ip_address(info[4][0].split("%")[0])
        plain = a.ipv4_mapped if a.version == 6 and a.ipv4_mapped else a
        if not plain.is_global or plain.is_multicast:
            return ""
        found.append(str(plain))
    return found[0] if found else ""


def _public_host(host: str) -> bool:
    return bool(_public_ip(host))


PORTS = (443, 8443)  # a webhook goes to a web server, not to whatever port a public host has open


def check_url(url: str) -> str:
    """"" when the webhook address is acceptable, else why not (in Russian, for the panel)."""
    url = url.strip()
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        return "Адрес должен начинаться с https://"
    if not url.isascii():
        # two libraries spell a non-Latin domain differently (IDNA 2003 vs 2008): the one checked could differ from the one called
        return "Укажите домен латиницей (для кириллического — в виде xn--…)."
    if parsed.username or parsed.password:
        return "Адрес без логина и пароля: подпись запроса — это и есть проверка."
    if len(url) > 500:
        return "Слишком длинный адрес."
    try:
        port = parsed.port or 443
    except ValueError:
        return "Неверный порт в адресе."
    if port not in PORTS:
        return "Порт может быть только 443 или 8443."
    if not _public_host(parsed.hostname):
        return "Этот адрес не открывается из интернета (или указывает во внутреннюю сеть)."
    return ""


def sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _events(session: Session, business: Business, now_utc: datetime) -> list[tuple[str, int, dict]]:
    """Events not yet delivered or given up on, oldest first across kinds, at most BATCH."""
    since = now_utc - LOOK_BACK
    if business.webhook_since and business.webhook_since > since:
        since = business.webhook_since  # nothing from before the owner switched webhooks on
    done = {(d.kind, d.object_id) for d in session.exec(select(WebhookDelivery).where(
        WebhookDelivery.business_id == business.id, WebhookDelivery.created_at >= since - LOOK_BACK)).all()
        if d.delivered_at or now_utc - d.created_at >= GIVE_UP}
    out: list[tuple[datetime, str, int, dict]] = []
    for b in session.exec(select(Booking).where(Booking.business_id == business.id, Booking.channel != TEST_CHANNEL,
                                                Booking.created_at >= since).order_by(Booking.id)).all():
        if ("booking.created", b.id) not in done:
            out.append((b.created_at, "booking.created", b.id, booking_json(b)))
    for b in session.exec(select(Booking).where(Booking.business_id == business.id, Booking.channel != TEST_CHANNEL,
                                                Booking.paid_at >= since, Booking.paid_som > 0).order_by(Booking.id)).all():
        if ("booking.paid", b.id) not in done:
            out.append((b.paid_at, "booking.paid", b.id, booking_json(b)))
    for o in session.exec(select(Order).where(Order.business_id == business.id, Order.channel != TEST_CHANNEL,
                                              Order.created_at >= since).order_by(Order.id)).all():
        if ("order.created", o.id) not in done:
            out.append((o.created_at, "order.created", o.id, order_json(session, o)))
    for x in session.exec(select(Lead).where(Lead.business_id == business.id, Lead.channel != TEST_CHANNEL, Lead.kind.in_(LEAD_KINDS),
                                             Lead.created_at >= since).order_by(Lead.id)).all():
        if ("lead.created", x.id) not in done:
            out.append((x.created_at, "lead.created", x.id, lead_json(x)))
    out.sort(key=lambda e: e[0])  # in the order things happened, so no kind starves another
    return [(kind, oid, data) for _, kind, oid, data in out[:BATCH]]


def post(http: httpx.Client, business: Business, event: str, data: dict, now_utc: datetime) -> tuple[bool, str]:
    body = json.dumps({"event": event, "business": business.slug, "sent_at": _iso(now_utc), "data": data},
                      ensure_ascii=False, separators=(",", ":")).encode()
    if check_url(business.webhook_url):  # checked again at send time: an address can start resolving inward later
        return False, "адрес указывает во внутреннюю сеть или не подходит"
    url = httpx.URL(business.webhook_url)
    host = url.raw_host.decode("ascii")
    ip = _public_ip(host, url.port or 443)
    if not ip:
        return False, "адрес указывает во внутреннюю сеть или не подходит"
    # connect to the address just checked, not to a second lookup: a DNS answer that changes between the check and
    # the connection (rebinding) cannot point the request inward. TLS still verifies the certificate of `host`;
    # the connection is not kept, so a pooled one to the same address never carries another host's events.
    pinned = url.copy_with(host=ip)
    try:
        r = http.post(pinned, content=body, timeout=TIMEOUT, follow_redirects=False, extensions={"sni_hostname": host}, headers={
            "Host": url.netloc.decode("ascii"), "Connection": "close", "Content-Type": "application/json", "User-Agent": "Joop-Webhooks/1",
            "X-Joop-Event": event, "X-Joop-Signature": sign(business.webhook_secret, body)})
    except httpx.HTTPError as exc:
        return False, type(exc).__name__
    return (200 <= r.status_code < 300), f"HTTP {r.status_code}"


def send_due(session: Session, http: httpx.Client, business: Business, now_utc: datetime) -> dict[str, int]:
    """Post due events in order; stop at the first failure (retried next tick) or when the time budget is spent.

    No database transaction is open while a request is in flight: a slow receiver must not hold SQLite's write
    lock for the whole scheduler.
    """
    if not (business.webhook_url and business.webhook_secret):
        return {}
    sent = failed = 0
    started = time.monotonic()
    due = _events(session, business, now_utc)
    for event, object_id, data in due:
        if time.monotonic() - started > BUDGET:
            break  # the rest next tick; other businesses are waiting for the scheduler
        session.commit()  # release the lock before going out to the network
        ok, why = post(http, business, event, data, now_utc)
        row = session.exec(select(WebhookDelivery).where(WebhookDelivery.business_id == business.id, WebhookDelivery.kind == event,
                                                         WebhookDelivery.object_id == object_id)).first()
        if row is None:
            row = WebhookDelivery(business_id=business.id, kind=event, object_id=object_id, created_at=now_utc)
        row.attempts += 1
        row.last_error = "" if ok else why[:200]
        if ok:
            row.delivered_at = now_utc
            sent += 1
        else:
            failed += 1
            business.webhook_error = f"{event}: {why}"[:200]
        session.add(row)
        session.add(business)
        session.commit()
        if not ok:
            break  # the address is down: try again next tick, in order
    if sent and not failed:
        business.webhook_error = ""
        session.add(business)
    return {"sent": sent, "failed": failed} if sent or failed else {}


def undelivered(session: Session, business: Business, now_utc: datetime) -> tuple[int, int]:
    """(waiting to be retried, given up) in the last LOOK_BACK, for the panel."""
    rows = session.exec(select(WebhookDelivery).where(WebhookDelivery.business_id == business.id, WebhookDelivery.delivered_at == None,  # noqa: E711
                                                      WebhookDelivery.created_at >= now_utc - LOOK_BACK)).all()
    lost = sum(1 for r in rows if now_utc - r.created_at >= GIVE_UP)
    return len(rows) - lost, lost
