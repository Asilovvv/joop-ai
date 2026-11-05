"""FastAPI application: the business admin panel and the channel webhooks."""

from __future__ import annotations

import hmac
import json
import logging
import secrets
import time as time_module
from contextlib import asynccontextmanager
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlmodel import Session, select
from starlette.middleware.sessions import SessionMiddleware

from ..channels.meta import parse_meta_payload, verify_signature
from ..channels.telegram import parse_update
from ..config import Settings, get_settings
from ..db import init_db, new_session
from ..dispatch import admin_chat_ids, process_incoming
from ..catalog import parse_price
from ..models import (Booking, Business, Conversation, Faq, Lead, Message, Order, OrderLine, PanelUser, Service, SignatureClick, Slot,
                      Staff, WaitlistEntry)
from ..niches import all_packs, get_pack
from ..phone import normalize_phone
from .. import billing, cash, confirm, customers, deposits, free_plan, funnel, gaps, ig_comments, samples, staff_reply, waitlist
from ..faq_gaps import open_gaps
from ..runtime import Runtime
from ..scheduler import Scheduler
from ..security import hash_password, new_link_code, verify_password
from ..slots import add_slots, generate_slots, parse_times, release_slot, resize_group, seats_needed
from ..stats import activity, by_hour, hour_bars
from ..timeutil import WEEKDAYS_SHORT, fmt_date_long, fmt_dt, fmt_slot, local_now, parse_days_off, parse_hhmm, utc_to_local, utcnow

log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.filters["local"] = lambda dt, tz: fmt_dt(utc_to_local(dt, tz)) if dt else ""
templates.env.filters["slot"] = lambda dt: fmt_slot(dt) if dt else ""
templates.env.filters["dt"] = fmt_dt

def nav_for(business: Business | None) -> list[tuple[str, str, str]]:
    """Panel sections for this business's niche: a cafe gets orders, a wholesaler has no slots."""
    pack = get_pack(business.niche if business else None)
    books = pack.has("booking") or pack.has("request")
    items = [("/panel", "dashboard", "Сводка"), ("/panel/conversations", "conversations", "Диалоги"), ("/panel/customers", "customers", "Клиенты")]
    if pack.has("order"):
        items.append(("/panel/orders", "orders", "Заказы"))
    if books:
        items.append(("/panel/bookings", "bookings", "Записи"))
    if pack.has("booking"):
        items.append(("/panel/slots", "slots", "Окна"))
    if pack.has("stay"):
        items.append(("/panel/stays", "stays", "Брони номеров"))
    items.append(("/panel/leads", "leads", "Заявки"))
    items.append(("/panel/funnel", "funnel", "Воронка"))
    if pack.has("booking"):
        items.append(("/panel/cash", "cash", "Касса"))
    if pack.offers("level_test"):
        items.append(("/panel/tests", "tests", "Тест на уровень"))
    items.append(("/panel/services", "services", pack.catalog_label))
    items.append(("/panel/menu", "menu", "QR-меню" if pack.has("order") else "Прайс онлайн"))
    if books:
        items.append(("/panel/followups", "followups", "Отзывы и возврат"))
    if pack.has("booking"):
        items.append(("/panel/gaps", "gaps", "Пустые окна"))
    items.append(("/panel/card", "card", "Табличка на стойку"))
    items.append(("/panel/broadcasts", "broadcasts", "Рассылки"))
    if pack.offers("memberships"):
        items.append(("/panel/memberships", "memberships", "Абонементы"))
    if pack.offers("jobs"):
        items.append(("/panel/jobs", "jobs", "Заказы в работе"))
    if books or pack.has("stay"):
        items.append(("/panel/staff", "staff", pack.resource_label))
    items += [("/panel/faq", "faq", "Вопросы"), ("/panel/settings", "settings", "Настройки"), ("/panel/channels", "channels", "Каналы"),
              ("/panel/accounts", "accounts", "Доступ сотрудников")]
    items[1:1] = [("/panel/setup", "setup", "Запуск"), ("/panel/try", "try", "Проверить ИИ")]
    items.append(("/panel/billing", "billing", "Оплата"))
    return items
NAV_GROUPS = (
    ("Работа", {"dashboard", "conversations", "customers", "orders", "bookings", "stays", "leads", "funnel", "cash", "jobs"}),
    ("Инструменты", {"slots", "tests", "menu", "followups", "gaps", "broadcasts", "memberships", "card"}),
    ("Настройка", {"setup", "try", "services", "staff", "faq", "settings", "channels", "accounts", "billing"}),
)


def nav_groups(items: list[tuple[str, str, str]]) -> list[tuple[str, list[tuple[str, str, str]]]]:
    """The same sections, grouped for the sidebar; order inside a group follows nav_for."""
    groups = [(title, [i for i in items if i[1] in keys]) for title, keys in NAV_GROUPS]
    known = set().union(*(keys for _, keys in NAV_GROUPS))
    rest = [i for i in items if i[1] not in known]
    if rest:
        groups[-1][1].extend(rest)
    return [(t, g) for t, g in groups if g]


TIMEZONES = ["Asia/Bishkek", "Asia/Almaty", "Asia/Tashkent", "Asia/Dushanbe", "Europe/Moscow"]
CHANNEL_NAMES = {"telegram": "Telegram", "whatsapp": "WhatsApp", "instagram": "Instagram", "web": "Чат на сайте", "console": "Тест"}

router = APIRouter()


class LoginRequired(Exception):
    pass


# --- helpers -----------------------------------------------------------------------------------


def _rt(request: Request) -> Runtime:
    return request.app.state.rt


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _csrf(request: Request) -> str:
    token = request.session.get("csrf")
    if not token:
        token = secrets.token_urlsafe(24)
        request.session["csrf"] = token
    return token


def _check_csrf(request: Request, token: str) -> None:
    expected = request.session.get("csrf", "")
    if not token or not expected or not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=403, detail="Форма устарела. Обновите страницу и повторите.")


def _flash(request: Request, text: str, kind: str = "ok") -> None:
    items = list(request.session.get("flash", []))
    items.append([kind, text])
    request.session["flash"] = items


def _bid(request: Request) -> int:
    bid = request.session.get("bid")
    if not isinstance(bid, int):
        raise LoginRequired
    return bid


# Panel sections only the owner (the company password) opens; staff logins (PanelUser) do the daily work.
OWNER_ONLY = ("/panel/settings", "/panel/channels", "/panel/altegio", "/panel/crm", "/panel/setup", "/panel/billing",
              "/panel/accounts", "/panel/broadcasts", "/panel/example")
OWNER_NAV = {"settings", "channels", "setup", "billing", "accounts", "broadcasts"}


def _business(s: Session, request: Request) -> Business:
    business = s.get(Business, _bid(request))
    if business is None:
        request.session.clear()
        raise LoginRequired
    uid = request.session.get("uid")
    if uid is not None:  # a staff login: still active, and only the daily-work sections
        user = s.get(PanelUser, uid)
        if user is None or not user.active or user.business_id != business.id \
                or request.session.get("pw") != user.password_hash[-16:]:  # a new password ends old sessions
            request.session.clear()
            raise LoginRequired
        if request.url.path.startswith(OWNER_ONLY):
            raise HTTPException(status_code=403, detail="Этот раздел открывает только владелец: войдите паролем компании.")
    return business


def _is_owner(request: Request) -> bool:
    return request.session.get("uid") is None


def _who(request: Request) -> str:
    """The name shown next to what this person did: a staff login's name, or "Владелец"."""
    return str(request.session.get("who") or "Владелец")


def _own(s: Session, model: Any, obj_id: int, business_id: int) -> Any:
    obj = s.get(model, obj_id)
    if obj is None or obj.business_id != business_id:
        raise HTTPException(status_code=404)
    return obj


def _nav(request: Request, business: Business | None) -> list[tuple[str, str, str]]:
    items = nav_for(business)
    return items if _is_owner(request) else [i for i in items if i[1] not in OWNER_NAV]


SUPPORT_DAYS = 30


def _support(request: Request, business: Business | None) -> dict | None:
    """The founder's own contacts, shown in the panel during a business's first month: a named person who
    answers within an hour beats a help page (the strategy's "support is the product")."""
    s = _settings(request)
    if business is None or not (s.contact_phone or s.contact_telegram):
        return None
    if business.created_at and (utcnow() - business.created_at).days > SUPPORT_DAYS:
        return None
    return {"phone": s.contact_phone, "telegram": s.contact_telegram,
            "wa": "".join(ch for ch in s.contact_phone if ch.isdigit())}


