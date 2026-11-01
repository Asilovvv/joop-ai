"""Web chat: the business's own AI on a link and on any website.

- /c/<slug>             a chat page: the link for an Instagram bio, 2GIS, Google Maps or a QR code at the desk.
                        It works without Meta's app review, which Instagram Direct still needs.
- /c/<slug>/widget.js   one line on the business's website adds a chat button that opens the same page.
- /c/<slug>/chat        the page's API: the same engine as every other channel (channel "web").

The page talks only to its own origin, inside an iframe on other sites, so no cookies, CORS or CSRF are
involved: a visitor is a random token kept in the browser. Limits per visitor, per address and per
business keep a public link from running up the model bill.
"""

from __future__ import annotations

import json
import logging
import re
import secrets
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from sqlalchemy import func
from sqlmodel import Session, select

from ..agent.engine import handle_incoming
from ..channels.base import IncomingMessage
from ..db import new_session
from ..models import Business, Conversation, Message
from ..timeutil import local_now, local_to_utc, utcnow
from .app import _rt, _settings, client_ip, templates

log = logging.getLogger(__name__)
router = APIRouter()

CHANNEL = "web"
MAX_TEXT = 1000
PER_VISITOR = 40  # messages a day from one browser
PER_ADDRESS = 120  # a day from one IP: an office or a café shares one address
PER_BUSINESS = 600  # web messages a day for one business: a public link must not run up the bill
_TOKEN = re.compile(r"^[a-f0-9]{16,32}$")
_used: dict[str, tuple[str, int]] = {}  # key -> (day, count); reset with the process, the DB limit still holds
PAUSED_REPLY = "Сообщение получено. Администратор ответит вам — оставьте, пожалуйста, номер телефона, если ещё не оставили."


def _business(s: Session, slug: str) -> Business:
    b = s.exec(select(Business).where(Business.slug == slug)).first()
    if b is None or not b.bot_enabled or b.slug.startswith("site-demo-"):
        raise HTTPException(status_code=404)
    return b


def _count(key: str, day: str) -> int:
    d, n = _used.get(key, (day, 0))
    return n if d == day else 0


def _bump(key: str, day: str) -> None:
    _used[key] = (day, _count(key, day) + 1)


def _web_messages_today(s: Session, business: Business) -> int:
    start = local_to_utc(local_now(business.timezone).replace(hour=0, minute=0, second=0, microsecond=0), business.timezone)
    return int(s.exec(select(func.count()).select_from(Message).join(Conversation, Conversation.id == Message.conversation_id).where(
        Message.business_id == business.id, Message.role == "customer", Message.created_at >= start,
        Conversation.channel == CHANNEL)).one() or 0)


@router.get("/c/{slug}", response_class=HTMLResponse)
def chat_page(request: Request, slug: str):
    with new_session() as s:
        b = _business(s, slug)
        return templates.TemplateResponse(request, "webchat.html", {
            "request": request, "b": b, "embed": request.query_params.get("embed") == "1",
        })


@router.post("/c/{slug}/chat")
async def chat_message(request: Request, slug: str):
    try:
        data = await request.json()
    except ValueError:
        return JSONResponse({"error": "bad request"}, status_code=400)
    text = str(data.get("text", "")).strip()[:MAX_TEXT]
    visitor = str(data.get("visitor", ""))
    if not _TOKEN.match(visitor):
        visitor = secrets.token_hex(12)
    if not text:
        return JSONResponse({"error": "empty"}, status_code=400)
    day, ip = time.strftime("%Y-%m-%d"), client_ip(request)
    if _count(f"v:{visitor}", day) >= PER_VISITOR or _count(f"ip:{ip}", day) >= PER_ADDRESS:
        return JSONResponse({"error": "Сегодня сообщений уже много. Позвоните нам или напишите завтра.", "visitor": visitor},
                            status_code=429)
    rt = _rt(request)
    with new_session() as s:
        try:
            business = _business(s, slug)
        except HTTPException:
            return JSONResponse({"error": "not found"}, status_code=404)
        if _web_messages_today(s, business) >= PER_BUSINESS:
            return JSONResponse({"error": "Чат сегодня перегружен. Позвоните нам, пожалуйста.", "visitor": visitor},
                                status_code=429)
        chat_id = f"web-{visitor}"
        incoming = IncomingMessage(CHANNEL, chat_id, "text", text, "Посетитель сайта", f"web:{chat_id}:{secrets.token_hex(6)}")
        try:
            outcome = handle_incoming(s, business, incoming, rt.get_llm, utcnow(), base_url=_settings(request).public_base_url,
                                      get_altegio=rt.altegio)
            s.commit()
        except Exception:
            s.rollback()
            log.exception("Web chat failed for %s", slug)
            return JSONResponse({"error": "Не получилось ответить. Попробуйте через минуту.", "visitor": visitor}, status_code=503)
    _bump(f"v:{visitor}", day)
    _bump(f"ip:{ip}", day)
    if outcome.admin_notes:
        from ..dispatch import notify_admins

        try:
            notify_admins(rt, business, outcome.admin_notes)
        except Exception:
            log.exception("Staff notes for a web chat of %s were not sent", slug)
    reply = outcome.reply or (PAUSED_REPLY if outcome.skipped in {"paused", "subscription"} else "")
    return JSONResponse({"reply": reply, "visitor": visitor})


WIDGET_JS = """(function () {
  var base = %(base)s, slug = %(slug)s, title = %(title)s;
  if (window.__joopChat) return; window.__joopChat = true;
  var button = document.createElement('button');
  button.type = 'button';
  button.setAttribute('aria-label', title);
  button.textContent = 'Чат';
  button.style.cssText = 'position:fixed;right:20px;bottom:20px;z-index:2147483646;border:0;border-radius:28px;' +
    'padding:14px 22px;font:600 16px system-ui,sans-serif;color:#fff;background:#0e8a72;cursor:pointer;' +
    'box-shadow:0 6px 24px rgba(0,0,0,.25)';
  var frame = null;
  button.onclick = function () {
    if (!frame) {
      frame = document.createElement('iframe');
      frame.src = base + '/c/' + slug + '?embed=1';
      frame.title = title;
      frame.style.cssText = 'position:fixed;right:20px;bottom:84px;z-index:2147483647;border:0;border-radius:16px;' +
        'width:min(380px,calc(100vw - 40px));height:min(560px,calc(100vh - 120px));background:#fff;' +
        'box-shadow:0 12px 40px rgba(0,0,0,.3)';
      document.body.appendChild(frame);
    } else {
      frame.style.display = frame.style.display === 'none' ? 'block' : 'none';
    }
  };
  document.body.appendChild(button);
})();
"""


@router.get("/c/{slug}/widget.js")
def widget(request: Request, slug: str):
    with new_session() as s:
        b = _business(s, slug)
        name = b.name
    base = _settings(request).public_base_url or str(request.base_url).rstrip("/")
    js = WIDGET_JS % {"base": json.dumps(base), "slug": json.dumps(slug), "title": json.dumps(f"Чат: {name}")}
    return Response(js, media_type="application/javascript; charset=utf-8", headers={"Cache-Control": "public, max-age=300"})


def reset_limits() -> None:
    """For tests."""
    _used.clear()
