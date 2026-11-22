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
import threading

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from sqlalchemy import func
from sqlmodel import Session, select

from .. import staff_reply, workers
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
_answering: dict[int, int] = {}  # business id -> web messages being answered now, not yet counted by the database
_lock = threading.Lock()  # the answers run in threads: a check and its count are one step, or a burst passes them all
PAUSED_REPLY = "Сообщение получено. Администратор ответит вам — оставьте, пожалуйста, номер телефона, если ещё не оставили."
LANGS = ("ru", "ky", "en", "zh")  # the page's languages; the AI answers in the language the guest writes in
TEXTS = {
    "limit": {"ru": "Сегодня сообщений уже много. Позвоните нам или напишите завтра.",
              "ky": "Бүгүн билдирүүлөр көп болуп кетти. Бизге чалыңыз же эртең жазыңыз.",
              "en": "Too many messages today. Please call us or write tomorrow.",
              "zh": "今天的消息太多了。请给我们打电话或明天再写。"},
    "busy": {"ru": "Чат сегодня перегружен. Позвоните нам, пожалуйста.",
             "ky": "Чат бүгүн жүктөлгөн. Сураныч, бизге чалыңыз.",
             "en": "The chat is busy today. Please call us.",
             "zh": "聊天今天很忙。请给我们打电话。"},
    "failed": {"ru": "Не получилось ответить. Попробуйте через минуту.",
               "ky": "Жооп берүү мүмкүн болгон жок. Бир мүнөттөн кийин кайра аракет кылыңыз.",
               "en": "Could not answer right now. Please try again in a minute.",
               "zh": "暂时无法回复。请一分钟后再试。"},
    "paused": {"ru": PAUSED_REPLY,
               "ky": "Билдирүү алынды. Администратор сизге жооп берет — телефон номериңизди калтырыңыз.",
               "en": "Message received. A staff member will reply — please leave your phone number if you have not yet.",
               "zh": "消息已收到。工作人员会回复您——如果还没有留下电话号码，请留下。"},
}


def _t(key: str, lang: str) -> str:
    return TEXTS[key].get(lang, TEXTS[key]["ru"])


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


def _take(limits: dict[str, int], day: str) -> bool:
    """Counts one message against every key, if none is at its limit."""
    with _lock:
        if any(_count(key, day) >= limit for key, limit in limits.items()):
            return False
        for key in limits:
            _bump(key, day)
        return True


def _give_back(keys, day: str) -> None:
    """A message that was not answered (refused, failed) does not count."""
    with _lock:
        for key in keys:
            d, n = _used.get(key, (day, 0))
            if d == day and n > 0:
                _used[key] = (day, n - 1)


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
            "request": request, "b": b, "embed": request.query_params.get("embed") == "1", "staff": _staff(request, b),
        })


def _staff(request: Request, business: Business) -> bool:
    """This browser is logged in to the business's panel: the owner or staff trying their own chat, not a customer.
    Read only: a visitor's request never gets a cookie. In an iframe on another site the cookie is not sent."""
    return request.scope.get("session", {}).get("bid") == business.id


@router.post("/c/{slug}/chat")
async def chat_message(request: Request, slug: str):
    try:
        data = await request.json()
    except ValueError:
        return JSONResponse({"error": "bad request"}, status_code=400)
    text = str(data.get("text", "")).strip()[:MAX_TEXT]
    visitor = str(data.get("visitor", ""))
    lang = str(data.get("lang", "ru")) if str(data.get("lang", "ru")) in LANGS else "ru"
    if not _TOKEN.match(visitor):
        visitor = secrets.token_hex(12)
    if not text:
        return JSONResponse({"error": "empty"}, status_code=400)
    day, ip = local_now(None).strftime("%Y-%m-%d"), client_ip(request)  # the day in Bishkek, not on the server clock
    limits = {f"v:{visitor}": PER_VISITOR, f"ip:{ip}": PER_ADDRESS}
    if not _take(limits, day):
        return JSONResponse({"error": _t("limit", lang), "visitor": visitor},
                            status_code=429)
    answered = False
    try:
        response = await workers.run(_answer, request, slug, text, visitor, lang, day, ip)
        answered = response.status_code == 200
        return response
    finally:
        if not answered:
            _give_back(limits, day)


def _answer(request: Request, slug: str, text: str, visitor: str, lang: str, day: str, ip: str) -> JSONResponse:
    """Everything that waits on the model, the database or Telegram. Runs in a worker thread: called straight from
    the async route, one visitor waiting for the model froze the whole server (three visitors at once: /health
    answered after 8.9 s, the third visitor after 9.2 s with a 3-second model)."""
    rt = _rt(request)
    with new_session() as s:
        try:
            business = _business(s, slug)
        except HTTPException:
            return JSONResponse({"error": "not found"}, status_code=404)
        with _lock:
            if _web_messages_today(s, business) + _answering.get(business.id, 0) >= PER_BUSINESS:
                return JSONResponse({"error": _t("busy", lang), "visitor": visitor},
                                    status_code=429)
            _answering[business.id] = _answering.get(business.id, 0) + 1
        chat_id = f"web-{visitor}"
        incoming = IncomingMessage(CHANNEL, chat_id, "text", text, "Посетитель сайта", f"web:{chat_id}:{secrets.token_hex(6)}",
                                   staff_test=_staff(request, business))
        try:
            outcome = handle_incoming(s, business, incoming, rt.get_llm, utcnow(), base_url=_settings(request).public_base_url,
                                      get_altegio=rt.altegio)
            s.commit()
        except Exception:
            s.rollback()
            log.exception("Web chat failed for %s", slug)
            return JSONResponse({"error": _t("failed", lang), "visitor": visitor}, status_code=503)
        finally:
            with _lock:
                _answering[business.id] -= 1
    if outcome.admin_notes:
        from ..dispatch import notify_admins

        try:
            notify_admins(rt, business, outcome.admin_notes)
        except Exception:
            log.exception("Staff notes for a web chat of %s were not sent", slug)
    if outcome.freed_slot_ids:  # the visitor cancelled or moved their booking: the time goes to the waiting list
        from ..dispatch import offer_freed

        try:
            offer_freed(rt, business, outcome.freed_slot_ids)
        except Exception:
            log.exception("A time freed in a web chat of %s was not offered to the waiting list", slug)
    reply = outcome.reply or (_t("paused", lang) if outcome.skipped in {"paused", "subscription"} else "")
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


PER_ADDRESS_POLLS = 20000  # /updates calls a day from one IP: the page asks every 15 s, so one visitor makes about 6,000


@router.get("/c/{slug}/updates")
def chat_updates(request: Request, slug: str, visitor: str = "", after: int = 0):
    """Replies staff wrote from the panel (joop/staff_reply.py); the page asks while it is open."""
    day, ip = local_now(None).strftime("%Y-%m-%d"), client_ip(request)  # the day in Bishkek, not on the server clock
    if not _TOKEN.match(visitor) or not _take({f"poll:{ip}": PER_ADDRESS_POLLS}, day):
        return JSONResponse({"messages": []}, headers={"Cache-Control": "no-store"})
    with new_session() as s:
        try:
            b = _business(s, slug)
        except HTTPException:
            return JSONResponse({"error": "not found"}, status_code=404)
        found = staff_reply.web_updates(s, b, f"web-{visitor}", max(0, after), utcnow())
        items = [{"id": m.id, "text": m.text} for m in found]
    return JSONResponse({"messages": items}, headers={"Cache-Control": "no-store"})


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
    _answering.clear()
