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
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
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
from ..models import Booking, Business, Conversation, Faq, Lead, Message, Order, OrderLine, Service, Slot, Staff
from ..niches import all_packs, get_pack
from ..runtime import Runtime
from ..scheduler import Scheduler
from ..security import hash_password, new_link_code, verify_password
from ..slots import add_slots, generate_slots, parse_times, release_slot
from ..stats import activity
from ..timeutil import WEEKDAYS_SHORT, fmt_date_long, fmt_dt, fmt_slot, parse_days_off, parse_hhmm, utc_to_local, utcnow

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
    items = [("/panel", "dashboard", "Сводка"), ("/panel/conversations", "conversations", "Диалоги")]
    if pack.has("order"):
        items.append(("/panel/orders", "orders", "Заказы"))
    if books:
        items.append(("/panel/bookings", "bookings", "Записи"))
    if pack.has("booking"):
        items.append(("/panel/slots", "slots", "Окна"))
    items.append(("/panel/leads", "leads", "Заявки"))
    items.append(("/panel/services", "services", pack.catalog_label))
    if books:
        items.append(("/panel/staff", "staff", pack.resource_label))
    items += [("/panel/faq", "faq", "Вопросы"), ("/panel/settings", "settings", "Настройки"), ("/panel/channels", "channels", "Каналы")]
    items[1:1] = [("/panel/setup", "setup", "Запуск"), ("/panel/try", "try", "Проверить ИИ")]
    items.append(("/panel/billing", "billing", "Оплата"))
    return items
TIMEZONES = ["Asia/Bishkek", "Asia/Almaty", "Asia/Tashkent", "Asia/Dushanbe", "Europe/Moscow"]
CHANNEL_NAMES = {"telegram": "Telegram", "whatsapp": "WhatsApp", "instagram": "Instagram", "console": "Тест"}

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


def _business(s: Session, request: Request) -> Business:
    business = s.get(Business, _bid(request))
    if business is None:
        request.session.clear()
        raise LoginRequired
    return business


def _own(s: Session, model: Any, obj_id: int, business_id: int) -> Any:
    obj = s.get(model, obj_id)
    if obj is None or obj.business_id != business_id:
        raise HTTPException(status_code=404)
    return obj


def _render(request: Request, template: str, active: str, business: Business | None = None, **ctx: Any):
    ctx.update(
        request=request,
        business=business,
        csrf=_csrf(request),
        flashes=request.session.pop("flash", []),
        nav=nav_for(business),
        pack=get_pack(business.niche if business else None),
        active=active,
    )
    return templates.TemplateResponse(request, template, ctx)


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
        updated="29.10.2026",
    )
    return templates.TemplateResponse(request, template, ctx)


@router.get("/")
def landing(request: Request):
    s = _settings(request)
    packs = {k: p for k, p in all_packs().items() if k != "other"}
    return _site(request, "site_home.html", packs=packs, price=s.price_som, trial_days=s.trial_days, signup=s.signup_enabled)


@router.get("/privacy")
def privacy(request: Request):
    return _site(request, "site_privacy.html")


@router.get("/data-deletion")
def data_deletion(request: Request):
    return _site(request, "site_deletion.html")


@router.get("/login")
def login_form(request: Request):
    return _render(request, "login.html", "login")


# Failed panel logins per login name: (count, first failure time). In memory: one process serves the panel.
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


@router.post("/login")
def login(request: Request, slug: str = Form(""), password: str = Form(""), csrf: str = Form("")):
    _check_csrf(request, csrf)
    key, now = slug.strip().lower(), time_module.time()
    if _login_locked(key, now):
        _flash(request, "Слишком много неудачных попыток. Попробуйте через 15 минут.", "error")
        return _back("/login")
    with new_session() as s:
        business = s.exec(select(Business).where(Business.slug == key)).first()
    if business is None or not verify_password(password, business.admin_password_hash):
        _login_failed(key, now)
        _flash(request, "Неверный логин или пароль.", "error")
        return _back("/login")
    _login_fails.pop(key, None)
    request.session.clear()
    request.session["bid"] = business.id
    return _back("/panel")


@router.post("/logout")
def logout(request: Request, csrf: str = Form("")):
    _check_csrf(request, csrf)
    request.session.clear()
    return _back("/login")


# --- dashboard -------------------------------------------------------------------------------------


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
        return _render(
            request,
            "dashboard.html",
            "dashboard",
            b,
            s14=activity(s, b.id, now - timedelta(days=14)),
            s1=activity(s, b.id, now - timedelta(hours=24)),
            upcoming=upcoming,
            leads=leads,
            counts=counts,
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
    request: Request, name: str = Form(""), role: str = Form(""), handles: str = Form(""), capacity: int = Form(0), csrf: str = Form("")
):
    _check_csrf(request, csrf)
    with new_session() as s:
        b = _business(s, request)
        if name.strip():
            s.add(Staff(business_id=b.id, name=name.strip(), role=role.strip(), handles=handles.strip(), capacity=max(0, capacity)))
            s.commit()
            _flash(request, "Специалист добавлен. Теперь создайте для него окна записи.")
    return _back("/panel/staff")


