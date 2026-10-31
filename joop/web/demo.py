"""Live demo on the public site: a visitor writes to the real AI of a fictional business.

Five demo businesses (salon, clinic, cafe, school, hotel) are created on first use from the niche packs'
demo data, with slugs starting with DEMO_PREFIX. They have no subscription (so they never expire), no
staff chats (so nothing is sent anywhere) and are hidden from the founder console. Every visitor gets a
private conversation per demo business. Spending is bounded three ways: messages per visitor session,
messages per address, and messages per day for the whole site (SITE_DEMO_DAILY_LIMIT; 0 turns it off).
"""

from __future__ import annotations

import logging
import secrets
import time
from datetime import timedelta

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func
from sqlmodel import Session, select

from ..agent.engine import handle_incoming
from ..channels.base import IncomingMessage
from ..db import new_session
from ..models import Business, Conversation, Message, Staff
from ..niches import get_pack
from ..presets import create_business
from ..profile import load_profile
from ..slots import generate_slots
from ..timeutil import local_now, parse_hhmm, utcnow
from .app import _check_csrf, _rt, _settings, client_ip

log = logging.getLogger(__name__)
router = APIRouter()

DEMO_PREFIX = "site-demo-"
DEMOS = {  # key on the page -> (niche pack, shown name)
    "salon": ("beauty", "Салон «Айгерим» (демо)"),
    "clinic": ("dental", "Стоматология «Ак-Тиш» (демо)"),
    "cafe": ("restaurant", "Кафе «Ала-Тоо» (демо)"),
    "school": ("education", "Языковая школа (демо)"),
    "hotel": ("hotel", "Гостевой дом (демо)"),
}
PER_SESSION = 16  # visitor messages per browser session per day
PER_ADDRESS = 40  # per IP address per day: several people behind one office router
MAX_TEXT = 500
_by_address: dict[str, tuple[int, float]] = {}
_refreshed: dict[int, float] = {}


def is_demo(business: Business) -> bool:
    return business.slug.startswith(DEMO_PREFIX)


def demo_business(session: Session, key: str) -> Business:
    """The demo business for a page key, created on first use; its free slots are kept a week ahead."""
    niche, name = DEMOS[key]
    slug = DEMO_PREFIX + key
    business = session.exec(select(Business).where(Business.slug == slug)).first()
    if business is None:
        business = create_business(session, slug=slug, name=name, password=secrets.token_urlsafe(24), niche=niche,
                                   demo=True, now_utc=utcnow())
        session.commit()
    elif time.time() - _refreshed.get(business.id, 0) > 3600:
        _refresh_slots(session, business)
    _refreshed[business.id] = time.time()
    return business


def _refresh_slots(session: Session, business: Business) -> None:
    """Visitors book demo slots and days pass: add the week ahead again (existing times are skipped)."""
    plan = load_profile(get_pack(business.niche).demo_file).get("slots")
    if not isinstance(plan, dict):
        return
    start = parse_hhmm(str(plan.get("start") or business.work_start))
    end = parse_hhmm(str(plan.get("end") or business.work_end))
    today = local_now(business.timezone, utcnow()).date()
    for member in session.exec(select(Staff).where(Staff.business_id == business.id, Staff.active == True)).all():  # noqa: E712
        generate_slots(session, business, member.id, today + timedelta(days=1), today + timedelta(days=int(plan.get("days") or 7)),
                       start, end, int(plan.get("step") or 60))
    session.commit()


def _site_messages_today(session: Session) -> int:
    since = utcnow() - timedelta(days=1)
    return session.exec(
        select(func.count()).select_from(Message).join(Conversation, Message.conversation_id == Conversation.id)
        .where(Conversation.channel == "console", Conversation.chat_id.startswith("site-"), Message.role == "customer",
               Message.created_at >= since)
    ).one()


def _address_used(ip: str, now: float) -> int:
    count, first = _by_address.get(ip, (0, now))
    if now - first > 86400:
        _by_address.pop(ip, None)
        return 0
    return count


def _limit(text: str) -> JSONResponse:
    return JSONResponse({"error": text}, status_code=429)


@router.post("/demo/chat")
async def demo_chat(request: Request):
    limit = _settings(request).site_demo_daily_limit
    if limit <= 0:
        raise HTTPException(status_code=404)
    try:
        data = await request.json()
    except ValueError:
        raise HTTPException(status_code=400)
    _check_csrf(request, str(data.get("csrf", "")))
    key, text = str(data.get("key", "")), str(data.get("text", "")).strip()[:MAX_TEXT]
    if key not in DEMOS or not text:
        raise HTTPException(status_code=400)

    now_s, ip = time.time(), client_ip(request)
    day = time.strftime("%Y-%m-%d")
    if request.session.get("demo_day") != day:
        request.session["demo_day"], request.session["demo_used"] = day, 0
    if int(request.session.get("demo_used", 0)) >= PER_SESSION:
        return _limit("Демо-сообщения на сегодня закончились. Зарегистрируйтесь — в своей панели можно проверить ИИ на ваших ценах.")
    if _address_used(ip, now_s) >= PER_ADDRESS:
        return _limit("С этого адреса сегодня уже много сообщений. Попробуйте завтра или зарегистрируйтесь.")
    token = request.session.get("demo_chat") or secrets.token_hex(8)
    request.session["demo_chat"] = token

    with new_session() as s:
        if _site_messages_today(s) >= limit:
            return _limit("Демо сегодня очень популярно и лимит исчерпан. Попробуйте завтра или зарегистрируйтесь.")
        business = demo_business(s, key)
        chat_id = f"site-{key}-{token}"
        incoming = IncomingMessage("console", chat_id, "text", text, "Гость", f"console:{chat_id}:{secrets.token_hex(6)}")
        try:
            outcome = handle_incoming(s, business, incoming, _rt(request).get_llm)
            s.commit()
        except Exception:
            s.rollback()
            log.exception("Site demo failed for %s", key)
            return JSONResponse({"error": "ИИ сейчас недоступен. Попробуйте через минуту."}, status_code=503)

    request.session["demo_used"] = int(request.session.get("demo_used", 0)) + 1
    count, first = _by_address.get(ip, (0, now_s))
    _by_address[ip] = (count + 1, first)
    notes = [n.splitlines()[0] for n in outcome.admin_notes][:3]
    return JSONResponse({"reply": outcome.reply or "", "notes": notes,
                         "left": PER_SESSION - int(request.session["demo_used"])})


@router.post("/demo/reset")
async def demo_reset(request: Request):
    try:
        data = await request.json()
    except ValueError:
        raise HTTPException(status_code=400)
    _check_csrf(request, str(data.get("csrf", "")))
    request.session["demo_chat"] = secrets.token_hex(8)  # a fresh conversation; the old one stays for stats
    return JSONResponse({"ok": True})
