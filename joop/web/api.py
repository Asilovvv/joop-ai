"""Panel page «API и вебхуки» and the read-only REST API under /api/v1 (joop/api.py has the rules).

The page is the owner's: make or revoke the key (shown once), set the webhook address and its secret, send a test.
The API answers only to `Authorization: Bearer <key>`; a wrong or missing key gets 401, too many calls 429.
"""

from __future__ import annotations

import secrets

from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Form, Request
from fastapi.responses import JSONResponse

from .. import api
from ..db import new_session
from ..dispatch import notify_admins
from ..timeutil import fmt_slot, local_now, utcnow
from .app import _back, _base_url, _business, _check_csrf, _flash, _render, _rt

router = APIRouter()


@router.get("/panel/api")
def api_page(request: Request):
    with new_session() as s:
        b = _business(s, request)
        waiting, lost = api.undelivered(s, b, utcnow())
        return _render(request, "api.html", "api", b, new_key="", new_secret="", base=_base_url(request), waiting=waiting, lost=lost)


@router.post("/panel/api")
def api_save(request: Request, action: str = Form(""), url: str = Form(""), csrf: str = Form("")):
    _check_csrf(request, csrf)
    with new_session() as s:
        b = _business(s, request)
        new_key = new_secret = ""
        if action == "new_key":
            new_key = api.new_key(b)  # replaces the old one at once
        elif action in ("booking_on", "booking_off"):
            b.api_booking = action == "booking_on"
            _flash(request, "Запись через API включена." if b.api_booking else "Запись через API выключена.")
        elif action == "revoke_key":
            b.api_key_hash, b.api_key_hint = "", ""
            _flash(request, "Ключ отозван: запросы с ним больше не проходят.")
        elif action == "save_webhook":
            problem = api.check_url(url)
            if problem:
                _flash(request, problem, "error")
                return _back("/panel/api")
            if url.strip() != b.webhook_url or not b.webhook_secret:
                b.webhook_since = utcnow()  # a new address gets events from now on, not the backlog
            b.webhook_url, b.webhook_error = url.strip(), ""
            if not b.webhook_secret:
                b.webhook_secret = new_secret = secrets.token_hex(24)
            else:
                _flash(request, "Адрес сохранён. События будут уходить туда в течение минуты.")
        elif action == "new_secret" and b.webhook_url:
            b.webhook_secret = new_secret = secrets.token_hex(24)
        elif action == "off_webhook":
            b.webhook_url, b.webhook_secret, b.webhook_error, b.webhook_since = "", "", "", None
            _flash(request, "Вебхуки выключены.")
        elif action == "test_webhook" and b.webhook_url and b.webhook_secret:
            ok, why = api.post(_rt(request).http, b, "test", {"message": "Joop: проверка вебхука"}, utcnow())
            _flash(request, "Тестовое событие доставлено." if ok else f"Адрес не принял тестовое событие: {why}.", "ok" if ok else "error")
        s.add(b)
        s.commit()
        s.refresh(b)
        if new_key or new_secret:  # shown on this page only, never stored in clear or put in the session
            page = _render(request, "api.html", "api", b, new_key=new_key, new_secret=new_secret, base=_base_url(request), waiting=0, lost=0)
            page.headers["Cache-Control"] = "no-store"  # not kept by the browser or a proxy
            return page
    return _back("/panel/api")


def _denied(status: int, text: str) -> JSONResponse:
    return JSONResponse({"error": text}, status_code=status, headers={"WWW-Authenticate": "Bearer"} if status == 401 else None)


def _key_business(s, request: Request):
    """(business, error response) for the Bearer key, with the rate limit."""
    header = request.headers.get("authorization", "")
    key = header[7:].strip() if header.lower().startswith("bearer ") else ""
    b = api.business_for_key(s, key) if key else None
    if b is None:
        return None, _denied(401, "invalid or missing API key")
    if not api.allow(b.api_key_hash):
        return None, JSONResponse({"error": "too many requests"}, status_code=429, headers={"Retry-After": "60"})
    return b, None


@router.get("/api/v1/slots")
def api_slots(request: Request, date: str = ""):
    """Free times to book into (only when booking through the API is on)."""
    with new_session() as s:
        b, refused = _key_business(s, request)
        if refused:
            return refused
        if not b.api_booking:
            return _denied(403, "booking through the API is off: turn it on in «API и вебхуки»")
        try:
            day = datetime.strptime(date, "%Y-%m-%d").date() if date else None
        except ValueError:
            return _denied(400, "date must be YYYY-MM-DD")
        data = api.free_slots(s, b, day, local_now(b.timezone).replace(tzinfo=None))
        return JSONResponse({"data": data, "timezone": b.timezone}, headers={"Cache-Control": "no-store"})


@router.post("/api/v1/bookings")
async def api_book(request: Request, background: BackgroundTasks):
    try:
        data = await request.json()
    except ValueError:
        data = None
    if not isinstance(data, dict):
        return _denied(400, "send JSON: {\"slot_id\", \"name\", \"phone\", \"service\"}")
    with new_session() as s:
        b, refused = _key_business(s, request)
        if refused:
            return refused
        done = api.book(s, b, data, local_now(b.timezone).replace(tzinfo=None), utcnow())
        if done.booking is None:
            return _denied(done.status, done.error)
        s.commit()
        s.refresh(done.booking)
        x = done.booking
        note = (f"Новая запись через API: {x.customer_name}, {x.customer_phone}"
                + (f", {x.service}" if x.service else "") + f" — {fmt_slot(x.start)}, {x.staff_name}.")
        background.add_task(notify_admins, _rt(request), b, [note])
        return JSONResponse({"data": api.booking_json(x)}, status_code=201, headers={"Cache-Control": "no-store"})


@router.get("/api/v1/{what}")
def api_list(request: Request, what: str, since: str = "", after_id: int = 0, offset: int = 0):
    if what not in ("bookings", "orders", "leads", "customers"):
        return _denied(404, "unknown resource")
    with new_session() as s:
        b, refused = _key_business(s, request)
        if refused:
            return refused
        if since and api._since(since) is None:
            return _denied(400, "since must be an ISO date-time, e.g. 2026-11-01T00:00:00Z")
        if what == "customers":
            data = api.customers_page(s, b, offset)
        else:
            data = api.rows(s, b, what, since, max(0, after_id))
        more = len(data) == api.PAGE
        return JSONResponse({"data": data, "has_more": more}, headers={"Cache-Control": "no-store"})
