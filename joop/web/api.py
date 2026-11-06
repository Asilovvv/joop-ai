"""Panel page «API и вебхуки» and the read-only REST API under /api/v1 (joop/api.py has the rules).

The page is the owner's: make or revoke the key (shown once), set the webhook address and its secret, send a test.
The API answers only to `Authorization: Bearer <key>`; a wrong or missing key gets 401, too many calls 429.
"""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Form, Request
from fastapi.responses import JSONResponse

from .. import api
from ..db import new_session
from ..timeutil import utcnow
from .app import _back, _base_url, _business, _check_csrf, _flash, _render, _rt

router = APIRouter()


@router.get("/panel/api")
def api_page(request: Request):
    with new_session() as s:
        b = _business(s, request)
        return _render(request, "api.html", "api", b, new_key="", new_secret="", base=_base_url(request))


@router.post("/panel/api")
def api_save(request: Request, action: str = Form(""), url: str = Form(""), csrf: str = Form("")):
    _check_csrf(request, csrf)
    with new_session() as s:
        b = _business(s, request)
        new_key = new_secret = ""
        if action == "new_key":
            new_key = api.new_key(b)  # replaces the old one at once
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
            return _render(request, "api.html", "api", b, new_key=new_key, new_secret=new_secret, base=_base_url(request))
    return _back("/panel/api")


def _denied(status: int, text: str) -> JSONResponse:
    return JSONResponse({"error": text}, status_code=status, headers={"WWW-Authenticate": "Bearer"} if status == 401 else None)


@router.get("/api/v1/{what}")
def api_list(request: Request, what: str, since: str = "", after_id: int = 0, offset: int = 0):
    if what not in ("bookings", "orders", "leads", "customers"):
        return _denied(404, "unknown resource")
    header = request.headers.get("authorization", "")
    key = header[7:].strip() if header.lower().startswith("bearer ") else ""
    with new_session() as s:
        b = api.business_for_key(s, key) if key else None
        if b is None:
            return _denied(401, "invalid or missing API key")
        if not api.allow(b.api_key_hash):
            return JSONResponse({"error": "too many requests"}, status_code=429, headers={"Retry-After": "60"})
        if since and api._since(since) is None:
            return _denied(400, "since must be an ISO date-time, e.g. 2026-11-01T00:00:00Z")
        if what == "customers":
            data = api.customers_page(s, b, offset)
        else:
            data = api.rows(s, b, what, since, max(0, after_id))
        more = len(data) == api.PAGE
        return JSONResponse({"data": data, "has_more": more}, headers={"Cache-Control": "no-store"})