def _render(request: Request, template: str, active: str, business: Business | None = None, **ctx: Any):
    ctx.update(
        request=request,
        business=business,
        csrf=_csrf(request),
        flashes=request.session.pop("flash", []),
        nav=_nav(request, business),
        nav_groups=nav_groups(_nav(request, business)),
        who=_who(request) if request.session.get("bid") else "",
        owner=_is_owner(request),
        support=_support(request, business),
        pack=get_pack(business.niche if business else None),
        active=active,
    )
    return templates.TemplateResponse(request, template, ctx)


def _base_url(request: Request) -> str:
    """Public address for links sent to customers: PUBLIC_BASE_URL, else the address this request came to."""
    return _settings(request).public_base_url or str(request.base_url).rstrip("/")


def _back(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def _parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat((value or "").strip())
    except ValueError:
        return None


def _now_local(business: Business) -> datetime:
    return utc_to_local(utcnow(), business.timezone)


# --- auth ----------------------------------------------------------------------------------------


@router.get("/health")
def health():
    return {"ok": True}


def _site(request: Request, template: str, **ctx: Any):
    s = _settings(request)
    ctx.update(
        request=request,
        legal_name=s.company_legal_name,
        email=s.contact_email,
        phone=s.contact_phone,
        telegram=s.contact_telegram,
        updated=ctx.pop("updated", "29.10.2026"),
    )
    return templates.TemplateResponse(request, template, ctx)


_daily: dict[str, tuple[str, int]] = {}  # small in-memory counters keyed by day: signature clicks per address, comment openings
SIGNATURE_PER_ADDRESS = 20  # clicks a day counted from one address: a loop must not inflate the master's number
PREVIEW_AGENTS = ("TelegramBot", "WhatsApp", "facebookexternalhit", "Twitterbot", "Slackbot", "LinkedInBot")


def daily_count(key: str, day: str) -> int:
    d, n = _daily.get(key, (day, 0))
    return n if d == day else 0


def daily_bump(key: str, day: str) -> None:
    if len(_daily) > 20000:
        _daily.clear()
    _daily[key] = (day, daily_count(key, day) + 1)


@router.get("/sw.js")
def service_worker():
    """The service worker must live at the root so its scope covers /panel; the file itself sits in static/pwa."""
    return FileResponse(BASE_DIR / "static" / "pwa" / "sw.js", media_type="application/javascript", headers={"Cache-Control": "no-cache"})


@router.get("/offline")
def offline_page(request: Request):
    return templates.TemplateResponse(request, "offline.html", {"request": request})


@router.get("/ai/{slug}")
def from_signature(request: Request, slug: str):
    """The link in a free business's AI signature: count the visit (once per browser a day, not for link-preview
    crawlers, at most a few per address), remember where it came from, show the site."""
    day = local_now(None).strftime("%Y-%m-%d")
    agent = request.headers.get("user-agent", "")
    crawler = any(x.lower() in agent.lower() for x in PREVIEW_AGENTS)
    seen = request.session.get("from_ai") == slug and request.session.get("from_ai_day") == day
    with new_session() as s:
        b = s.exec(select(Business).where(Business.slug == slug)).first()
        if b is not None and not crawler:
            ip = client_ip(request)
            if not seen and daily_count(f"ai:{ip}", day) < SIGNATURE_PER_ADDRESS:
                daily_bump(f"ai:{ip}", day)
                s.add(SignatureClick(business_id=b.id))
                s.commit()
            request.session["from_ai"], request.session["from_ai_day"] = slug, day
    return RedirectResponse("/", status_code=303)


@router.get("/")
def landing(request: Request):
    s = _settings(request)
    packs = {k: p for k, p in all_packs().items() if k != "other"}
    return _site(request, "site_home.html", packs=packs, price=s.price_som, trial_days=s.trial_days, signup=s.signup_enabled,
                 live_demo=s.site_demo_daily_limit > 0 and bool(s.anthropic_api_key), csrf=_csrf(request))


@router.get("/privacy")
def privacy(request: Request):
    return _site(request, "site_privacy.html", updated="05.11.2026")


@router.get("/data-deletion")
def data_deletion(request: Request):
    return _site(request, "site_deletion.html")


@router.get("/login")
def login_form(request: Request):
    return _render(request, "login.html", "login")


# Failed logins: (count, first failure time) per "name|address" and per "name|*". In memory: one process
# serves the panel. Keyed by address too, so a stranger cannot lock a company out by mistyping its login.
LOGIN_MAX_FAILS = 5
LOGIN_LOCK_SECONDS = 15 * 60
_login_fails: dict[str, tuple[int, float]] = {}


def _login_locked(key: str, now: float) -> bool:
    count, first = _login_fails.get(key, (0, now))
    if now - first > LOGIN_LOCK_SECONDS:
        _login_fails.pop(key, None)
        return False
    return count >= LOGIN_MAX_FAILS


def _login_failed(key: str, now: float) -> None:
    count, first = _login_fails.get(key, (0, now))
    if now - first > LOGIN_LOCK_SECONDS:
        count, first = 0, now
    _login_fails[key] = (count + 1, first)


LOGIN_MAX_FAILS_PER_NAME = 50  # from all addresses together: bounds guessing spread over many addresses


def client_ip(request: Request) -> str:
    """The visitor's address. Behind Caddy it is the last X-Forwarded-For entry (added by Caddy itself)."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else ""


def throttled(name: str, request: Request, now: float) -> bool:
    """Too many failures for this name from this address, or for this name overall."""
    count, first = _login_fails.get(f"{name}|*", (0, now))
    if now - first <= LOGIN_LOCK_SECONDS and count >= LOGIN_MAX_FAILS_PER_NAME:
        return True
    return _login_locked(f"{name}|{client_ip(request)}", now)


def record_failure(name: str, request: Request, now: float) -> None:
    _login_failed(f"{name}|{client_ip(request)}", now)
    _login_failed(f"{name}|*", now)


def _by_phone(s: Session, text: str) -> Business | None:
    """An owner who forgot the generated login can type the phone from sign-up; only a phone of exactly one company."""
    phone = normalize_phone(text)
    if not phone:
        return None
    found = [b for b in s.exec(select(Business).where(Business.phone != "")).all() if normalize_phone(b.phone) == phone]
    return found[0] if len(found) == 1 else None


@router.post("/login")
def login(request: Request, slug: str = Form(""), password: str = Form(""), user: str = Form(""), csrf: str = Form("")):
    """The company password logs in the owner; a staff member adds their own login (PanelUser)."""
    _check_csrf(request, csrf)
    company, person, now = slug.strip().lower(), user.strip().lower(), time_module.time()
    key = f"{company}/{person}" if person else company
    if throttled(key, request, now):
        _flash(request, "Слишком много неудачных попыток. Попробуйте через 15 минут.", "error")
        return _back("/login")
    with new_session() as s:
        business = s.exec(select(Business).where(Business.slug == company)).first() or _by_phone(s, company)
        account = None
        if business is not None and person:
            account = s.exec(select(PanelUser).where(PanelUser.business_id == business.id, PanelUser.login == person,
                                                     PanelUser.active == True)).first()  # noqa: E712
            ok = account is not None and verify_password(password, account.password_hash)
        else:
            ok = business is not None and verify_password(password, business.admin_password_hash)
        if not ok:
            record_failure(key, request, now)
            _flash(request, "Неверный логин или пароль.", "error")
            return _back("/login")
        _login_fails.pop(f"{key}|{client_ip(request)}", None)
        request.session.clear()
        request.session["bid"] = business.id
        if account is not None:
            request.session["uid"], request.session["who"] = account.id, account.name
            request.session["pw"] = account.password_hash[-16:]
            account.last_login_at = utcnow()
            s.add(account)
            s.commit()
    return _back("/panel")


@router.post("/logout")
def logout(request: Request, csrf: str = Form("")):
    _check_csrf(request, csrf)
    request.session.clear()
    return _back("/login")


# --- dashboard -------------------------------------------------------------------------------------


@router.post("/panel/example/ok")
def example_ok(request: Request, csrf: str = Form("")):
    """The owner checked: the rows that still equal the sign-up example are the business's real prices and answers."""
    _check_csrf(request, csrf)
    with new_session() as s:
        b = _business(s, request)
        b.example_ok = True
        s.add(b)
        s.commit()
    _flash(request, "Готово: эти данные считаются вашими, предупреждение больше не показывается.")
    return _back("/panel")


@router.get("/panel")
def dashboard(request: Request):
    with new_session() as s:
        b = _business(s, request)
        now = utcnow()
        now_local = _now_local(b)
        upcoming = s.exec(
            select(Booking)
            .where(Booking.business_id == b.id, Booking.status == "booked", Booking.start >= now_local - timedelta(hours=1))
            .order_by(Booking.start)
            .limit(10)
        ).all()
        leads = s.exec(
            select(Lead).where(Lead.business_id == b.id, Lead.status == "new").order_by(Lead.id.desc()).limit(10)
        ).all()
        counts = {
            "services": s.exec(select(func.count()).select_from(Service).where(Service.business_id == b.id)).one(),
            "staff": s.exec(
                select(func.count()).select_from(Staff).where(Staff.business_id == b.id, Staff.active == True)  # noqa: E712
            ).one(),
            "free_slots": s.exec(
                select(func.count()).select_from(Slot).where(
                    Slot.business_id == b.id, Slot.status == "free", Slot.start > now_local
                )
            ).one(),
        }
        example = samples.left(s, b)
        return _render(
            request,
            "dashboard.html",
            "dashboard",
            b,
            s14=activity(s, b.id, now - timedelta(days=14)),
            s1=activity(s, b.id, now - timedelta(hours=24)),
            hours=(hours := by_hour(s, b.id, now - timedelta(days=14), b.timezone)),
            hour_bars=hour_bars(hours),
            upcoming=upcoming,
            leads=leads,
            counts=counts,
            example=example,
            admins=len(admin_chat_ids(b)),
            channels=[
                ("Telegram", bool(b.telegram_bot_token)),
                ("WhatsApp", bool(b.wa_phone_number_id and b.wa_access_token)),
                ("Instagram", bool(b.ig_account_id and b.ig_access_token)),
            ],
            channel_names=CHANNEL_NAMES,
        )


# --- price list, staff, FAQ --------------------------------------------------------------------------


@router.get("/panel/services")
def services_page(request: Request):
    with new_session() as s:
        b = _business(s, request)
        rows = s.exec(select(Service).where(Service.business_id == b.id).order_by(Service.sort, Service.id)).all()
        return _render(request, "services.html", "services", b, rows=rows)


@router.post("/panel/services")
def service_add(
    request: Request, name: str = Form(""), name_ky: str = Form(""), price: str = Form(""), note: str = Form(""), csrf: str = Form("")
):
    _check_csrf(request, csrf)
    with new_session() as s:
        b = _business(s, request)
        if name.strip():
            last = s.exec(select(func.max(Service.sort)).where(Service.business_id == b.id)).one() or 0
            s.add(Service(business_id=b.id, name=name.strip(), name_ky=name_ky.strip(), price=price.strip(),
                          price_value=parse_price(price), note=note.strip(), sort=last + 1))
            s.commit()
            _flash(request, "Услуга добавлена.")
    return _back("/panel/services")


@router.post("/panel/services/upsell")
async def services_upsell(request: Request):
    """Per service, the add-on the AI offers right after a booking (joop/upsell.py)."""
    form = await request.form()
    _check_csrf(request, str(form.get("csrf", "")))
    with new_session() as s:
        b = _business(s, request)
        services = s.exec(select(Service).where(Service.business_id == b.id)).all()
        priced = {sv.id for sv in services if sv.price_value}
        for sv in services:
            key = f"upsell_{sv.id}"
            if key not in form:
                continue
            try:
                chosen = int(str(form.get(key) or 0))
            except ValueError:
                chosen = 0
            sv.upsell_id = chosen if chosen in priced and chosen != sv.id else 0
            s.add(sv)
        s.commit()
    _flash(request, "Сохранено. После записи ИИ предложит выбранную услугу одной строкой.")
    return _back("/panel/services")


@router.post("/panel/services/{item_id}")
def service_update(
    request: Request,
    item_id: int,
    name: str = Form(""),
    name_ky: str = Form(""),
    price: str = Form(""),
    note: str = Form(""),
    available: str = Form(""),
    csrf: str = Form(""),
):
    _check_csrf(request, csrf)
    with new_session() as s:
        b = _business(s, request)
        row = _own(s, Service, item_id, b.id)
        if name.strip():
            row.name, row.name_ky, row.price, row.note = name.strip(), name_ky.strip(), price.strip(), note.strip()
            row.price_value = parse_price(row.price)
            row.available = bool(available)
            s.add(row)
            s.commit()
            _flash(request, "Сохранено.")
    return _back("/panel/services")


@router.post("/panel/services/{item_id}/delete")
def service_delete(request: Request, item_id: int, csrf: str = Form("")):
    _check_csrf(request, csrf)
    with new_session() as s:
        b = _business(s, request)
        s.delete(_own(s, Service, item_id, b.id))
        s.commit()
        _flash(request, "Услуга удалена.")
    return _back("/panel/services")


@router.get("/panel/staff")
def staff_page(request: Request):
    with new_session() as s:
        b = _business(s, request)
        rows = s.exec(select(Staff).where(Staff.business_id == b.id, Staff.active == True).order_by(Staff.id)).all()  # noqa: E712
        return _render(request, "staff.html", "staff", b, rows=rows)


@router.post("/panel/staff")
def staff_add(
    request: Request, name: str = Form(""), role: str = Form(""), handles: str = Form(""), capacity: int = Form(0),
    group_size: int = Form(0), csrf: str = Form("")
):
    _check_csrf(request, csrf)
    with new_session() as s:
        b = _business(s, request)
        if name.strip() and free_plan.is_free(billing.get_subscription(s, b.id)) and len(free_plan.active_staff(s, b.id)) >= free_plan.MAX_STAFF:
            _flash(request, free_plan.TOO_MANY, "error")  # the free plan is for one master
            return _back("/panel/staff")
        if name.strip():
            s.add(Staff(business_id=b.id, name=name.strip(), role=role.strip(), handles=handles.strip(), capacity=max(0, capacity),
                        group_size=max(0, min(group_size, 500))))
            s.commit()
            _flash(request, "Специалист добавлен. Теперь создайте для него окна записи.")
    return _back("/panel/staff")


@router.post("/panel/staff/{item_id}")
def staff_update(
    request: Request, item_id: int, name: str = Form(""), role: str = Form(""), handles: str = Form(""), capacity: int = Form(0),
    group_size: int = Form(0), csrf: str = Form("")
):
    _check_csrf(request, csrf)
    with new_session() as s:
        b = _business(s, request)
        row = _own(s, Staff, item_id, b.id)
        if name.strip():
            row.name, row.role, row.handles = name.strip(), role.strip(), handles.strip()
            row.capacity = max(0, capacity)
            group_size = max(0, min(group_size, 500))
            if group_size != row.group_size:
                row.group_size = group_size
                resize_group(s, row.id, group_size, _now_local(b))
            s.add(row)
            s.commit()
            _flash(request, "Сохранено.")
    return _back("/panel/staff")


@router.post("/panel/staff/{item_id}/delete")
def staff_delete(request: Request, item_id: int, csrf: str = Form("")):
    _check_csrf(request, csrf)
    with new_session() as s:
        b = _business(s, request)
        row = _own(s, Staff, item_id, b.id)
        row.active = False  # kept for booking history
        s.add(row)
        for slot in s.exec(select(Slot).where(Slot.staff_id == row.id, Slot.status == "free", Slot.taken == 0)).all():
            s.delete(slot)
        s.commit()
        _flash(request, "Специалист убран, его свободные окна удалены. Существующие записи остались.")
    return _back("/panel/staff")


@router.get("/panel/faq")
def faq_page(request: Request):
    with new_session() as s:
        b = _business(s, request)
        rows = s.exec(select(Faq).where(Faq.business_id == b.id).order_by(Faq.id)).all()
        gaps = open_gaps(s, b, utcnow())
        return _render(request, "faq.html", "faq", b, rows=rows, gaps=gaps)


@router.post("/panel/faq")
def faq_add(request: Request, question: str = Form(""), question_ky: str = Form(""), answer: str = Form(""),
            lead_id: int = Form(0), csrf: str = Form("")):
    _check_csrf(request, csrf)
    with new_session() as s:
        b = _business(s, request)
        if question.strip() and answer.strip():
            lead = s.get(Lead, lead_id) if lead_id else None
            source = lead.id if lead is not None and lead.business_id == b.id else None
            s.add(Faq(business_id=b.id, question=question.strip(), question_ky=question_ky.strip()[:300], answer=answer.strip(),
                      source_lead_id=source))
            s.commit()
            _flash(request, "Вопрос добавлен.")
    return _back("/panel/faq")


@router.post("/panel/faq/{item_id}")
def faq_update(request: Request, item_id: int, question: str = Form(""), question_ky: str = Form(""), answer: str = Form(""),
               csrf: str = Form("")):
    _check_csrf(request, csrf)
    with new_session() as s:
        b = _business(s, request)
        row = _own(s, Faq, item_id, b.id)
        if question.strip() and answer.strip():
            row.question, row.question_ky, row.answer = question.strip(), question_ky.strip()[:300], answer.strip()
            s.add(row)
            s.commit()
            _flash(request, "Сохранено.")
    return _back("/panel/faq")


KY_FILLS_PER_DAY = 10
_ky_fills: dict[int, list[float]] = {}


@router.post("/panel/kyrgyz/fill")
def kyrgyz_fill(request: Request, back: str = Form("services"), csrf: str = Form("")):
    """The AI fills empty Kyrgyz names and questions; the owner checks them on the page."""
    from .. import kyrgyz

    _check_csrf(request, csrf)
    target = "/panel/faq" if back == "faq" else "/panel/services"
    now_s = time_module.time()
    with new_session() as s:
        b = _business(s, request)
        recent = [t for t in _ky_fills.get(b.id, []) if now_s - t < 86400]
        if len(recent) >= KY_FILLS_PER_DAY:
            _flash(request, "Автозаполнение можно запускать до 10 раз в сутки. Остальное заполните вручную.", "error")
            return _back(target)
        _ky_fills[b.id] = recent + [now_s]
        result = kyrgyz.fill_missing(s, b, _rt(request).get_llm())
        s.commit()
    if result.failed:
        _flash(request, "ИИ сейчас не смог предложить перевод. Попробуйте через минуту.", "error")
    elif result.filled == 0 and result.skipped == 0:
        _flash(request, "Все кыргызские поля уже заполнены.")
    else:
        text = f"ИИ заполнил кыргызских вариантов: {result.filled}. Проверьте их и исправьте, если что-то звучит не так."
        if result.skipped:
            text += f" Не получилось: {result.skipped} — заполните вручную."
        if result.left:
            text += f" Осталось ещё {result.left} — нажмите кнопку снова."
        _flash(request, text)
    return _back(target)


@router.post("/panel/faq/{item_id}/delete")
def faq_delete(request: Request, item_id: int, csrf: str = Form("")):
    _check_csrf(request, csrf)
    with new_session() as s:
        b = _business(s, request)
        s.delete(_own(s, Faq, item_id, b.id))
        s.commit()
        _flash(request, "Вопрос удалён.")
    return _back("/panel/faq")


# --- slots and bookings ------------------------------------------------------------------------------


@router.get("/panel/slots")
def slots_page(request: Request):
    with new_session() as s:
        b = _business(s, request)
        now_local = _now_local(b)
        staff = s.exec(select(Staff).where(Staff.business_id == b.id, Staff.active == True).order_by(Staff.id)).all()  # noqa: E712
        names = {m.id: m.name for m in staff}
        rows = s.exec(
            select(Slot)
            .where(Slot.business_id == b.id, Slot.start >= now_local.replace(hour=0, minute=0, second=0, microsecond=0), Slot.start < now_local + timedelta(days=21))
            .order_by(Slot.start, Slot.staff_id)
        ).all()
        booked = {
            bk.slot_id: bk
            for bk in s.exec(
                select(Booking).where(Booking.business_id == b.id, Booking.status == "booked", Booking.slot_id.in_([r.id for r in rows] or [0]))
            ).all()
        }
        # day label -> staff name -> [(slot, booking)]; dicts keep insertion order (sorted by time)
        grouped: dict[str, dict[str, list]] = {}
        for slot in rows:
            if slot.staff_id not in names:
                continue
            per_day = grouped.setdefault(fmt_date_long(slot.start), {})
            per_day.setdefault(names[slot.staff_id], []).append((slot, booked.get(slot.id)))
        days = [(label, sorted(per_staff.items())) for label, per_staff in grouped.items()]
        today = now_local.date()
        return _render(
            request,
            "slots.html",
            "slots",
            b,
            staff=staff,
            days=days,
            today=today.isoformat(),
            week=(today + timedelta(days=7)).isoformat(),
            work_start=b.work_start,
            work_end=b.work_end,
        )


@router.post("/panel/slots/add")
def slots_add(request: Request, staff_id: int = Form(...), day: str = Form(""), times: str = Form(""), csrf: str = Form("")):
    _check_csrf(request, csrf)
    with new_session() as s:
        b = _business(s, request)
        _own(s, Staff, staff_id, b.id)
        parsed_day, parsed_times = _parse_date(day), parse_times(times)
        if parsed_day is None or not parsed_times:
            _flash(request, "Укажите дату и время, например: 10:00, 11:30, 15:00.", "error")
            return _back("/panel/slots")
        created = add_slots(s, b, staff_id, parsed_day, parsed_times)
        s.commit()
        _flash(request, f"Добавлено окон: {created}.")
    return _back("/panel/slots")


@router.post("/panel/slots/generate")
def slots_generate(
    request: Request,
    staff_id: int = Form(...),
    date_from: str = Form(""),
    date_to: str = Form(""),
    start: str = Form("09:00"),
    end: str = Form("18:00"),
    step: int = Form(60),
    csrf: str = Form(""),
):
    _check_csrf(request, csrf)
    with new_session() as s:
        b = _business(s, request)
        _own(s, Staff, staff_id, b.id)
        d_from, d_to = _parse_date(date_from), _parse_date(date_to)
        t_start, t_end = parse_hhmm(start), parse_hhmm(end)
        if not (d_from and d_to and t_start and t_end) or d_to < d_from or t_end <= t_start:
            _flash(request, "Проверьте даты и часы: конец должен быть позже начала.", "error")
            return _back("/panel/slots")
        created = generate_slots(s, b, staff_id, d_from, d_to, t_start, t_end, max(10, min(step, 480)))
        s.commit()
        _flash(request, f"Создано окон: {created}. Выходные дни пропущены.")
    return _back("/panel/slots")


@router.post("/panel/slots/{item_id}/toggle")
def slot_toggle(request: Request, item_id: int, csrf: str = Form("")):
    """Free <-> busy without a booking, e.g. a patient who booked by phone."""
    _check_csrf(request, csrf)
    with new_session() as s:
        b = _business(s, request)
        slot = _own(s, Slot, item_id, b.id)
        active = s.exec(select(Booking).where(Booking.slot_id == slot.id, Booking.status == "booked")).first()
        if active:
            _flash(request, "На это время есть запись. Отмените её на странице «Записи».", "error")
        else:
            slot.status = "booked" if slot.status == "free" else "free"
            s.add(slot)
            s.flush()
            told = waitlist.offer_freed_slot(s, _rt(request), b, slot, utcnow()) if slot.status == "free" else 0
            s.commit()
            if told:
                _flash(request, f"Время предложено клиентам из листа ожидания: {told}.")
    return _back("/panel/slots")


@router.post("/panel/slots/{item_id}/delete")
def slot_delete(request: Request, item_id: int, csrf: str = Form("")):
    _check_csrf(request, csrf)
    with new_session() as s:
        b = _business(s, request)
        slot = _own(s, Slot, item_id, b.id)
        if s.exec(select(Booking).where(Booking.slot_id == slot.id)).first():
            _flash(request, "Окно с записью удалить нельзя, сначала отмените запись.", "error")
        else:
            s.delete(slot)
            s.commit()
    return _back("/panel/slots")


@router.get("/panel/bookings")
def bookings_page(request: Request):
    with new_session() as s:
        b = _business(s, request)
        today = datetime.combine(_now_local(b).date(), time.min)
        upcoming = s.exec(
            select(Booking).where(Booking.business_id == b.id, Booking.start >= today).order_by(Booking.start)
        ).all()
        past = s.exec(
            select(Booking)
            .where(Booking.business_id == b.id, Booking.start < today, Booking.start >= today - timedelta(days=30))
            .order_by(Booking.start.desc())
        ).all()
        waiting = s.exec(select(WaitlistEntry).where(WaitlistEntry.business_id == b.id,
                                                     WaitlistEntry.status.in_(["waiting", "notified"]),
                                                     WaitlistEntry.created_at >= utcnow() - waitlist.KEEP)
                         .order_by(WaitlistEntry.created_at)).all()
        return _render(request, "bookings.html", "bookings", b, upcoming=upcoming, past=past, channel_names=CHANNEL_NAMES,
                       waiting=waiting)


@router.post("/panel/waitlist/{item_id}/remove")
def waitlist_remove(request: Request, item_id: int, csrf: str = Form("")):
    _check_csrf(request, csrf)
    with new_session() as s:
        b = _business(s, request)
        entry = _own(s, WaitlistEntry, item_id, b.id)
        entry.status = "cancelled"
        s.add(entry)
        s.commit()
    return _back("/panel/bookings#waitlist")


@router.post("/panel/bookings/{item_id}/cancel")
def booking_cancel(request: Request, item_id: int, csrf: str = Form("")):
    _check_csrf(request, csrf)
    with new_session() as s:
        b = _business(s, request)
        booking = _own(s, Booking, item_id, b.id)
        if booking.status == "booked":
            booking.status = "cancelled"
            s.add(booking)
            slot = s.get(Slot, booking.slot_id) if booking.slot_id else None
            release_slot(s, booking.slot_id, seats_needed(slot, booking.party_size) if slot else 1)
            s.flush()
            told = 0
            if slot is not None:
                s.refresh(slot)
                told = waitlist.offer_freed_slot(s, _rt(request), b, slot, utcnow())
            s.commit()
            _flash(request, "Запись отменена, время снова свободно. Клиенту сообщите сами."
                   + (f" Время предложено клиентам из листа ожидания: {told}." if told else ""))
    return _back("/panel/bookings")


@router.post("/panel/bookings/{item_id}/paid")
def booking_paid(request: Request, item_id: int, csrf: str = Form("")):
    _check_csrf(request, csrf)
    with new_session() as s:
        b = _business(s, request)
        booking = _own(s, Booking, item_id, b.id)
        told = deposits.mark_paid(s, _rt(request), b, booking, utcnow())
        s.commit()
        if told is None:
            _flash(request, "Эта запись уже не ждёт предоплаты: она отмечена раньше или снята по сроку. Проверьте список.", "error")
        else:
            _flash(request, "Предоплата отмечена." + (" Клиенту отправлено подтверждение." if told
                                                      else " Подтвердите клиенту сами: написать ему из системы сейчас нельзя."))
    return _back("/panel/bookings")


# --- orders ------------------------------------------------------------------------------------------------

ORDER_STATUSES = {"new": "Новый", "accepted": "Принят", "done": "Выполнен", "cancelled": "Отменён"}


@router.get("/panel/orders")
def orders_page(request: Request):
    with new_session() as s:
        b = _business(s, request)
        orders = s.exec(select(Order).where(Order.business_id == b.id).order_by(Order.id.desc()).limit(100)).all()
        lines: dict[int, list[OrderLine]] = {}
        for line in s.exec(select(OrderLine).where(OrderLine.order_id.in_([o.id for o in orders] or [0])).order_by(OrderLine.id)).all():
            lines.setdefault(line.order_id, []).append(line)
        return _render(request, "orders.html", "orders", b, orders=orders, lines=lines, statuses=ORDER_STATUSES, channel_names=CHANNEL_NAMES)


@router.post("/panel/orders/{item_id}/status")
def order_status(request: Request, item_id: int, status: str = Form(""), csrf: str = Form("")):
    _check_csrf(request, csrf)
    with new_session() as s:
        b = _business(s, request)
        order = _own(s, Order, item_id, b.id)
        if status in ORDER_STATUSES:
            order.status = status
            s.add(order)
            s.commit()
    return _back("/panel/orders")


# --- leads and conversations ---------------------------------------------------------------------------


@router.get("/panel/leads")
def leads_page(request: Request):
    with new_session() as s:
        b = _business(s, request)
        new = s.exec(select(Lead).where(Lead.business_id == b.id, Lead.status == "new").order_by(Lead.id.desc())).all()
        done = s.exec(
            select(Lead).where(Lead.business_id == b.id, Lead.status == "done").order_by(Lead.id.desc()).limit(50)
        ).all()
        return _render(request, "leads.html", "leads", b, new=new, done=done, channel_names=CHANNEL_NAMES)


@router.post("/panel/leads/{item_id}/done")
def lead_done(request: Request, item_id: int, csrf: str = Form("")):
    _check_csrf(request, csrf)
    with new_session() as s:
        b = _business(s, request)
        lead = _own(s, Lead, item_id, b.id)
        lead.status, lead.closed_by = "done", _who(request)
        s.add(lead)
        s.commit()
    return _back("/panel/leads")


@router.get("/panel/cash")
def cash_page(request: Request, date: str = ""):
    """The day's cash and the month: payments recorded on visits, by method, master and service."""
    with new_session() as s:
        b = _business(s, request)
        now_local = _now_local(b)
        try:
            chosen = datetime.strptime(date, "%Y-%m-%d") if date else now_local
        except ValueError:
            chosen = now_local
        d = cash.day(s, b, chosen, now_local)
        m = cash.month(s, b, chosen)
        suggested = {x.id: cash.suggested(s, x) for x in d.unpaid}
        return _render(request, "cash.html", "cash", b, d=d, m=m, methods=cash.METHODS, suggested=suggested, chosen=chosen,
                       prev=(chosen - timedelta(days=1)).strftime("%Y-%m-%d"), next=(chosen + timedelta(days=1)).strftime("%Y-%m-%d"))


@router.post("/panel/bookings/{item_id}/pay")
def booking_pay(request: Request, item_id: int, amount: str = Form("0"), method: str = Form("cash"), csrf: str = Form("")):
    """One tap after the visit: the amount is pre-filled from the price list, the method is a choice."""
    _check_csrf(request, csrf)
    with new_session() as s:
        b = _business(s, request)
        row = s.get(Booking, item_id)
        if row is None or row.business_id != b.id:
            raise HTTPException(status_code=404)
        try:
            value = int(str(amount).replace(" ", "") or 0)
        except ValueError:
            value = 0
        cash.record(row, value, method, utcnow())
        s.add(row)
        s.commit()
        when = row.start.strftime("%Y-%m-%d")
    return _back(f"/panel/cash?date={when}")


@router.get("/panel/funnel")
def funnel_page(request: Request):
    """Requests of the last 30 days by stage; the AI moves them, a person only marks «потерян»."""
    with new_session() as s:
        b = _business(s, request)
        funnel.advance(s, b, utcnow())
        s.commit()
        f = funnel.report(s, b, utcnow())
        return _render(request, "funnel.html", "funnel", b, f=f, stages=funnel.STAGES, labels=funnel.LABELS, channel_names=CHANNEL_NAMES)


@router.post("/panel/funnel/{item_id}")
def funnel_move(request: Request, item_id: int, stage: str = Form(""), csrf: str = Form("")):
    _check_csrf(request, csrf)
    if stage not in funnel.STAGES:
        raise HTTPException(status_code=400)
    with new_session() as s:
        b = _business(s, request)
        lead = s.get(Lead, item_id)
        if lead is None or lead.business_id != b.id:
            raise HTTPException(status_code=404)
        lead.stage = stage
        if stage in ("visited", "lost", "booked") and lead.status == "new":
            lead.status, lead.closed_by = "done", _who(request)
        s.add(lead)
        s.commit()
    return _back("/panel/funnel")


@router.get("/panel/customers")
def customers_page(request: Request, q: str = "", tag: str = ""):
    """Every customer, assembled by the AI from bookings, orders and dialogues: nobody types a card."""
    with new_session() as s:
        b = _business(s, request)
        rows = customers.listing(s, b, q, tag)
        tags = sorted({t for c in rows for t in c.tag_list})
        return _render(request, "customers.html", "customers", b, rows=rows[:300], total=len(rows), q=q, tag=tag, tags=tags,
                       channel_names=CHANNEL_NAMES)


@router.get("/panel/customers.csv")
def customers_csv(request: Request):
    with new_session() as s:
        b = _business(s, request)
        text = customers.export_csv(customers.listing(s, b), b.timezone)
    return PlainTextResponse(text, media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": 'attachment; filename="customers.csv"'})


@router.get("/panel/customers/{key}")
def customer_card(request: Request, key: str):
    with new_session() as s:
        b = _business(s, request)
        card = customers.cards(s, b).get(key)
        if card is None:
            raise HTTPException(status_code=404)
        return _render(request, "customer.html", "customers", b, c=card, channel_names=CHANNEL_NAMES)


@router.post("/panel/customers/{key}")
def customer_save(request: Request, key: str, note: str = Form(""), tags: str = Form(""), csrf: str = Form("")):
    _check_csrf(request, csrf)
    with new_session() as s:
        b = _business(s, request)
        if key not in customers.cards(s, b):
            raise HTTPException(status_code=404)
        customers.save_note(s, b, key, note, tags)
        s.commit()
    _flash(request, "Заметка сохранена.")
    return _back(f"/panel/customers/{key}")


@router.get("/panel/conversations")
def conversations_page(request: Request):
    with new_session() as s:
        b = _business(s, request)
        convs = s.exec(
            select(Conversation).where(Conversation.business_id == b.id).order_by(Conversation.last_message_at.desc()).limit(100)
        ).all()
        last_ids = s.exec(
            select(func.max(Message.id)).where(Message.conversation_id.in_([c.id for c in convs] or [0])).group_by(Message.conversation_id)
        ).all()
        last = {m.conversation_id: m for m in s.exec(select(Message).where(Message.id.in_(list(last_ids) or [0]))).all()}
        return _render(
            request,
            "conversations.html",
            "conversations",
            b,
            rows=[(c, last.get(c.id)) for c in convs],
            now=utcnow(),
            channel_names=CHANNEL_NAMES,
        )


@router.get("/panel/card")
def counter_card(request: Request, via: str = ""):
    """A printable card for the counter: a QR to the chat the owner picks, with Joop's name on it."""
    from markupsafe import Markup

    from ..studio import phone_digits
    from .menu import qr_svg

    base = _base_url(request)
    with new_session() as s:
        b = _business(s, request)
    if b.telegram_bot_token and not b.telegram_bot_username:  # connected before the username was kept: ask Telegram once
        client = _rt(request).telegram(b)
        me = client.get_me() if client else None
        if me and me.get("username"):
            with new_session() as s:
                b = _business(s, request)
                b.telegram_bot_username = str(me["username"])
                s.add(b)
                s.commit()
    options = {"web": (f"{base}/c/{b.slug}", "Чат на сайте")}
    if b.telegram_bot_token and b.telegram_bot_username:  # only where Joop actually answers
        options["telegram"] = (f"https://t.me/{b.telegram_bot_username}", "Telegram")
    whatsapp_on = bool(b.wa_phone_number_id and b.wa_access_token)
    if whatsapp_on and phone_digits(b.phone):
        options["whatsapp"] = (f"https://wa.me/{phone_digits(b.phone)}", "WhatsApp")
    notes = {"telegram": "Telegram-бот ещё не подключён — подключите его в «Каналах», и ссылка появится.",
             "whatsapp": ("Укажите телефон для клиентов в «Настройках» — тот, что подключён к WhatsApp: на него поведёт ссылка."
                          if whatsapp_on else "WhatsApp ещё не подключён — подключите его в «Каналах», и ссылка появится.")}
    note = "" if via in options or via not in notes else notes[via]
    chosen = via if via in options else ("telegram" if "telegram" in options else "whatsapp" if "whatsapp" in options else "web")
    url, label = options[chosen]
    return templates.TemplateResponse(request, "counter_card.html", {
        "request": request, "b": b, "url": url, "label": label, "chosen": chosen, "qr": Markup(qr_svg(url)), "note": note,
        "choices": [("telegram", "Telegram"), ("whatsapp", "WhatsApp"), ("web", "Чат на сайте")],
    })


@router.get("/panel/gaps")
def gaps_page(request: Request):
    with new_session() as s:
        b = _business(s, request)
        now_local = _now_local(b)
        days = gaps.week(s, b, now_local)
        rows = gaps.candidates(s, b, now_local)
        return _render(request, "gaps.html", "gaps", b, days=days, rows=rows, free=sum(d.free for d in days), total=sum(d.total for d in days))


@router.post("/panel/gaps/{conv_id}/send")
def gaps_send(request: Request, conv_id: int, csrf: str = Form("")):
    _check_csrf(request, csrf)
    with new_session() as s:
        b = _business(s, request)
        _own(s, Conversation, conv_id, b.id)
        cand = next((c for c in gaps.candidates(s, b, _now_local(b)) if c.conversation_id == conv_id), None)
        if cand is None:
            _flash(request, "Этого клиента уже не нужно приглашать: записался или получил приглашение.", "error")
            return _back("/panel/gaps")
        ok = gaps.send(s, _rt(request), b, cand, utcnow())
        s.commit()
    if ok:
        _flash(request, "Приглашение отправлено.")
    else:
        _flash(request, "Не удалось отправить: в этом канале сейчас нельзя написать первым — позвоните.", "error")
    return _back("/panel/gaps")


@router.post("/panel/gaps/send-all")
def gaps_send_all(request: Request, csrf: str = Form("")):
    _check_csrf(request, csrf)
    sent = 0
    with new_session() as s:
        b = _business(s, request)
        for cand in [c for c in gaps.candidates(s, b, _now_local(b)) if c.reachable]:
            sent += gaps.send(s, _rt(request), b, cand, utcnow())
        s.commit()
    _flash(request, f"Отправлено: {sent}.")
    return _back("/panel/gaps")


@router.get("/panel/conversations/{item_id}")
def conversation_page(request: Request, item_id: int):
    with new_session() as s:
        b = _business(s, request)
        conv = _own(s, Conversation, item_id, b.id)
        if conv.reviewed_at is None and request.session.get("owner") is not True:  # the owner's first look, not the founder's
            conv.reviewed_at = utcnow()
            s.add(conv)
            s.commit()
            s.refresh(conv)
        messages = list(
            reversed(s.exec(select(Message).where(Message.conversation_id == conv.id).order_by(Message.id.desc()).limit(200)).all())
        )
        return _render(
            request,
            "conversation.html",
            "conversations",
            b,
            conv=conv,
            messages=messages,
            paused=bool(conv.ai_paused_until and conv.ai_paused_until > utcnow()),
            channel_names=CHANNEL_NAMES,
            reply_blocked=staff_reply.blocked(conv, utcnow()),
        )


@router.post("/panel/conversations/{item_id}/reply")
def conversation_reply(request: Request, item_id: int, text: str = Form(""), csrf: str = Form("")):
    """Staff answer the customer from the panel, through the customer's channel (joop/staff_reply.py)."""
    _check_csrf(request, csrf)
    with new_session() as s:
        b = _business(s, request)
        conv = _own(s, Conversation, item_id, b.id)
        sent, problem = staff_reply.send(s, _rt(request), b, conv, text, utcnow(), author=_who(request))
        s.commit()
    if sent:
        _flash(request, "Ответ отправлен. ИИ не вмешивается в этот диалог 12 часов; заявки из него отмечены выполненными.")
    else:
        _flash(request, problem, "error")
    return _back(f"/panel/conversations/{item_id}")


@router.post("/panel/conversations/{item_id}/pause")
def conversation_pause(request: Request, item_id: int, hours: int = Form(24), csrf: str = Form("")):
    _check_csrf(request, csrf)
    with new_session() as s:
        b = _business(s, request)
        conv = _own(s, Conversation, item_id, b.id)
        conv.ai_paused_until = utcnow() + timedelta(hours=max(1, min(hours, 24 * 30)))
        s.add(conv)
        s.commit()
        _flash(request, "ИИ не будет отвечать в этом диалоге. Отвечайте клиенту сами.")
    return _back(f"/panel/conversations/{item_id}")


@router.post("/panel/conversations/{item_id}/resume")
def conversation_resume(request: Request, item_id: int, csrf: str = Form("")):
    _check_csrf(request, csrf)
    with new_session() as s:
        b = _business(s, request)
        conv = _own(s, Conversation, item_id, b.id)
        conv.ai_paused_until = None
        s.add(conv)
        s.commit()
        _flash(request, "ИИ снова отвечает в этом диалоге.")
    return _back(f"/panel/conversations/{item_id}")


# --- settings and channels -------------------------------------------------------------------------------


@router.get("/panel/settings")
def settings_page(request: Request):
    with new_session() as s:
        b = _business(s, request)
        return _render(
            request,
            "settings.html",
            "settings",
            b,
            weekdays=list(enumerate(WEEKDAYS_SHORT, start=1)),
            days_off=parse_days_off(b.days_off),
            timezones=TIMEZONES,
            packs=all_packs(),
            admins=admin_chat_ids(b),
        )


@router.post("/panel/settings")
async def settings_save(request: Request):
    form = await request.form()
    _check_csrf(request, str(form.get("csrf", "")))

    def text(key: str, limit: int = 300) -> str:
        return str(form.get(key, "")).strip()[:limit]

    def hour(key: str, default: int) -> int:
        try:
            return max(0, min(23, int(str(form.get(key, default)))))
        except ValueError:
            return default

    with new_session() as s:
        b = _business(s, request)
        if text("name"):
            b.name = text("name", 120)
        b.address, b.phone, b.hours_text = text("address"), text("phone", 60), text("hours_text")
        start, end = parse_hhmm(text("work_start")), parse_hhmm(text("work_end"))
        if start and end and end > start:
            b.work_start, b.work_end = f"{start:%H:%M}", f"{end:%H:%M}"
        else:
            _flash(request, "Часы работы не сохранены: конец должен быть позже начала.", "error")
        b.days_off = ",".join(str(d) for d in range(1, 8) if form.get(f"off{d}"))
        if text("timezone") in TIMEZONES:
            b.timezone = text("timezone")
        if text("niche") in all_packs():
            b.niche = text("niche")
        b.extra_rules = text("extra_rules", 3000)
        b.description = text("description", 1000)
        b.tone = text("tone", 300)
        b.booking_policy = text("booking_policy", 1000)
        b.greeting = text("greeting", 1000)
        b.bot_enabled = bool(form.get("bot_enabled"))
        for key in ("min_order", "delivery_fee", "free_delivery_from"):
            try:
                setattr(b, key, max(0, int(str(form.get(key) or 0).replace(" ", ""))))
            except ValueError:
                pass
        b.reminder_hour = hour("reminder_hour", b.reminder_hour)
        b.digest_hour = hour("digest_hour", b.digest_hour)
        if "lead_nudge_minutes" in form:
            try:
                b.lead_nudge_minutes = max(0, min(int(str(form.get("lead_nudge_minutes") or 0)), 480))
            except ValueError:
                pass
        if "deposit_amount" in form:  # the card is shown only to businesses that book times
            try:
                amount = max(0, min(int(str(form.get("deposit_amount") or 0).replace(" ", "")), 100_000))
                b.deposit_hours = max(1, min(int(str(form.get("deposit_hours") or 2)), 48))
            except ValueError:
                amount = b.deposit_amount
            b.deposit_details = text("deposit_details")
            b.deposit_auto_cancel = bool(form.get("deposit_auto_cancel"))
            if amount and not b.deposit_details:
                amount = 0
                _flash(request, "Предоплата не включена: напишите, как оплатить.", "error")
            b.deposit_amount = amount
        if "nudge_unfinished" in form or "release_unconfirmed_hours" in form:
            b.nudge_unfinished = bool(form.get("nudge_unfinished"))
        if "release_unconfirmed_hours" in form:
            try:
                b.release_unconfirmed_hours = max(0, min(int(str(form.get("release_unconfirmed_hours") or 0)), confirm.MAX_RELEASE_HOURS))
            except ValueError:
                pass
        s.add(b)
        s.commit()
    _flash(request, "Настройки сохранены.")
    return _back("/panel/settings")


@router.post("/panel/settings/link-code")
def settings_new_code(request: Request, csrf: str = Form("")):
    _check_csrf(request, csrf)
    with new_session() as s:
        b = _business(s, request)
        b.admin_link_code = new_link_code()
        s.add(b)
        s.commit()
    _flash(request, "Новый код создан. Старый больше не работает.")
    return _back("/panel/settings")


@router.post("/panel/settings/unlink")
def settings_unlink(request: Request, csrf: str = Form("")):
    _check_csrf(request, csrf)
    with new_session() as s:
        b = _business(s, request)
        b.admin_chat_ids = ""
        b.admin_link_code = new_link_code()
        s.add(b)
        s.commit()
    _flash(request, "Все чаты отвязаны от уведомлений.")
    return _back("/panel/settings")


@router.post("/panel/settings/password")
def settings_password(request: Request, current: str = Form(""), new: str = Form(""), csrf: str = Form("")):
    _check_csrf(request, csrf)
    with new_session() as s:
        b = _business(s, request)
        if not verify_password(current, b.admin_password_hash):
            _flash(request, "Текущий пароль неверный.", "error")
        elif len(new) < 8:
            _flash(request, "Новый пароль должен быть не короче 8 символов.", "error")
        else:
            b.admin_password_hash = hash_password(new)
            s.add(b)
            s.commit()
            _flash(request, "Пароль изменён.")
    return _back("/panel/settings")


@router.get("/panel/channels")
def channels_page(request: Request):
    settings = _settings(request)
    with new_session() as s:
        b = _business(s, request)
        base = settings.public_base_url
        return _render(
            request,
            "channels.html",
            "channels",
            b,
            public_base=base,
            telegram_url=f"{base}/webhooks/telegram/{b.slug}" if base else "",
            meta_url=f"{base}/webhooks/meta" if base else "",
            meta_ready=bool(settings.meta_verify_token and (settings.meta_app_secret or settings.instagram_app_secret)),
            altegio_shared=bool(settings.altegio_partner_token),
            chat_url=f"{base or str(request.base_url).rstrip('/')}/c/{b.slug}",
            chat_qr=_chat_qr(f"{base or str(request.base_url).rstrip('/')}/c/{b.slug}"),
            altegio_synced=utc_to_local(b.altegio_synced_at, b.timezone) if b.altegio_synced_at else None,
        )


@router.get("/panel/sticker", response_class=HTMLResponse)
def sticker_page(request: Request):
    """A printable A4 sheet of four stickers: "ask a question, we answer at once" with the chat's QR code."""
    from .menu import qr_svg

    settings = _settings(request)
    with new_session() as s:
        b = _business(s, request)
        url = f"{settings.public_base_url or str(request.base_url).rstrip('/')}/c/{b.slug}"
        return templates.TemplateResponse(request, "sticker.html", {"request": request, "business": b, "qr": qr_svg(url, scale=6)})


def _chat_qr(url: str) -> str:
    from .menu import qr_svg

    return qr_svg(url, scale=4, sized=True)


@router.post("/panel/altegio")
def altegio_save(request: Request, location_id: str = Form(""), token: str = Form(""), clear_token: str = Form(""),
                 action: str = Form("connect"), csrf: str = Form("")):
    """Connect the salon's Altegio location: check the ID by loading its services and team right away;
    the free times follow within a minute (scheduler)."""
    from .. import altegio

    _check_csrf(request, csrf)
    with new_session() as s:
        b = _business(s, request)
        if action == "disconnect":
            b.altegio_location_id, b.altegio_error, b.altegio_synced_at = 0, "", None
            s.add(b)
            s.commit()
            _flash(request, "Altegio отключён. Прайс и сотрудники остались; включите нужных вручную в разделе «Сотрудники».")
            return _back("/panel/channels")
        digits = "".join(ch for ch in location_id if ch.isdigit())[:12]
        if not digits or int(digits) <= 0:
            _flash(request, "Укажите ID филиала в Altegio — это число из адреса вашей онлайн-записи.", "error")
            return _back("/panel/channels")
        b.altegio_location_id = int(digits)
        if clear_token:
            b.altegio_token = ""
        elif token.strip():
            b.altegio_token = token.strip()[:500]
        client = _rt(request).altegio(b)
        if client is None:
            _flash(request, "Нет ключа Altegio: вставьте ключ партнёра или попросите нас включить общий ключ.", "error")
            s.add(b)
            s.commit()
            return _back("/panel/channels")
        try:
            res = altegio.sync(s, b, client, utcnow(), with_slots=False)
        except altegio.AltegioError as exc:
            s.rollback()
            _flash(request, f"Altegio не принял подключение ({exc.status or 'нет связи'}). Проверьте ID филиала и ключ.", "error")
            return _back("/panel/channels")
        b.altegio_synced_at = None  # the scheduler loads the free times on its next round
        s.add(b)
        s.commit()
        _flash(request, f"Altegio подключён: услуг {res.services}, сотрудников {res.staff}. Свободные окна загрузятся в течение минуты.")
    return _back("/panel/channels")


@router.post("/panel/crm")
def crm_save(request: Request, domain: str = Form(""), token: str = Form(""), pipeline_id: str = Form(""),
             action: str = Form("connect"), csrf: str = Form("")):
    """Connect amoCRM / Kommo: check the token on the account right away; deals follow with the scheduler."""
    from .. import crm

    _check_csrf(request, csrf)
    with new_session() as s:
        b = _business(s, request)
        if action == "disconnect":
            b.crm_domain, b.crm_token, b.crm_error = "", "", ""
            s.add(b)
            s.commit()
            _flash(request, "amoCRM отключён: новые записи и заявки туда больше не уходят.")
            return _back("/panel/channels")
        base = crm.base_url(domain)
        if not base:
            _flash(request, "Укажите адрес аккаунта amoCRM, например mycompany.amocrm.ru или mycompany.kommo.com.", "error")
            return _back("/panel/channels")
        key = token.strip()[:2000] or b.crm_token
        if not key:
            _flash(request, "Вставьте долгосрочный токен из настроек интеграции amoCRM.", "error")
            return _back("/panel/channels")
        try:
            account = crm.AmoClient(_rt(request).http, base, key).account()
        except crm.CrmError as exc:
            _flash(request, f"amoCRM не принял подключение ({exc.status or 'нет связи'}). Проверьте адрес и токен.", "error")
            return _back("/panel/channels")
        digits = "".join(ch for ch in pipeline_id if ch.isdigit())[:12]
        b.crm_domain, b.crm_token, b.crm_pipeline_id, b.crm_error = base.removeprefix("https://"), key, int(digits or 0), ""
        s.add(b)
        s.commit()
        name = str(account.get("name") or "").strip()
        _flash(request, f"amoCRM подключён{(': ' + name) if name else ''}. Новые записи, заявки и заказы будут появляться там как сделки в течение нескольких минут.")
    return _back("/panel/channels")


@router.post("/panel/channels")
async def channels_save(request: Request):
    form = await request.form()
    _check_csrf(request, str(form.get("csrf", "")))

    def value(key: str) -> str:
        return str(form.get(key, "")).strip()

    with new_session() as s:
        b = _business(s, request)
        # The bot token is not saved here: /panel/setup/telegram checks it with Telegram first and sets the webhook.
        for field in ("wa_access_token", "ig_access_token"):
            if form.get(f"clear_{field}"):
                setattr(b, field, "")
            elif value(field):
                setattr(b, field, value(field))
                if field == "ig_access_token":
                    b.ig_token_refreshed_at = utcnow()  # a freshly pasted token is valid for 60 days
        for field in ("wa_phone_number_id", "wa_reminder_template", "ig_account_id"):
            setattr(b, field, value(field))
        b.ig_comments = bool(form.get("ig_comments"))
        b.ig_comment_keywords = value("ig_comment_keywords")[:300]
        b.ig_comment_public_reply = value("ig_comment_public_reply")[:200]
        b.wa_template_lang = value("wa_template_lang") or "ru"
        for field, column in (("wa_phone_number_id", Business.wa_phone_number_id), ("ig_account_id", Business.ig_account_id)):
            account = getattr(b, field)
            if account and s.exec(select(Business).where(column == account, Business.id != b.id)).first():
                _flash(request, "Этот аккаунт уже подключён к другой компании.", "error")
                return _back("/panel/channels")
        if not (b.ig_account_id and b.ig_access_token):
            b.ig_username = ""
        elif value("ig_access_token") or not b.ig_username:  # a new token, or connected before the username was kept
            client = _rt(request).instagram(b)
            b.ig_username = str((client.get_me() if client else {}).get("username") or "")
        s.add(b)
        s.commit()
    _flash(request, "WhatsApp и Instagram сохранены.")
    return _back("/panel/channels")


@router.post("/panel/channels/telegram/disconnect")
def telegram_disconnect(request: Request, csrf: str = Form("")):
    """Stop the bot: Telegram stops sending its messages here (best effort), then the token is removed."""
    _check_csrf(request, csrf)
    with new_session() as s:
        b = _business(s, request)
        client = _rt(request).telegram(b)
        if client is not None:
            try:
                client.delete_webhook()
            except Exception:  # noqa: BLE001 - Telegram unreachable: the token is removed anyway
                log.warning("Telegram webhook not deleted for %s", b.slug)
        b.telegram_bot_token = ""
        b.telegram_bot_username = ""  # the counter card must not point at a bot that no longer answers
        s.add(b)
        s.commit()
    _flash(request, "Бот отключён: в Telegram ИИ больше не отвечает. Подключить снова — вставьте токен.")
    return _back("/panel/channels#telegram")


@router.post("/panel/channels/telegram/webhook")
def telegram_connect(request: Request, csrf: str = Form("")):
    _check_csrf(request, csrf)
    settings = _settings(request)
    with new_session() as s:
        b = _business(s, request)
    client = _rt(request).telegram(b)
    if client is None:
        _flash(request, "Сначала сохраните токен бота.", "error")
        return _back("/panel/channels")
    if not settings.public_base_url.startswith("https://"):
        _flash(request, "Нужен PUBLIC_BASE_URL с https. Для теста на компьютере используйте режим опроса: python -m joop dev.", "error")
        return _back("/panel/channels")
    me = client.get_me()
    if not me:
        _flash(request, "Telegram не принял токен. Проверьте его у @BotFather.", "error")
        return _back("/panel/channels")
    with new_session() as s:
        b = _business(s, request)
        b.telegram_bot_username = str(me.get("username") or "")
        s.add(b)
        s.commit()
    if client.set_webhook(f"{settings.public_base_url}/webhooks/telegram/{b.slug}", b.telegram_secret):
        _flash(request, f"Бот @{me.get('username', '')} подключён. Напишите ему, чтобы проверить.")
    else:
        _flash(request, "Не удалось подключить вебхук. Проверьте, что адрес сервера доступен из интернета.", "error")
    return _back("/panel/channels")


# --- webhooks ------------------------------------------------------------------------------------------


@router.post("/webhooks/telegram/{slug}")
async def telegram_webhook(slug: str, request: Request, background: BackgroundTasks):
    secret = request.headers.get("x-telegram-bot-api-secret-token", "")
    with new_session() as s:
        business = s.exec(select(Business).where(Business.slug == slug)).first()
    if business is None or not business.telegram_secret or not hmac.compare_digest(secret, business.telegram_secret):
        raise HTTPException(status_code=403)
    try:
        update = await request.json()
    except ValueError:
        raise HTTPException(status_code=400) from None
    incoming = parse_update(update) if isinstance(update, dict) else None
    if incoming is not None:
        background.add_task(process_incoming, _rt(request), business.id, incoming)
    return {"ok": True}


@router.get("/webhooks/meta")
def meta_verify(request: Request):
    params = request.query_params
    token = _settings(request).meta_verify_token
    if params.get("hub.mode") == "subscribe" and token and hmac.compare_digest(params.get("hub.verify_token", ""), token):
        return PlainTextResponse(params.get("hub.challenge", ""))
    raise HTTPException(status_code=403)


@router.post("/webhooks/meta")
async def meta_events(request: Request, background: BackgroundTasks):
    settings = _settings(request)
    app_secrets = [x for x in (settings.meta_app_secret, settings.instagram_app_secret) if x]
    if not app_secrets:
        raise HTTPException(status_code=503, detail="META_APP_SECRET is not configured")
    raw = await request.body()
    if not verify_signature(app_secrets, raw, request.headers.get("x-hub-signature-256", "")):
        raise HTTPException(status_code=403)
    try:
        payload = json.loads(raw or b"{}")
    except ValueError:
        raise HTTPException(status_code=400) from None
    events = parse_meta_payload(payload) if isinstance(payload, dict) else []
    if events:
        with new_session() as s:
            for channel, account_id, incoming in events:
                column = Business.wa_phone_number_id if channel == "whatsapp" else Business.ig_account_id
                business = s.exec(select(Business).where(column == account_id)).first() if account_id else None
                if business is None:
                    log.warning("No business is connected to %s account %s", channel, account_id)
                    continue
                if incoming.reply_to and (ig_comments.own(business, incoming.text, incoming.user_name)
                                          or not ig_comments.wanted(business, incoming.text)):
                    continue  # the business's own comment (the pointer Joop posted), one that asks nothing («Красиво!»), or the feature is off
                if incoming.reply_to:  # one Direct opening per commenter a day: 300 «?» comments must not become 300 public replies
                    key, day = f"igc:{business.id}:{incoming.chat_id}", local_now(business.timezone).strftime("%Y-%m-%d")
                    if daily_count(key, day) >= 1:
                        continue
                    daily_bump(key, day)
                background.add_task(process_incoming, _rt(request), business.id, incoming)
    return PlainTextResponse("EVENT_RECEIVED")


# --- app factory ----------------------------------------------------------------------------------------


def create_app(settings: Settings | None = None, runtime: Runtime | None = None, init: bool = True) -> FastAPI:
    settings = settings or get_settings()
    rt = runtime or Runtime(settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if init:
            init_db()
        scheduler = Scheduler(rt, settings.scheduler_interval) if settings.scheduler_enabled else None
        if scheduler:
            scheduler.start()
        yield
        if scheduler:
            scheduler.stop()

    app = FastAPI(title="Joop AI", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.state.rt = rt
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret,
        https_only=settings.secure_cookies,
        same_site="lax",
        max_age=14 * 24 * 3600,
    )
    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
    app.include_router(router)
    from .saas import OwnerRequired, router as saas_router  # imported here: saas uses this module's helpers

    app.include_router(saas_router)
    from .studio import router as studio_router

    app.include_router(studio_router)
    from .placement import router as placement_router

    app.include_router(placement_router)
    from .menu import router as menu_router

    app.include_router(menu_router)
    from .audit import router as audit_router

    app.include_router(audit_router)
    from .demo import router as demo_router

    app.include_router(demo_router)
    from .followups import router as followups_router

    app.include_router(followups_router)
    from .memberships import router as memberships_router

    app.include_router(memberships_router)
    from .jobs import router as jobs_router

    app.include_router(jobs_router)
    from .stays import router as stays_router

    app.include_router(stays_router)
    from .webchat import router as webchat_router

    app.include_router(webchat_router)
    from .broadcasts import router as broadcasts_router

    app.include_router(broadcasts_router)
    from .autofill import router as autofill_router

    app.include_router(autofill_router)
    from .accounts import router as accounts_router

    app.include_router(accounts_router)

    @app.exception_handler(OwnerRequired)
    async def _owner_required(_request: Request, _exc: OwnerRequired):
        return RedirectResponse("/owner/login", status_code=303)

    @app.exception_handler(LoginRequired)
    async def _login_required(_request: Request, _exc: LoginRequired):
        return RedirectResponse("/login", status_code=303)

    @app.exception_handler(HTTPException)
    async def _http_error(request: Request, exc: HTTPException):
        if request.url.path.startswith("/webhooks") or request.url.path == "/health":
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        return templates.TemplateResponse(
            request,
            "error.html",
            {"request": request, "status": exc.status_code, "detail": exc.detail, "business": None, "flashes": []},
            status_code=exc.status_code,
        )

    return app