@router.post("/panel/staff/{item_id}")
def staff_update(
    request: Request, item_id: int, name: str = Form(""), role: str = Form(""), handles: str = Form(""), capacity: int = Form(0), csrf: str = Form("")
):
    _check_csrf(request, csrf)
    with new_session() as s:
        b = _business(s, request)
        row = _own(s, Staff, item_id, b.id)
        if name.strip():
            row.name, row.role, row.handles = name.strip(), role.strip(), handles.strip()
            row.capacity = max(0, capacity)
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
        for slot in s.exec(select(Slot).where(Slot.staff_id == row.id, Slot.status == "free")).all():
            s.delete(slot)
        s.commit()
        _flash(request, "Специалист убран, его свободные окна удалены. Существующие записи остались.")
    return _back("/panel/staff")


@router.get("/panel/faq")
def faq_page(request: Request):
    with new_session() as s:
        b = _business(s, request)
        rows = s.exec(select(Faq).where(Faq.business_id == b.id).order_by(Faq.id)).all()
        return _render(request, "faq.html", "faq", b, rows=rows)


@router.post("/panel/faq")
def faq_add(request: Request, question: str = Form(""), answer: str = Form(""), csrf: str = Form("")):
    _check_csrf(request, csrf)
    with new_session() as s:
        b = _business(s, request)
        if question.strip() and answer.strip():
            s.add(Faq(business_id=b.id, question=question.strip(), answer=answer.strip()))
            s.commit()
            _flash(request, "Вопрос добавлен.")
    return _back("/panel/faq")


@router.post("/panel/faq/{item_id}")
def faq_update(request: Request, item_id: int, question: str = Form(""), answer: str = Form(""), csrf: str = Form("")):
    _check_csrf(request, csrf)
    with new_session() as s:
        b = _business(s, request)
        row = _own(s, Faq, item_id, b.id)
        if question.strip() and answer.strip():
            row.question, row.answer = question.strip(), answer.strip()
            s.add(row)
            s.commit()
            _flash(request, "Сохранено.")
    return _back("/panel/faq")


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
            s.commit()
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
        return _render(request, "bookings.html", "bookings", b, upcoming=upcoming, past=past, channel_names=CHANNEL_NAMES)


@router.post("/panel/bookings/{item_id}/cancel")
def booking_cancel(request: Request, item_id: int, csrf: str = Form("")):
    _check_csrf(request, csrf)
    with new_session() as s:
        b = _business(s, request)
        booking = _own(s, Booking, item_id, b.id)
        if booking.status == "booked":
            booking.status = "cancelled"
            s.add(booking)
            release_slot(s, booking.slot_id)
            s.commit()
            _flash(request, "Запись отменена, время снова свободно. Клиенту сообщите сами.")
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
        lead.status = "done"
        s.add(lead)
        s.commit()
    return _back("/panel/leads")


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


@router.get("/panel/conversations/{item_id}")
def conversation_page(request: Request, item_id: int):
    with new_session() as s:
        b = _business(s, request)
        conv = _own(s, Conversation, item_id, b.id)
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
        )


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
        )


@router.post("/panel/channels")
async def channels_save(request: Request):
    form = await request.form()
    _check_csrf(request, str(form.get("csrf", "")))

    def value(key: str) -> str:
        return str(form.get(key, "")).strip()

    with new_session() as s:
        b = _business(s, request)
        for field in ("telegram_bot_token", "wa_access_token", "ig_access_token"):
            if form.get(f"clear_{field}"):
                setattr(b, field, "")
            elif value(field):
                setattr(b, field, value(field))
                if field == "ig_access_token":
                    b.ig_token_refreshed_at = utcnow()  # a freshly pasted token is valid for 60 days
        for field in ("wa_phone_number_id", "wa_reminder_template", "ig_account_id"):
            setattr(b, field, value(field))
        b.wa_template_lang = value("wa_template_lang") or "ru"
        for field, column in (("wa_phone_number_id", Business.wa_phone_number_id), ("ig_account_id", Business.ig_account_id)):
            account = getattr(b, field)
            if account and s.exec(select(Business).where(column == account, Business.id != b.id)).first():
                _flash(request, "Этот аккаунт уже подключён к другой компании.", "error")
                return _back("/panel/channels")
        s.add(b)
        s.commit()
    _flash(request, "Каналы сохранены.")
    return _back("/panel/channels")


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
