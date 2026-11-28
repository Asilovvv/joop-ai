"""JSON API for the Joop mobile app (the owner's and staff's app, a Flutter client): /api/mobile/...

The app signs in with the same credentials as the panel: the company login and its password for the owner, or a
staff member's own login and password (PanelUser). It gets a signed token and sends it as `Authorization: Bearer`.

The token is not stored on the server: it is signed with the session secret and carries the business, the staff
login (0 for the owner) and the last 16 characters of the password hash, so a new password ends every token issued
before it, the same way it ends panel sessions. A token lives TOKEN_DAYS days.

What a login may do follows the panel: a master's login (PanelUser.staff_id) sees and cancels only her own bookings;
the owner and ordinary staff see the whole business. Settings, channels and payment stay in the panel.
"""

from __future__ import annotations

import threading
import time as time_module
from contextvars import ContextVar
from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from itsdangerous import BadSignature, URLSafeTimedSerializer
from pydantic import BaseModel
from sqlmodel import Session, func, select

from .. import altegio, cash, customers, deposits, order_status, quick_replies, schedule, staff_reply, stays
from ..reschedule import blocked as move_blocked, reschedule
from ..api import _iso, booking_json, customer_json, lead_json, order_json
from ..db import free, new_session
from ..memberships import phone_key
from ..models import Booking, Business, Conversation, Job, Lead, Message, Order, PanelUser, Service, Slot, Staff, Stay
from ..niches import get_pack, picker_packs
from ..phone import normalize_phone
from ..samples import example_staff_ids
from ..security import hash_password, verify_password
from ..signup import Refused, register
from ..catalog import parse_price
from .. import billing, free_plan, page_booking, period_end, telegram_setup, try_chat
from ..slots import (CLOSED, MAX_GENERATE_DAYS, claim_slot, free_on_day, generate_slots, release_slot, resize_group,
                     seats_left, seats_needed)
from ..stats import TEST_CHANNEL, activity, not_test, real_conversation, test_conversations
from ..timeutil import local_now, parse_days_off, parse_hhmm, utc_to_local, utcnow
from .app import _base_url, _by_phone, _delete_service, _login_fails, _retire_staff, _rt, _settings, cancel_booking, client_ip, move_order, record_failure, throttled
from .saas import checklist, unique_slug
from .menu import qr_rows

_LANGUAGE: ContextVar[str] = ContextVar("mobile_language", default="ru")


class _InAppLanguage(APIRoute):
    """Each request runs in the app's language (its Accept-Language header, `_lang`): `_fail` says a refusal in it.
    Set before the endpoint, which a sync endpoint's thread sees as it runs in a copy of this context."""

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def in_language(request: Request):
            token = _LANGUAGE.set(_lang(request))
            try:
                return await handler(request)
            finally:
                _LANGUAGE.reset(token)

        return in_language


router = APIRouter(route_class=_InAppLanguage)

TOKEN_DAYS = 30
SALT = "joop-mobile-v1"
MAX_DAYS = 31  # one bookings call covers at most this many days


class LoginIn(BaseModel):
    company: str
    password: str
    user: str = ""


class Who:
    """The signed-in person: the business and, for a staff login, their PanelUser."""

    def __init__(self, business: Business, user: PanelUser | None):
        self.business, self.user = business, user

    @property
    def master_staff_id(self) -> int | None:
        return self.user.staff_id if self.user and self.user.staff_id else None

    def json(self) -> dict:
        b = self.business
        role = "owner" if self.user is None else ("master" if self.master_staff_id else "staff")
        pack = get_pack(b.niche)
        master = role == "master"  # a master's login opens only her bookings, as in the panel
        return {"business": {"id": b.id, "slug": b.slug, "name": b.name, "niche": b.niche, "timezone": b.timezone,
                             "address": b.address, "phone": b.phone},
                "who": self.user.name if self.user else "Владелец", "role": role,
                "sections": {"bookings": pack.has("booking") or pack.has("request"), "cash": pack.has("booking"),
                             "orders": pack.has("order") and not master, "leads": not master,
                             "stays": pack.has("stay") and not master,
                             "jobs": pack.offers("jobs") and not master},  # «Заказы в работе»: receipts at the counter
                "stay_kind": _stay_kind(pack) if pack.has("stay") else None,
                # the app's people screen (/api/mobile/staff): its title, "" where the app does not edit them
                "people_label": "" if master or b.altegio_location_id else pack.resource_label}


def _stay_kind(pack) -> str:
    """What a stay books: a banquet hall for one date, a car, or a hotel room (the panel's «Брони залов/машин/номеров»)."""
    return "hall" if pack.by_day else "car" if pack.rental else "room"


def _serializer(request: Request) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(_settings(request).session_secret, salt=SALT)


def _fail(status: int, text: str) -> JSONResponse:
    """A refusal, in Kyrgyz for an app in Kyrgyz (joop/errors_ky.py; an unknown sentence stays Russian)."""
    if _LANGUAGE.get() == "ky":
        from ..errors_ky import kyrgyz

        text = kyrgyz(text)
    return JSONResponse({"error": text}, status_code=status, headers={"WWW-Authenticate": "Bearer"} if status == 401 else None)


def _fingerprint(business: Business, user: PanelUser | None) -> str:
    return (user.password_hash if user else business.admin_password_hash)[-16:]


def _signed_in(s: Session, request: Request) -> Who | None:
    header = request.headers.get("authorization", "")
    token = header[7:].strip() if header.lower().startswith("bearer ") else ""
    if not token:
        return None
    try:
        data = _serializer(request).loads(token, max_age=TOKEN_DAYS * 24 * 3600)
    except BadSignature:  # also covers an expired token
        return None
    if not isinstance(data, dict):
        return None
    business = s.get(Business, data.get("b"))
    if business is None:
        return None
    user = None
    if data.get("u"):
        user = s.get(PanelUser, data["u"])
        if user is None or not user.active or user.business_id != business.id:
            return None
    if data.get("p") != _fingerprint(business, user):  # the password changed after this token was issued
        return None
    return Who(business, user)


@router.post("/api/mobile/login")
def mobile_login(request: Request, body: LoginIn):
    company, person, now = body.company.strip().lower(), body.user.strip().lower(), time_module.time()
    key = f"{company}/{person}" if person else company
    if throttled(key, request, now):
        return _fail(429, "Слишком много неудачных попыток. Попробуйте через 15 минут.")
    with new_session() as s:
        business = s.exec(select(Business).where(Business.slug == company)).first() or _by_phone(s, company)
        user = None
        if business is not None and person:
            user = s.exec(select(PanelUser).where(PanelUser.business_id == business.id, PanelUser.login == person,
                                                  PanelUser.active == True)).first()  # noqa: E712
            ok = user is not None and verify_password(body.password, user.password_hash)
        else:
            ok = business is not None and bool(business.admin_password_hash) \
                and verify_password(body.password, business.admin_password_hash)
        if not ok:
            record_failure(key, request, now)
            return _fail(401, "Неверный логин или пароль.")
        _login_fails.pop(f"{key}|{client_ip(request)}", None)
        if user is not None:  # «последний вход» on the panel's and the app's staff list, from the app too
            user.last_login_at = utcnow()
            s.add(user)
            s.commit()
            s.refresh(user)
        token = _serializer(request).dumps({"b": business.id, "u": user.id if user else 0, "p": _fingerprint(business, user)})
        return {"token": token, **Who(business, user).json()}


class SignupIn(BaseModel):
    name: str
    niche: str = "other"
    phone: str
    password: str
    contact_name: str = ""


SIGNUPS_PER_HOUR = 3  # from one address: a real owner signs up once; a script is stopped here
_signups: dict[str, list[float]] = {}  # address -> times of sign-ups this hour; reset with the process
_signups_lock = threading.Lock()  # requests run on a thread pool: the check and the reservation are one step


@router.get("/api/mobile/niches")
def mobile_niches(request: Request):
    """What a business can be, as the sign-up form lists it (the site's /signup shows the same)."""
    if not _settings(request).signup_enabled:
        return _fail(404, "Регистрация закрыта.")
    return {"niches": [{"key": key, "label": pack.label} for key, pack in picker_packs().items()],
            "trial_days": _settings(request).trial_days}


@router.post("/api/mobile/signup")
def mobile_signup(request: Request, body: SignupIn):
    """A business signs itself up from the app, as on the site (joop/signup.py), and is signed in at once."""
    settings, now = _settings(request), time_module.time()
    if not settings.signup_enabled:
        return _fail(404, "Регистрация закрыта.")
    address = client_ip(request)
    with _signups_lock:  # reserve the place before the slow part, so parallel requests cannot all pass the check
        recent = [t for t in _signups.get(address, []) if now - t < 3600]
        if len(recent) >= SIGNUPS_PER_HOUR:
            return _fail(429, "С этого адреса уже зарегистрировали несколько компаний. Попробуйте через час.")
        _signups[address] = recent + [now]

    def give_back() -> None:
        with _signups_lock:
            if now in _signups.get(address, []):
                _signups[address].remove(now)

    with new_session() as s:
        try:
            business = register(s, slug=unique_slug(s, body.name), name=body.name, niche=body.niche, phone=body.phone,
                                password=body.password, trial_days=settings.trial_days, now=utcnow(),
                                contact_name=body.contact_name, source="signup-app")
            s.commit()
        except Refused as refused:
            give_back()  # a refused form is not a sign-up
            return _fail(422, str(refused))
        except Exception:
            give_back()
            raise
        s.refresh(business)
        token = _serializer(request).dumps({"b": business.id, "u": 0, "p": _fingerprint(business, None)})
        return {"token": token, **Who(business, None).json(), "setup_path": "/panel/setup"}


# --- the launch checklist, from the phone (the owner only) ------------------------------------------------------
# The panel's «Запуск» list, as it stands; two of its steps the owner can take right here: the Telegram bot by its
# token, and booking by link without a chat. The rest (prices, people, hours) the app names, with the panel's page.


class TokenIn(BaseModel):
    token: str


class PageBookingIn(BaseModel):
    on: bool


def _owner_only(s: Session, request: Request) -> tuple[Who | None, JSONResponse | None]:
    who = _signed_in(s, request)
    if who is None:
        return None, _fail(401, "Войдите заново.")
    if who.user is not None:
        return None, _fail(403, "Настройки компании меняет владелец.")
    return who, None


def _lang(request: Request) -> str:
    """The app's language, from its Accept-Language header: ky or ru."""
    return "ky" if request.headers.get("accept-language", "").strip().lower().startswith("ky") else "ru"


def _setup(s: Session, request: Request, b: Business) -> dict:
    from .. import checklist_ky

    now = utcnow()
    pack = get_pack(b.niche)
    base = (_settings(request).public_base_url or str(request.base_url)).rstrip("/")
    why = page_booking.unavailable(s, b, now) if pack.has("booking") else "niche"
    ky = _lang(request) == "ky"
    steps = checklist(s, b, now)
    if ky:  # the panel's steps are Russian; an owner who chose Kyrgyz reads them in Kyrgyz
        steps = checklist_ky.kyrgyz(steps, b, pack)
    return {
        "steps": [{"key": i["key"], "done": bool(i["done"]), "title": i["title"], "hint": i["hint"],
                   "panel": f"{base}{i['href']}" if str(i.get("href", "")).startswith("/") else ""}
                  for i in steps],
        "telegram": {"connected": bool(b.telegram_bot_token), "username": b.telegram_bot_username},
        "page_booking": {"available": pack.has("booking") and why != "altegio", "on": bool(b.page_booking and b.menu_enabled),
                         "works": why == "", "why": why, "url": f"{base}/m/{b.slug}/book",
                         "qr": qr_rows(f"{base}/m/{b.slug}/book")},
        # the public page (the panel's «Прайс онлайн» / «Каталог онлайн» / «QR-меню»): prices, contacts and the buttons
        # into the chats; a cafe's guests order from it by table
        "online": {"label": checklist_ky.online_label(pack) if ky else pack.online_label, "on": b.menu_enabled,
                   "tables": pack.serves_tables,
                   "url": f"{base}/m/{b.slug}", "qr": qr_rows(f"{base}/m/{b.slug}")},
    }


@router.get("/api/mobile/setup")
def mobile_setup(request: Request):
    with new_session() as s:
        who, denied = _owner_only(s, request)
        return denied or _setup(s, request, who.business)


@router.post("/api/mobile/setup/telegram")
def mobile_setup_telegram(request: Request, body: TokenIn):
    with new_session() as s:
        who, denied = _owner_only(s, request)
        if denied:
            return denied
        done = telegram_setup.connect(s, _rt(request), _settings(request), who.business, body.token)
        if not done.ok:
            return _fail(422, done.notes[0][0])
        b = s.get(Business, who.business.id)
        return {"notes": [{"text": text, "ok": kind == "ok"} for text, kind in done.notes], **_setup(s, request, b)}


@router.post("/api/mobile/setup/page-booking")
def mobile_setup_page_booking(request: Request, body: PageBookingIn):
    """Booking by link without a chat (joop/page_booking.py). Turning it on opens the public page too, which the
    booking page lives on; turning it off keeps the page."""
    with new_session() as s:
        who, denied = _owner_only(s, request)
        if denied:
            return denied
        b = who.business
        if not get_pack(b.niche).has("booking") or b.altegio_location_id:
            return _fail(409, "В этой сфере клиенты не записываются на время." if not b.altegio_location_id
                         else "Ваш график ведётся в Altegio — для записи по ссылке используйте онлайн-запись Altegio.")
        b.page_booking = body.on
        if body.on:
            b.menu_enabled = True
        s.add(b)
        s.commit()
        s.refresh(b)
        return _setup(s, request, b)


@router.post("/api/mobile/setup/online")
def mobile_setup_online(request: Request, body: PageBookingIn):
    """The public page on or off, as the panel's switch on «Прайс онлайн». Off also stops booking by link, which
    lives on that page; its own switch is kept for when the page is back."""
    with new_session() as s:
        who, denied = _owner_only(s, request)
        if denied:
            return denied
        b = who.business
        b.menu_enabled = body.on
        s.add(b)
        s.commit()
        s.refresh(b)
        return _setup(s, request, b)


# --- contacts and opening hours (the panel's «Настройки», the part the launch list asks for) ---


class ContactsIn(BaseModel):
    address: str = ""
    phone: str = ""
    hours_text: str = ""
    work_start: str = "09:00"
    work_end: str = "18:00"
    days_off: list[int] = []
    # the panel's «Заказы» card, for niches that take orders: som, 0 = not applied
    min_order: int = 0
    delivery_fee: int = 0
    free_delivery_from: int = 0


TERMS_MAX = 10_000_000  # som: a typo of extra zeros is refused rather than held against every order


def _contacts(b: Business) -> dict:
    """`example`: fields still the sign-up example's, which customers are not told (joop/samples.py). `orders`: the
    panel's «Заказы» card (minimum order, delivery fee, free delivery from) for a niche that takes orders, else null;
    its `example` says the sums are the example's, not applied to real customers' orders until changed."""
    from .. import samples

    example = sorted(f for f in samples.example_contacts(b) if f in ("address", "phone"))
    if samples.hours_are_example(b):
        example.append("hours_text")
    orders = {"min_order": b.min_order, "delivery_fee": b.delivery_fee, "free_delivery_from": b.free_delivery_from,
              "example": "order" in samples.example_terms(b)} if get_pack(b.niche).has("order") else None
    return {"address": b.address, "phone": b.phone, "hours_text": b.hours_text, "work_start": b.work_start,
            "work_end": b.work_end, "days_off": sorted(parse_days_off(b.days_off)), "example": example, "orders": orders}


@router.get("/api/mobile/contacts")
def mobile_contacts(request: Request):
    with new_session() as s:
        who, denied = _staff_only(s, request)
        return denied or _contacts(who.business)


@router.post("/api/mobile/contacts")
def mobile_contacts_save(request: Request, body: ContactsIn):
    """What the panel's settings save for these fields, with the same limits; the rest of the settings stay. Only the
    owner, as «Настройки» in the panel; a field not sent keeps its value."""
    sent = body.model_fields_set
    with new_session() as s:
        who, denied = _owner_only(s, request)
        if denied:
            return denied
        b = s.get(Business, who.business.id)
        start = parse_hhmm((body.work_start if "work_start" in sent else b.work_start).strip())
        end = parse_hhmm((body.work_end if "work_end" in sent else b.work_end).strip())
        if not (start and end and end > start):
            return _fail(422, "Конец рабочего дня должен быть позже начала.")
        if "address" in sent:
            b.address = body.address.strip()[:300]
        if "phone" in sent:
            b.phone = body.phone.strip()[:60]
        if "hours_text" in sent:
            b.hours_text = body.hours_text.strip()[:300]
        b.work_start, b.work_end = f"{start:%H:%M}", f"{end:%H:%M}"
        if "days_off" in sent:
            b.days_off = ",".join(str(d) for d in range(1, 8) if d in body.days_off)
        terms = [key for key in ("min_order", "delivery_fee", "free_delivery_from") if key in sent]
        if terms and get_pack(b.niche).has("order"):  # as the panel: below zero is 0, «не применять»
            if any(getattr(body, key) > TERMS_MAX for key in terms):
                return _fail(422, "Слишком большая сумма: проверьте нули.")
            for key in terms:
                setattr(b, key, max(0, getattr(body, key)))
        s.add(b)
        s.commit()
        s.refresh(b)
        return _contacts(b)


# --- the test chat (the panel's «Тестовый чат», joop/try_chat.py): the owner writes as a customer, nothing counted ---


class TryIn(BaseModel):
    text: str


def _try_messages(s: Session, b: Business) -> list[dict]:
    return [{"id": m.id, "role": m.role, "text": m.text, "created_at": m.created_at.isoformat() + "Z", "author": m.author}
            for m in try_chat.messages(s, b) if m.role in ("customer", "ai", "staff")]


@router.get("/api/mobile/try")
def mobile_try(request: Request):
    with new_session() as s:
        who, denied = _owner_only(s, request)
        return denied or {"messages": _try_messages(s, who.business)}


@router.post("/api/mobile/try")
def mobile_try_send(request: Request, body: TryIn):
    if not body.text.strip():
        return _fail(422, "Напишите сообщение.")
    with new_session() as s:
        who, denied = _owner_only(s, request)
        if denied:
            return denied
        business_id = who.business.id
    sent = try_chat.send(_rt(request), business_id, body.text, _base_url(request))
    with new_session() as s:
        return {"notes": [{"text": text, "ok": kind == "ok"} for text, kind in sent.notes],
                "messages": _try_messages(s, s.get(Business, business_id))}


@router.post("/api/mobile/try/reset")
def mobile_try_reset(request: Request):
    """«Новый диалог»: the test's bookings cancelled and their times free again, a fresh chat."""
    with new_session() as s:
        who, denied = _owner_only(s, request)
        if denied:
            return denied
        cancelled = try_chat.reset(s, _rt(request), s.get(Business, who.business.id))
        return {"cancelled": cancelled, "messages": []}


@router.get("/api/mobile/me")
def mobile_me(request: Request):
    with new_session() as s:
        who = _signed_in(s, request)
        if who is None:
            return _fail(401, "Войдите заново.")
        return who.json()


def _day(text: str, today: date) -> date | None:
    if not text:
        return today
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


MAX_SPAN_DAYS = 3 * 366  # a date further away is a typo, and 9999-12-31 + 1 day overflows


def _booking(s: Session, b: Booking) -> dict:
    """booking_json plus the price-list amount to pre-fill the payment with (the panel's Касса does the same), the
    key of the customer's card (customers.cards keys it the same way: the phone, else the chat), and whether the
    booking can still be moved to another time (joop/reschedule.py)."""
    key = customers.key_of(b.customer_phone, b.channel, "")
    if not key and b.conversation_id:
        conv = s.get(Conversation, b.conversation_id)
        key = customers.key_of(conv.customer_phone, conv.channel, conv.chat_id) if conv else ""
    now_local = local_now(s.get(Business, b.business_id).timezone).replace(tzinfo=None)
    deposit = {"due": b.deposit_due, "status": b.deposit_status,
               "deadline": b.deposit_deadline.isoformat() + "Z" if b.deposit_deadline else None} if b.deposit_status else None
    return {**booking_json(b), "customer_key": key, "deposit": deposit,
            "movable": not move_blocked(b, now_local),  # «Перенести» is offered only for a visit that has not happened
            "suggested_som": 0 if b.paid_som or b.status != "booked" else cash.suggested(s, b)}


def _bookings(s: Session, who: Who, first: date, last: date) -> list[Booking]:
    own = [Booking.staff_id == who.master_staff_id] if who.master_staff_id else []
    return list(s.exec(
        select(Booking)
        .where(Booking.business_id == who.business.id, Booking.start >= datetime.combine(first, time.min),
               Booking.start < datetime.combine(last + timedelta(days=1), time.min), not_test(Booking, who.business.id), *own)
        .order_by(Booking.start)
    ).all())


@router.get("/api/mobile/bookings")
def mobile_bookings(request: Request, day: str = "", days: int = 1):
    """Bookings from `day` (YYYY-MM-DD, the business's local date; today when empty) for `days` days, cancelled included."""
    with new_session() as s:
        who = _signed_in(s, request)
        if who is None:
            return _fail(401, "Войдите заново.")
        first = _day(day, local_now(who.business.timezone).date())
        if first is None or abs((first - local_now(who.business.timezone).date()).days) > MAX_SPAN_DAYS:
            return _fail(400, "day: нужна дата в виде 2026-11-20, не дальше трёх лет от сегодня.")
        days = max(1, min(days, MAX_DAYS))
        rows = _bookings(s, who, first, first + timedelta(days=days - 1))
        return {"from": first.isoformat(), "days": days, "bookings": [_booking(s, b) for b in rows]}


@router.get("/api/mobile/summary")
def mobile_summary(request: Request):
    """Counts for the app's home screen: active bookings today, tomorrow and in the next 7 days, and the next visit;
    and `period`: the panel's line while the AI is about to stop or has stopped for payment (joop/period_end.py), with
    `pay_url` for the owner to pay in the browser, None otherwise."""
    with new_session() as s:
        who = _signed_in(s, request)
        if who is None:
            return _fail(401, "Войдите заново.")
        now = local_now(who.business.timezone)
        today = now.date()
        week = [b for b in _bookings(s, who, today, today + timedelta(days=6)) if b.status == "booked"]
        upcoming = [b for b in week if b.start >= now.replace(second=0, microsecond=0)]
        own = [Booking.staff_id == who.master_staff_id] if who.master_staff_id else []
        to_check = s.exec(select(Booking).where(  # the customer sent a receipt, or the deadline passed: someone must look
            Booking.business_id == who.business.id, Booking.status == "booked", Booking.deposit_status.in_(["check", "overdue"]),
            Booking.start >= datetime.combine(today, time.min), not_test(Booking, who.business.id), *own)
            .order_by(Booking.start).limit(20)).all()
        return {"today": sum(1 for b in week if b.start.date() == today),
                "tomorrow": sum(1 for b in week if b.start.date() == today + timedelta(days=1)),
                "week": len(week),
                "next": _booking(s, upcoming[0]) if upcoming else None,
                "deposits": [_booking(s, b) for b in to_check],
                "period": _period_line(s, request, who)}


def _period_line(s: Session, request: Request, who: Who) -> dict | None:
    line = period_end.banner(s, who.business, utcnow())
    if line is None:
        return None
    owner = who.user is None
    pay_url = f"{_base_url(request).rstrip('/')}/panel/billing" if line.pay and owner else None
    return {"level": line.level, "text": line.text, "pay_url": pay_url,
            "ask_owner": line.pay and not owner}  # staff: «Скажите владельцу», as in the panel


RESULT_DAYS = 14


@router.get("/api/mobile/ai-results")
def mobile_ai_results(request: Request):
    """What the AI did in the last 14 days, the figures the panel's Сводка shows (stats.activity): the chats it held,
    how many came after hours, and what it brought — bookings, orders, room bookings, qualified leads — plus the
    questions it handed to people. Only the figures the niche has are sent. The whole business's, so not for a master."""
    with new_session() as s:
        who, denied = _staff_only(s, request)
        if denied:
            return denied
        pack = get_pack(who.business.niche)
        a = activity(s, who.business.id, utcnow() - timedelta(days=RESULT_DAYS))
        out = {"conversations": a["conversations"], "off_hours_conversations": a["off_hours_conversations"]}
        if pack.has("booking"):
            out |= {"bookings": a["bookings"], "off_hours_bookings": a["off_hours_bookings"]}
        if pack.has("order"):
            out["orders"] = a["orders"]
        if pack.has("stay"):
            out["stays"] = a["stays"]
        if pack.has("booking") or pack.has("request"):
            out["requests"] = a["requests"]
        if pack.has("lead"):
            out["qualified"] = a["qualified"]
        out["handed_to_people"] = a["leads"] - a["qualified"]
        return {"days": RESULT_DAYS, "figures": out}


@router.post("/api/mobile/bookings/{item_id}/cancel")
def mobile_cancel(request: Request, item_id: int):
    with new_session() as s:
        who = _signed_in(s, request)
        if who is None:
            return _fail(401, "Войдите заново.")
        booking = s.get(Booking, item_id)
        if booking is None or booking.business_id != who.business.id \
                or (who.master_staff_id and booking.staff_id != who.master_staff_id):
            return _fail(404, "Запись не найдена.")
        told = cancel_booking(s, _rt(request), who.business, booking)
        if told is None:
            return _fail(409, "Запись уже отменена.")
        s.commit()
        s.refresh(booking)
        return {"booking": booking_json(booking), "waitlist_offered": told}


# --- the customer card (the panel's Клиенты) -------------------------------------------------------------
# Assembled by customers.cards from bookings, orders and dialogues; staff add only a note and tags. A master sees
# her own visits of the customer (customers.for_staff), as in the panel.

CARD_BOOKINGS = 20
CARD_ORDERS = 10


def _card(s: Session, who: Who, key: str):
    card = customers.cards(s, who.business).get(key)
    if card is not None and who.master_staff_id:
        card = customers.for_staff(card, who.master_staff_id)
    return card


CUSTOMERS = 100


@router.get("/api/mobile/customers")
def mobile_customers(request: Request, q: str = "", tag: str = ""):
    """The panel's Клиенты: everyone the AI met, newest contact first; `q` finds by name or phone, `tag` by a tag
    staff gave. A master sees the customers who came to her, with her visits only (customers.listing)."""
    with new_session() as s:
        who = _signed_in(s, request)
        if who is None:
            return _fail(401, "Войдите заново.")
        rows = customers.listing(s, who.business, q.strip()[:60], tag.strip()[:60], staff_id=who.master_staff_id)
        everyone = rows if not (q.strip() or tag.strip()) else customers.listing(s, who.business, staff_id=who.master_staff_id)
        return {"customers": [customer_json(c) for c in rows[:CUSTOMERS]], "total": len(rows),
                "tags": sorted({t for c in everyone for t in c.tag_list})}


@router.get("/api/mobile/customers/{key}")
def mobile_customer(request: Request, key: str):
    with new_session() as s:
        who = _signed_in(s, request)
        if who is None:
            return _fail(401, "Войдите заново.")
        card = _card(s, who, key)
        if card is None:
            return _fail(404, "Клиент не найден.")
        upcoming = card.upcoming
        return {"customer": {**customer_json(card), "rating": card.rating,
                             "upcoming": _booking(s, upcoming) if upcoming else None,
                             "bookings": [_booking(s, b) for b in card.bookings[:CARD_BOOKINGS]],
                             "orders": [{**order_json(s, o), "label": order_status.label(o)} for o in card.orders[:CARD_ORDERS]]}}


class NoteIn(BaseModel):
    note: str = ""
    tags: str = ""


@router.post("/api/mobile/customers/{key}")
def mobile_customer_note(request: Request, key: str, body: NoteIn):
    """The note and tags staff keep on the card ("аллергия на лидокаин", "VIP"); the rest is assembled."""
    with new_session() as s:
        who = _signed_in(s, request)
        if who is None:
            return _fail(401, "Войдите заново.")
        if _card(s, who, key) is None:
            return _fail(404, "Клиент не найден.")
        row = customers.save_note(s, who.business, key, body.note, body.tags)
        s.commit()
        return {"note": row.note, "tags": [t.strip() for t in row.tags.split(",") if t.strip()]}


@router.post("/api/mobile/bookings/{item_id}/deposit")
def mobile_deposit_paid(request: Request, item_id: int):
    """Staff saw the prepayment: the panel's «Предоплата получена» (deposits.mark_paid), the customer is told."""
    with new_session() as s:
        who = _signed_in(s, request)
        if who is None:
            return _fail(401, "Войдите заново.")
        booking = s.get(Booking, item_id)
        if booking is None or booking.business_id != who.business.id \
                or (who.master_staff_id and booking.staff_id != who.master_staff_id):
            return _fail(404, "Запись не найдена.")
        told = deposits.mark_paid(s, _rt(request), who.business, booking, utcnow())
        if told is None:
            s.rollback()
            return _fail(409, "Эта запись уже не ждёт предоплаты: её отметили раньше или сняли по сроку.")
        s.commit()
        s.refresh(booking)
        return {"booking": _booking(s, booking), "told": told}


class MoveIn(BaseModel):
    slot_id: int


@router.post("/api/mobile/bookings/{item_id}/move")
def mobile_move(request: Request, item_id: int, body: MoveIn):
    """Move a booking to another free time (joop/reschedule.py): the customer is told in their chat."""
    with new_session() as s:
        who = _signed_in(s, request)
        if who is None:
            return _fail(401, "Войдите заново.")
        b = who.business
        booking, slot = s.get(Booking, item_id), s.get(Slot, body.slot_id)
        own = lambda staff_id: not who.master_staff_id or staff_id == who.master_staff_id  # noqa: E731
        if booking is None or booking.business_id != b.id or not own(booking.staff_id):
            return _fail(404, "Запись не найдена.")
        if slot is None or slot.business_id != b.id or not own(slot.staff_id):
            return _fail(404, "Такого времени нет.")
        moved = reschedule(s, _rt(request), b, booking, slot, local_now(b.timezone).replace(tzinfo=None), utcnow(),
                           hidden_staff=example_staff_ids(s, b))
        if moved.problem:
            s.rollback()
            return _fail(409, moved.problem)
        s.commit()
        s.refresh(booking)
        return {"booking": _booking(s, booking), "told": moved.told}


# --- closing and opening times by hand (joop/schedule.py) ------------------------------------------------
# A doctor is ill: the owner closes her day from the phone, and the AI stops booking into it. The bookings already
# there are returned, to be moved or cancelled. The panel's «Окна», so not for a master.


def _day_slots(s: Session, member: Staff, day: date) -> list[Slot]:
    return list(s.exec(select(Slot).where(Slot.staff_id == member.id, Slot.start >= datetime.combine(day, time.min),
                                          Slot.start < datetime.combine(day + timedelta(days=1), time.min))
                       .order_by(Slot.start)).all())


def _state(slot: Slot) -> str:
    if slot.status == CLOSED:
        return "closed"
    if slot.status == "free":
        return "free"
    return "booked" if slot.taken else "busy"  # busy: marked so by staff, without a booking


def _changed(s: Session, changed: schedule.Changed) -> dict:
    return {"changed": changed.count, "offered": changed.offered, "bookings": [_booking(s, x) for x in changed.bookings]}


@router.get("/api/mobile/schedule")
def mobile_schedule(request: Request, day: str = ""):
    """The day's times that have not started, by person: free, closed, busy or booked (with the customer)."""
    with new_session() as s:
        who, denied = _staff_only(s, request)
        if denied:
            return denied
        b = who.business
        now = local_now(b.timezone).replace(tzinfo=None)
        chosen = _day(day, now.date())
        if chosen is None or abs((chosen - now.date()).days) > MAX_SPAN_DAYS:
            return _fail(400, "day: нужна дата в виде 2026-11-20, не дальше трёх лет от сегодня.")
        hidden = example_staff_ids(s, b)
        people = s.exec(select(Staff).where(Staff.business_id == b.id, Staff.active == True)  # noqa: E712
                        .order_by(Staff.name)).all()
        out = []
        for member in people:
            if member.id in hidden:
                continue
            slots = [x for x in _day_slots(s, member, chosen) if x.start > now]
            booked = {x.slot_id: x for x in s.exec(select(Booking).where(
                Booking.slot_id.in_([x.id for x in slots] or [0]), Booking.status == "booked").order_by(Booking.id)).all()}
            out.append({"id": member.id, "name": member.name, "from_altegio": schedule.from_altegio(b, member),
                        "slots": [{"id": x.id, "start_local": x.start.isoformat(timespec="seconds"), "state": _state(x),
                                   "seats": x.seats, "taken": x.taken,
                                   "customer": booked[x.id].customer_name if x.id in booked and x.seats == 1 else ""}
                                  for x in slots]})
        return {"day": chosen.isoformat(), "staff": out}


class OpenIn(BaseModel):
    open: bool


@router.post("/api/mobile/schedule/slots/{item_id}")
def mobile_schedule_slot(request: Request, item_id: int, body: OpenIn):
    """Close one time, or open a closed or busy one."""
    with new_session() as s:
        who, denied = _staff_only(s, request)
        if denied:
            return denied
        b = who.business
        slot = s.get(Slot, item_id)
        member = s.get(Staff, slot.staff_id) if slot else None
        if slot is None or member is None or slot.business_id != b.id or member.id in example_staff_ids(s, b):
            return _fail(404, "Такого времени нет.")
        now = local_now(b.timezone).replace(tzinfo=None)
        if slot.start <= now:
            return _fail(409, "Это время уже началось.")
        changed = (schedule.reopen(s, _rt(request), b, member, [slot], now, utcnow(), busy_too=True) if body.open
                   else schedule.close(s, b, member, [slot], now))
        if changed.problem:
            return _fail(409, changed.problem)
        s.commit()
        return _changed(s, changed)


class DayIn(BaseModel):
    staff_id: int
    day: str
    open: bool


@router.post("/api/mobile/schedule/day")
def mobile_schedule_day(request: Request, body: DayIn):
    """Close a person's whole day (ill, on leave) or open it again; times already started are left as they are."""
    with new_session() as s:
        who, denied = _staff_only(s, request)
        if denied:
            return denied
        b = who.business
        member = s.get(Staff, body.staff_id)
        if member is None or member.business_id != b.id or member.id in example_staff_ids(s, b):
            return _fail(404, "Такого сотрудника нет.")
        now = local_now(b.timezone).replace(tzinfo=None)
        chosen = _day(body.day, now.date())
        if chosen is None or abs((chosen - now.date()).days) > MAX_SPAN_DAYS:
            return _fail(400, "day: нужна дата в виде 2026-11-20, не дальше трёх лет от сегодня.")
        slots = _day_slots(s, member, chosen)
        changed = (schedule.reopen(s, _rt(request), b, member, slots, now, utcnow()) if body.open
                   else schedule.close(s, b, member, slots, now))
        if changed.problem:
            return _fail(409, changed.problem)
        s.commit()
        return _changed(s, changed)


# --- payment after the visit (the panel's Касса) ---------------------------------------------------------


class PaymentIn(BaseModel):
    amount: int
    method: str = "cash"
    receipt: bool = False


@router.post("/api/mobile/bookings/{item_id}/pay")
def mobile_pay(request: Request, item_id: int, body: PaymentIn):
    """What the customer paid, by method; amount 0 removes a payment recorded by mistake."""
    with new_session() as s:
        who = _signed_in(s, request)
        if who is None:
            return _fail(401, "Войдите заново.")
        booking = s.get(Booking, item_id)
        if booking is None or booking.business_id != who.business.id \
                or (who.master_staff_id and booking.staff_id != who.master_staff_id):
            return _fail(404, "Запись не найдена.")
        if booking.status != "booked":
            return _fail(409, "Запись отменена: оплату к ней не записать.")
        if body.method not in cash.METHODS:
            return _fail(422, "Способ оплаты: наличные, карта или перевод.")
        if not 0 <= body.amount <= cash.MAX_PAYMENT:
            return _fail(422, "Сумма — целое число сомов, не больше 10 000 000.")
        cash.record(booking, body.amount, body.method, utcnow(), receipt=body.receipt)
        s.add(booking)
        s.commit()
        s.refresh(booking)
        return {"booking": _booking(s, booking)}


@router.get("/api/mobile/cash")
def mobile_cash(request: Request, day: str = ""):
    """The day's takings by method, visits that passed without a payment, and the month so far (a master: her own)."""
    with new_session() as s:
        who = _signed_in(s, request)
        if who is None:
            return _fail(401, "Войдите заново.")
        now = local_now(who.business.timezone).replace(tzinfo=None)
        first = _day(day, now.date())
        if first is None or abs((first - now.date()).days) > MAX_SPAN_DAYS:
            return _fail(400, "day: нужна дата в виде 2026-11-20, не дальше трёх лет от сегодня.")
        chosen = datetime.combine(first, time.min)
        d = cash.day(s, who.business, chosen, now, staff_id=who.master_staff_id)
        m = cash.month(s, who.business, chosen, staff_id=who.master_staff_id)
        return {"day": first.isoformat(), "total": d.total, "by_method": d.by_method, "visits": len(d.rows),
                "unpaid": [_booking(s, b) for b in d.unpaid], "month": {"total": m.total, "paid_visits": m.visits}}


# --- a booking made by staff (a customer phoned or walked in) ------------------------------------------
# It takes a free slot the same way the AI does (claim_slot), goes to Altegio when the salon uses it, and is marked
# source="staff", so the AI's figures (stats, the founder digest, the case study) do not count it.


def _free(s: Session, who: Who, day: date, now_local: datetime) -> list[tuple[Slot, Staff]]:
    return free_on_day(s, who.business.id, day, now_local, staff_id=who.master_staff_id,
                       exclude_staff=example_staff_ids(s, who.business))


@router.get("/api/mobile/slots")
def mobile_slots(request: Request, day: str = ""):
    """Free times on `day` (the business's local date; today when empty) that staff can book a customer into."""
    with new_session() as s:
        who = _signed_in(s, request)
        if who is None:
            return _fail(401, "Войдите заново.")
        now = local_now(who.business.timezone)
        first = _day(day, now.date())
        if first is None or abs((first - now.date()).days) > MAX_SPAN_DAYS:
            return _fail(400, "day: нужна дата в виде 2026-11-20, не дальше трёх лет от сегодня.")
        return {"day": first.isoformat(), "slots": [
            {"id": slot.id, "start_local": slot.start.isoformat(timespec="seconds"), "staff_id": member.id,
             "staff": member.name, "seats_left": seats_left(slot), "seats": slot.seats}
            for slot, member in _free(s, who, first, now.replace(tzinfo=None))]}


class NewBookingIn(BaseModel):
    slot_id: int
    name: str
    phone: str = ""
    service: str = ""


@router.post("/api/mobile/bookings")
def mobile_new_booking(request: Request, body: NewBookingIn):
    with new_session() as s:
        who = _signed_in(s, request)
        if who is None:
            return _fail(401, "Войдите заново.")
        name, service = body.name.strip()[:120], body.service.strip()[:200]
        phone = normalize_phone(body.phone) if body.phone.strip() else ""
        if not name:
            return _fail(422, "Укажите имя клиента.")
        if phone is None:
            return _fail(422, "Телефон не похож на номер. Пример: 0555 123 456.")
        b = who.business
        now = local_now(b.timezone).replace(tzinfo=None)
        slot = s.get(Slot, body.slot_id)
        member = s.get(Staff, slot.staff_id) if slot else None
        if slot is None or member is None or slot.business_id != b.id \
                or (who.master_staff_id and member.id != who.master_staff_id) \
                or member.id in example_staff_ids(s, b):  # the sign-up example is nobody: no bookings to it
            return _fail(404, "Такого времени нет.")
        client = _rt(request).altegio(b) if member.external_id else None
        if client is not None and not phone:
            return _fail(422, "Для записи в Altegio нужен телефон клиента.")
        if slot.start <= now or not member.active or not claim_slot(s, slot.id, seats_needed(slot, 1)):
            return _fail(409, "Это время уже занято. Выберите другое.")
        record_id = ""
        if client is not None:
            # The claim is saved first, so Altegio's two calls never hold the database's write lock; a sync that
            # lands before the booking is saved leaves the slot alone (altegio.on_the_way).
            altegio.on_the_way(slot.id, utcnow())
            free(s)
            try:
                record_id = altegio.push_booking(s, b, client, slot, member, service, name, phone or "",
                                                 api_id=f"joop-{b.id}-{slot.id}")
            except Exception as exc:
                if not isinstance(exc, altegio.AltegioError):  # the claim is already saved: give the time back
                    release_slot(s, slot.id, seats_needed(slot, 1))
                    s.commit()
                    raise
                if exc.taken:  # booked in Altegio meanwhile: the slot stays closed here too
                    s.commit()
                    return _fail(409, "В Altegio это время уже занято. Выберите другое.")
                release_slot(s, slot.id, seats_needed(slot, 1))
                s.commit()
                return _fail(502, "Altegio сейчас не отвечает, запись не создана. Попробуйте ещё раз.")
        booking = Booking(business_id=b.id, slot_id=slot.id, staff_id=member.id, staff_name=member.name, start=slot.start,
                          service=service, customer_name=name, customer_phone=phone or "", channel="", source="staff",
                          created_at=utcnow(), external_id=record_id)
        s.add(booking)
        s.commit()
        s.refresh(booking)
        return {"booking": booking_json(booking)}


@router.get("/api/mobile/services")
def mobile_services(request: Request):
    with new_session() as s:
        who = _signed_in(s, request)
        if who is None:
            return _fail(401, "Войдите заново.")
        rows = s.exec(select(Service).where(Service.business_id == who.business.id).order_by(Service.sort, Service.id)).all()
        example = _example_services(s, who.business)
        return {"services": [_service(who.business, x, example) for x in rows]}


def _example_services(s: Session, b: Business) -> frozenset[int]:
    """Price rows still the sign-up example: the AI does not name them to real customers (joop/samples.py)."""
    from .. import samples

    return samples.hidden_from_customers(s, b, "web").services


def _service(b: Business, x: Service, example: frozenset[int] = frozenset()) -> dict:
    """`available`: the AI offers it. `sold_out`: the stock reached zero (joop/stock.py). `from_altegio`: the salon's
    Altegio price list sets it on every sync, so a stop here would not last. `example`: still the sign-up example's."""
    return {"id": x.id, "name": x.name, "name_ky": x.name_ky, "price": x.price, "price_value": x.price_value,
            "note": x.note, "category": x.category, "available": x.available and not x.sold_out, "sold_out": x.sold_out,
            "from_altegio": bool(b.altegio_location_id), "example": x.id in example}


class AvailableIn(BaseModel):
    available: bool


@router.post("/api/mobile/services/{item_id}/available")
def mobile_stop_list(request: Request, item_id: int, body: AvailableIn):
    """The stop list: the AI stops offering an item (a dish ran out, a doctor does not do it this week) and offers it
    again when it is back. What the panel's «В продаже» box does; masters do not edit the price list there either."""
    with new_session() as s:
        who, denied = _staff_only(s, request)
        if denied:
            return denied
        row = s.get(Service, item_id)
        if row is None or row.business_id != who.business.id:
            return _fail(404, "Такой позиции нет.")
        if who.business.altegio_location_id:
            return _fail(409, "Прайс берётся из Altegio: снимите или верните услугу там, Joop подхватит это сам.")
        if row.sold_out and body.available:
            return _fail(409, "Закончилось на складе. Укажите новый остаток в панели («Склад») — позиция вернётся в продажу.")
        row.available = body.available
        s.add(row)
        s.commit()
        s.refresh(row)
        return {"service": _service(who.business, row, _example_services(s, who.business))}


# --- editing the price list (the panel's «Прайс»): the sign-up example out, the business's own prices in ---


class ServiceIn(BaseModel):
    name: str
    price: str = ""
    name_ky: str = ""
    note: str = ""


def _price_list(s: Session, b: Business) -> dict:
    rows = s.exec(select(Service).where(Service.business_id == b.id).order_by(Service.sort, Service.id)).all()
    example = _example_services(s, b)
    return {"services": [_service(b, x, example) for x in rows]}


def _price_editor(s: Session, request: Request) -> tuple[Who | None, JSONResponse | None]:
    """Owner and administrators, as in the panel; not a master, and not a salon whose price list is Altegio's."""
    who, denied = _staff_only(s, request)
    if denied:
        return None, denied
    if who.business.altegio_location_id:
        return None, _fail(409, "Прайс берётся из Altegio: меняйте его там, Joop подхватит изменения сам.")
    return who, None


def _service_row(s: Session, b: Business, item_id: int) -> Service | None:
    row = s.get(Service, item_id)
    return row if row is not None and row.business_id == b.id else None


@router.post("/api/mobile/services")
def mobile_service_add(request: Request, body: ServiceIn):
    with new_session() as s:
        who, denied = _price_editor(s, request)
        if denied:
            return denied
        if not body.name.strip():
            return _fail(422, "Напишите название.")
        b = who.business
        last = s.exec(select(func.max(Service.sort)).where(Service.business_id == b.id)).one() or 0
        s.add(Service(business_id=b.id, name=body.name.strip()[:200], name_ky=body.name_ky.strip()[:200],
                      price=body.price.strip()[:100], price_value=parse_price(body.price), note=body.note.strip()[:500],
                      sort=last + 1))
        s.commit()
        return _price_list(s, b)


@router.post("/api/mobile/services/example/delete")
def mobile_services_example_delete(request: Request):
    """Every row still exactly the sign-up example out in one go, as the panel's «Удалить пример»."""
    with new_session() as s:
        who, denied = _price_editor(s, request)
        if denied:
            return denied
        b = who.business
        ids = _example_services(s, b)
        for item in s.exec(select(Service).where(Service.business_id == b.id, Service.id.in_(ids))).all() if ids else []:
            _delete_service(s, item)
        s.commit()
        return {"removed": len(ids), **_price_list(s, b)}


@router.post("/api/mobile/services/{item_id}")
def mobile_service_update(request: Request, item_id: int, body: ServiceIn):
    """Name, price and note; whether it is on sale stays as it was (the stop list is its own switch)."""
    with new_session() as s:
        who, denied = _price_editor(s, request)
        if denied:
            return denied
        row = _service_row(s, who.business, item_id)
        if row is None:
            return _fail(404, "Такой позиции нет.")
        if not body.name.strip():
            return _fail(422, "Напишите название.")
        row.name, row.name_ky = body.name.strip()[:200], body.name_ky.strip()[:200]
        row.price, row.note = body.price.strip()[:100], body.note.strip()[:500]
        row.price_value = parse_price(row.price)
        s.add(row)
        s.commit()
        return _price_list(s, who.business)


@router.post("/api/mobile/services/{item_id}/delete")
def mobile_service_delete(request: Request, item_id: int):
    with new_session() as s:
        who, denied = _price_editor(s, request)
        if denied:
            return denied
        row = _service_row(s, who.business, item_id)
        if row is None:
            return _fail(404, "Такой позиции нет.")
        _delete_service(s, row)
        s.commit()
        return _price_list(s, who.business)


# --- the business's people (the panel's «Специалисты»): the sign-up example out, its own people in ---


class StaffIn(BaseModel):
    name: str
    role: str = ""
    handles: str = ""
    capacity: int = 0
    group_size: int = 0


def _people(s: Session, b: Business) -> dict:
    """`capacity`: seats of a table or a hall, guests of a room (party-size niches); `group`: places in a group class;
    `units`: how many rooms of the type or cars of the model (`group_size`, from 1; joop/stays.py), `stay_kind` room,
    car or hall for a hotel, a car rental or a banquet hall, else ""."""
    pack = get_pack(b.niche)
    example = example_staff_ids(s, b)
    rows = s.exec(select(Staff).where(Staff.business_id == b.id, Staff.active == True).order_by(Staff.id)).all()  # noqa: E712
    now_local = local_now(b.timezone).replace(tzinfo=None)
    free = dict(s.exec(select(Slot.staff_id, func.count()).where(Slot.business_id == b.id, Slot.status == "free",
                                                                 Slot.start > now_local).group_by(Slot.staff_id)).all())
    return {"label": pack.resource_label, "item": pack.resource_item, "capacity": pack.party_size,
            "group": pack.offers("group_classes"), "booking": pack.has("booking"),
            "units": pack.has("stay") and not pack.by_day, "stay_kind": _stay_kind(pack) if pack.has("stay") else "",
            "work_start": b.work_start, "work_end": b.work_end,
            "staff": [{"id": x.id, "name": x.name, "role": x.role, "handles": x.handles, "capacity": x.capacity,
                       "group_size": x.group_size, "example": x.id in example, "free": free.get(x.id, 0)} for x in rows]}


def _people_editor(s: Session, request: Request) -> tuple[Who | None, JSONResponse | None]:
    """Owner and administrators, as in the panel. Not a master; not a salon whose people come from Altegio. Rooms,
    halls and cars are edited the same way: the panel's «Номера» / «Залы» / «Машины» is the same page."""
    who, denied = _staff_only(s, request)
    if denied:
        return None, denied
    b = who.business
    if b.altegio_location_id:
        return None, _fail(409, "Сотрудники берутся из Altegio: меняйте их там, Joop подхватит изменения сам.")
    return who, None


CAPACITY_MAX = 100_000  # seats of a table or a hall, guests of a room: the panel takes any number; a wedding hall seats 800


def _group_size(b: Business, sent: int) -> int:
    """As the panel's field: rooms of the type or cars of the model from 1 (a stay needs one to be booked); a hall is
    one, its field not shown; a group class 0 (one booking a time) to 500."""
    pack = get_pack(b.niche)
    if pack.has("stay"):
        return 0 if pack.by_day else max(1, min(sent, 500))
    return max(0, min(sent, 500))


def _own_person(s: Session, b: Business, item_id: int) -> Staff | None:
    row = s.get(Staff, item_id)
    return row if row is not None and row.business_id == b.id and row.active else None


@router.get("/api/mobile/staff")
def mobile_staff(request: Request):
    with new_session() as s:
        who, denied = _staff_only(s, request)
        return denied or _people(s, who.business)


@router.post("/api/mobile/staff")
def mobile_staff_add(request: Request, body: StaffIn):
    with new_session() as s:
        who, denied = _people_editor(s, request)
        if denied:
            return denied
        b = who.business
        if not body.name.strip():
            return _fail(422, "Напишите имя.")
        if free_plan.is_free(billing.get_subscription(s, b.id)) and len(free_plan.active_staff(s, b.id)) >= free_plan.MAX_STAFF:
            return _fail(409, free_plan.TOO_MANY)  # the free plan is for one master
        s.add(Staff(business_id=b.id, name=body.name.strip()[:120], role=body.role.strip()[:120],
                    handles=body.handles.strip()[:500], capacity=max(0, min(body.capacity, CAPACITY_MAX)),
                    group_size=_group_size(b, body.group_size)))
        s.commit()
        return _people(s, b)


@router.post("/api/mobile/staff/example/delete")
def mobile_staff_example_delete(request: Request):
    """Every person still exactly the sign-up example retired, with their free times, as the panel's «Удалить пример»."""
    with new_session() as s:
        who, denied = _people_editor(s, request)
        if denied:
            return denied
        b = who.business
        ids = example_staff_ids(s, b)
        for row in s.exec(select(Staff).where(Staff.business_id == b.id, Staff.id.in_(ids))).all() if ids else []:
            _retire_staff(s, b.id, row)
        s.commit()
        return {"removed": len(ids), **_people(s, b)}


@router.post("/api/mobile/staff/{item_id}")
def mobile_staff_update(request: Request, item_id: int, body: StaffIn):
    with new_session() as s:
        who, denied = _people_editor(s, request)
        if denied:
            return denied
        b = who.business
        row = _own_person(s, b, item_id)
        if row is None:
            return _fail(404, "Такого сотрудника нет.")
        if not body.name.strip():
            return _fail(422, "Напишите имя.")
        before = len(free_plan.active_staff(s, b.id))
        row.name, row.role, row.handles = body.name.strip()[:120], body.role.strip()[:120], body.handles.strip()[:500]
        row.capacity = max(0, min(body.capacity, CAPACITY_MAX))
        group_size = _group_size(b, body.group_size)
        if group_size != row.group_size:
            row.group_size = group_size
            resize_group(s, row.id, group_size, local_now(b.timezone).replace(tzinfo=None))
        s.add(row)
        s.flush()
        # an example person turned into a second real one, by any field: seats and group size count too
        if free_plan.breaks_plan(s, b.id, before):
            s.rollback()
            return _fail(409, free_plan.TOO_MANY)
        s.commit()
        return _people(s, b)


class WindowsIn(BaseModel):
    days: int = 14
    step: int = 60
    start: str = ""
    end: str = ""


@router.post("/api/mobile/staff/{item_id}/windows")
def mobile_staff_windows(request: Request, item_id: int, body: WindowsIn):
    """Free times for one person from tomorrow, every `step` minutes between the hours (the business's by default),
    days off skipped, times already there kept: the panel's «Окна для записи» → «Создать», in one tap."""
    with new_session() as s:
        who, denied = _people_editor(s, request)
        if denied:
            return denied
        b = who.business
        if not get_pack(b.niche).has("booking"):
            return _fail(409, "В этой сфере клиенты не записываются на время.")
        row = _own_person(s, b, item_id)
        if row is None:
            return _fail(404, "Такого сотрудника нет.")
        if row.id in example_staff_ids(s, b):
            return _fail(409, "Это пример: к нему клиентов не записывают. Впишите своего человека и откройте окна ему.")
        start, end = parse_hhmm((body.start or b.work_start).strip()), parse_hhmm((body.end or b.work_end).strip())
        if not (start and end and end > start):
            return _fail(422, "Проверьте часы: конец должен быть позже начала.")
        days = max(1, min(body.days, MAX_GENERATE_DAYS))
        tomorrow = local_now(b.timezone).date() + timedelta(days=1)
        created = generate_slots(s, b, row.id, tomorrow, tomorrow + timedelta(days=days - 1), start, end,
                                 max(10, min(body.step, 480)))
        s.commit()
        return {"created": created, **_people(s, b)}


@router.post("/api/mobile/staff/{item_id}/delete")
def mobile_staff_delete(request: Request, item_id: int):
    """Retired, not deleted: bookings keep their person; free times and the person's own login go."""
    with new_session() as s:
        who, denied = _people_editor(s, request)
        if denied:
            return denied
        row = _own_person(s, who.business, item_id)
        if row is None:
            return _fail(404, "Такого сотрудника нет.")
        _retire_staff(s, who.business.id, row)
        s.commit()
        return _people(s, who.business)


# --- orders and requests ---------------------------------------------------------------------------
# Cafes, shops and water delivery work with orders; every niche gets requests (questions the AI handed to staff,
# bookings without a free slot, qualified leads). A master's login has neither, as in the panel.

OPEN_ORDERS = ("new", "accepted", "sent")
RECENT = 30  # closed orders and requests shown after the open ones


def _staff_only(s: Session, request: Request) -> tuple[Who | None, JSONResponse | None]:
    who = _signed_in(s, request)
    if who is None:
        return None, _fail(401, "Войдите заново.")
    if who.master_staff_id:
        return None, _fail(403, "Этот раздел мастеру не открыт.")
    return who, None


ACTIONS = {"accepted": "Принять", "done": "Выполнен", "cancelled": "Отменить"}  # the panel's button words (orders.html)


def _order(s: Session, o: Order) -> dict:
    return {**order_json(s, o), "label": order_status.label(o),
            "next": [{"status": x, "label": order_status.sent_label(o) if x == "sent" else ACTIONS[x]}
                     for x in order_status.NEXT.get(o.status, ())]}


@router.get("/api/mobile/orders")
def mobile_orders(request: Request):
    """Open orders, newest first, then the last RECENT closed ones."""
    with new_session() as s:
        who, denied = _staff_only(s, request)
        if denied:
            return denied
        mine = [Order.business_id == who.business.id, not_test(Order, who.business.id)]
        open_ = s.exec(select(Order).where(*mine, Order.status.in_(OPEN_ORDERS)).order_by(Order.id.desc())).all()
        closed = s.exec(select(Order).where(*mine, Order.status.not_in(OPEN_ORDERS)).order_by(Order.id.desc()).limit(RECENT)).all()
        return {"orders": [_order(s, o) for o in [*open_, *closed]]}


class StatusIn(BaseModel):
    status: str


@router.post("/api/mobile/orders/{item_id}/status")
def mobile_order_move(request: Request, item_id: int, body: StatusIn):
    with new_session() as s:
        who, denied = _staff_only(s, request)
        if denied:
            return denied
        order = s.get(Order, item_id)
        if order is None or order.business_id != who.business.id:
            return _fail(404, "Заказ не найден.")
        if not order_status.can_move(order, body.status):  # another person already moved it, or no such step
            return _fail(409, f"Заказ уже «{order_status.label(order)}».")
        sent, why = move_order(s, _rt(request), who.business, order, body.status, who.json()["who"])
        s.commit()
        s.refresh(order)
        return {"order": _order(s, order),
                "customer_told": sent, "why": why}


def _stay(s: Session, st: Stay, tests: set[int] | None = None) -> dict:
    """A room, car or hall booking as the panel's «Брони» page shows it, with the key of the customer's card."""
    key = customers.key_of(st.customer_phone, st.channel, "")
    if not key and st.conversation_id:
        conv = s.get(Conversation, st.conversation_id)
        key = customers.key_of(conv.customer_phone, conv.channel, conv.chat_id) if conv else ""
    return {"id": st.id, "room": st.room_name, "check_in": st.check_in.isoformat(), "check_out": st.check_out.isoformat(),
            "nights": (st.check_out - st.check_in).days, "guests": st.guests, "customer_name": st.customer_name,
            "customer_phone": st.customer_phone, "customer_key": key, "channel": st.channel,
            "conversation_id": st.conversation_id, "status": st.status, "manual": st.source == "staff",
            # made in a test chat: it still holds real nights, so it is listed (to cancel), marked as a test
            "test": st.channel == TEST_CHANNEL or (tests is not None and st.conversation_id in tests)}


def _stays_business(s: Session, request: Request) -> tuple[Who | None, JSONResponse | None]:
    who, denied = _staff_only(s, request)
    if denied:
        return None, denied
    if not get_pack(who.business.niche).has("stay"):
        return None, _fail(404, "В этой сфере нет броней номеров, машин или залов.")
    return who, None


@router.get("/api/mobile/stays")
def mobile_stays(request: Request):
    """Upcoming stays, as on the panel's page: a hall's event from today on (yesterday's wedding is over), a hotel guest
    or a car until the day they leave; cancelled ones included. A test chat's stay holds real nights: listed, marked."""
    with new_session() as s:
        who, denied = _stays_business(s, request)
        if denied:
            return denied
        pack = get_pack(who.business.niche)
        today = local_now(who.business.timezone).date()
        ahead = Stay.check_in >= today if pack.by_day else Stay.check_out >= today
        rows = s.exec(select(Stay).where(Stay.business_id == who.business.id, ahead).order_by(Stay.check_in, Stay.id)).all()
        tests = set(s.exec(test_conversations(who.business.id)).all())
        return {"kind": _stay_kind(pack), "stays": [_stay(s, st, tests) for st in rows]}


@router.get("/api/mobile/stays/rooms")
def mobile_stay_rooms(request: Request, check_in: str = "", check_out: str = ""):
    """For «Забронировать»: every room type (car, hall) with how many are free for all of these nights."""
    with new_session() as s:
        who, denied = _stays_business(s, request)
        if denied:
            return denied
        b = who.business
        today = local_now(b.timezone).date()
        first = _day(check_in, today)
        if first is not None and not today <= first <= today + timedelta(days=stays.MAX_AHEAD_DAYS):
            return _fail(400, "Даты — с сегодняшнего дня и не дальше чем на год вперёд.")
        if first is not None and stays.by_day(b):
            last = first + timedelta(days=1)  # a hall: one date
        else:
            last = _day(check_out, date.min) if check_out else None
        if first is None or last is None or last <= first or (last - first).days > stays.MAX_NIGHTS:
            return _fail(400, "Нужны даты заезда и выезда в виде 2026-11-20.")
        units = stays.HALL_UNITS if stays.by_day(b) else None
        return {"rooms": [{"id": r.id, "name": r.name, "capacity": r.capacity,
                           "free": stays.free_rooms(s, r, first, last, units)}
                          for r in stays.room_types(s, b.id, frozenset(example_staff_ids(s, b)))]}


class NewStayIn(BaseModel):
    room_id: int
    check_in: str
    check_out: str = ""
    guests: int = 1
    name: str
    phone: str = ""


@router.post("/api/mobile/stays")
def mobile_new_stay(request: Request, body: NewStayIn):
    """A guest who phoned or walked in: booked by staff (not counted as the AI's work), with the AI's rules."""
    with new_session() as s:
        who, denied = _stays_business(s, request)
        if denied:
            return denied
        b = who.business
        name = body.name.strip()[:120]
        phone = normalize_phone(body.phone) if body.phone.strip() else ""
        if not name:
            return _fail(422, "Укажите имя клиента.")
        if phone is None:
            return _fail(422, "Телефон не похож на номер. Пример: 0555 123 456.")
        first, last = _day(body.check_in, date.min), _day(body.check_out, date.min) if body.check_out else None
        if first is None or first == date.min or (body.check_out and last is None):
            return _fail(400, "Нужны даты в виде 2026-11-20.")
        stay, problem = stays.book_by_staff(s, b, body.room_id, first, last, body.guests, name, phone,
                                            local_now(b.timezone).date(), utcnow(), frozenset(example_staff_ids(s, b)))
        if stay is None:
            return _fail(409, problem)
        s.commit()
        s.refresh(stay)
        return {"stay": _stay(s, stay)}


@router.post("/api/mobile/stays/{item_id}/cancel")
def mobile_stay_cancel(request: Request, item_id: int):
    """As the panel's «Отменить»: the room, car or hall is free again for those dates; the customer is told by staff."""
    with new_session() as s:
        who, denied = _stays_business(s, request)
        if denied:
            return denied
        stay = s.get(Stay, item_id)
        if stay is None or stay.business_id != who.business.id:
            return _fail(404, "Бронь не найдена.")
        if stay.status == "booked":
            stays.cancel(s, stay)
            s.commit()
            s.refresh(stay)
        return {"stay": _stay(s, stay)}


def _lead(x: Lead) -> dict:
    return {**lead_json(x), "closed_by": x.closed_by, "conversation_id": x.conversation_id}


@router.get("/api/mobile/leads")
def mobile_leads(request: Request):
    """New requests, newest first, then the last RECENT done ones."""
    with new_session() as s:
        who, denied = _staff_only(s, request)
        if denied:
            return denied
        mine = [Lead.business_id == who.business.id, not_test(Lead, who.business.id)]
        new = s.exec(select(Lead).where(*mine, Lead.status == "new").order_by(Lead.id.desc())).all()
        done = s.exec(select(Lead).where(*mine, Lead.status == "done").order_by(Lead.id.desc()).limit(RECENT)).all()
        return {"leads": [_lead(x) for x in [*new, *done]]}


@router.post("/api/mobile/leads/{item_id}/done")
def mobile_lead_done(request: Request, item_id: int):
    with new_session() as s:
        who, denied = _staff_only(s, request)
        if denied:
            return denied
        lead = s.get(Lead, item_id)
        if lead is None or lead.business_id != who.business.id:
            return _fail(404, "Заявка не найдена.")
        if lead.status != "done":
            lead.status, lead.closed_by = "done", who.json()["who"]
            s.add(lead)
            s.commit()
            s.refresh(lead)
        return {"lead": _lead(lead)}


# --- answering a customer --------------------------------------------------------------------------
# The owner answers a request's customer from the phone, through the customer's channel: the same code as the
# panel's «Ответить» (joop/staff_reply.py), with WhatsApp's and Instagram's 24-hour rule, the AI paused in that chat
# and its open requests closed.

DIALOGUE = 50  # messages shown


def _conversation(s: Session, who: Who, item_id: int) -> Conversation | None:
    conv = s.get(Conversation, item_id)
    return conv if conv is not None and conv.business_id == who.business.id else None


def _dialogue(s: Session, conv: Conversation) -> dict:
    now = utcnow()
    paused = conv.ai_paused_until if conv.ai_paused_until and conv.ai_paused_until > now else None
    rows = list(reversed(s.exec(select(Message).where(Message.conversation_id == conv.id)
                                .order_by(Message.id.desc()).limit(DIALOGUE)).all()))
    b = s.get(Business, conv.business_id)
    return {"id": conv.id, "channel": conv.channel, "customer": {"name": conv.customer_name, "phone": conv.customer_phone},
            "ai_paused": paused is not None,
            "ai_paused_until": paused.isoformat() + "Z" if paused else None,
            # how long a staff reply keeps the AI out of the chat, as the owner chose in the settings
            "takeover_minutes": b.takeover_minutes,
            # the panel's «Готовые ответы», filled for this customer: one tap puts the text into the reply box
            "quick_replies": [{"id": r.id, "title": r.title, "text": quick_replies.fill(r.text, b, conv)}
                              for r in quick_replies.listing(s, b)],
            "reply_blocked": staff_reply.blocked(conv, now),
            "messages": [{"id": m.id, "role": m.role, "text": m.text, "created_at": m.created_at.isoformat() + "Z",
                          "author": m.author} for m in rows if m.role in ("customer", "ai", "staff")]}


CHATS = 100
SEARCHED = 1000  # the most recent chats a search looks through


@router.get("/api/mobile/conversations")
def mobile_conversations(request: Request, q: str = ""):
    """The latest real chats (the panel's Диалоги, test chats left out), newest first, with the last message;
    `q` finds a customer by name or phone. A chat opens with GET /api/mobile/conversations/{id}."""
    with new_session() as s:
        who, denied = _staff_only(s, request)
        if denied:
            return denied
        query = select(Conversation).where(Conversation.business_id == who.business.id, real_conversation())
        convs = s.exec(query.order_by(Conversation.last_message_at.desc()).limit(SEARCHED if q.strip() else CHATS)).all()
        text = q.strip()[:60].casefold()
        if text:  # in Python: SQLite's LIKE ignores case only for Latin letters, and names here are Cyrillic
            digits = "".join(ch for ch in text if ch.isdigit()).lstrip("0")  # «0555 123» is local for +996 555 123
            convs = [c for c in convs if text in (c.customer_name or "").casefold() or text in (c.display_name or "").casefold()
                     or (len(digits) >= 3 and digits in "".join(ch for ch in c.customer_phone if ch.isdigit()))][:CHATS]
        last_ids = s.exec(select(func.max(Message.id)).where(Message.conversation_id.in_([c.id for c in convs] or [0]))
                          .group_by(Message.conversation_id)).all()
        last = {m.conversation_id: m for m in s.exec(select(Message).where(Message.id.in_(list(last_ids) or [0]))).all()}
        now = utcnow()
        return {"conversations": [{
            "id": c.id, "channel": c.channel, "customer": {"name": c.customer_name or c.display_name, "phone": c.customer_phone},
            "last_message_at": c.last_message_at.isoformat() + "Z",
            "last": {"role": last[c.id].role, "text": last[c.id].text[:200]} if c.id in last else None,
            "ai_paused": bool(c.ai_paused_until and c.ai_paused_until > now),
            "blocked": c.blocked_at is not None,
        } for c in convs]}


@router.get("/api/mobile/conversations/{item_id}")
def mobile_conversation(request: Request, item_id: int):
    with new_session() as s:
        who, denied = _staff_only(s, request)
        if denied:
            return denied
        conv = _conversation(s, who, item_id)
        if conv is None:
            return _fail(404, "Диалог не найден.")
        if conv.reviewed_at is None:  # the business's first look, as when the panel opens the dialogue
            conv.reviewed_at = utcnow()
            s.add(conv)
            s.commit()
            s.refresh(conv)
        return _dialogue(s, conv)


class ReplyIn(BaseModel):
    text: str


@router.post("/api/mobile/conversations/{item_id}/reply")
def mobile_reply(request: Request, item_id: int, body: ReplyIn):
    with new_session() as s:
        who, denied = _staff_only(s, request)
        if denied:
            return denied
        conv = _conversation(s, who, item_id)
        if conv is None:
            return _fail(404, "Диалог не найден.")
        sent, problem = staff_reply.send(s, _rt(request), who.business, conv, body.text, utcnow(), author=who.json()["who"])
        s.commit()
        if not sent:
            return _fail(422, problem)
        s.refresh(conv)
        return _dialogue(s, conv)


class AiSwitchIn(BaseModel):
    on: bool
    hours: int = 24


@router.post("/api/mobile/conversations/{item_id}/ai")
def mobile_ai_switch(request: Request, item_id: int, body: AiSwitchIn):
    """Staff take a chat over (the AI stays quiet for `hours`, 1 h to 30 days, 24 by default) or give it back to the
    AI: the panel's «Выключить ИИ» / «Включить ИИ»."""
    with new_session() as s:
        who, denied = _staff_only(s, request)
        if denied:
            return denied
        conv = _conversation(s, who, item_id)
        if conv is None:
            return _fail(404, "Диалог не найден.")
        conv.ai_paused_until = None if body.on else utcnow() + timedelta(hours=max(1, min(body.hours, 24 * 30)))
        s.add(conv)
        s.commit()
        s.refresh(conv)
        return _dialogue(s, conv)


# --- staff logins (the panel's «Доступ сотрудников», joop/web/accounts.py): each master or administrator her own ---


def _logins(s: Session, b: Business) -> dict:
    """The business's staff logins and the people a login can be linked to. Not the sign-up example's people: a
    master's login is for a real master. `company` is what staff type as the company login."""
    from .accounts import MIN_PASSWORD

    users = s.exec(select(PanelUser).where(PanelUser.business_id == b.id).order_by(PanelUser.id)).all()
    people = s.exec(select(Staff).where(Staff.business_id == b.id, Staff.active == True).order_by(Staff.name)).all()  # noqa: E712
    names = {x.id: x.name for x in people}
    example = example_staff_ids(s, b)
    return {"company": b.slug, "min_password": MIN_PASSWORD,
            "masters": get_pack(b.niche).has("booking") and not get_pack(b.niche).has("stay"),
            "people": [{"id": x.id, "name": x.name} for x in people if x.id not in example],
            "users": [{"id": u.id, "name": u.name, "login": u.login, "active": u.active, "staff_id": u.staff_id,
                       "staff_name": names.get(u.staff_id, "") if u.staff_id else "",
                       "last_login_local": utc_to_local(u.last_login_at, b.timezone).isoformat(timespec="minutes")
                       if u.last_login_at else None} for u in users]}


@router.get("/api/mobile/accounts")
def mobile_accounts(request: Request):
    with new_session() as s:
        who, denied = _owner_only(s, request)
        return denied or _logins(s, who.business)


class StaffLoginIn(BaseModel):
    name: str = ""
    login: str = ""
    password: str = ""
    staff_id: int | None = None  # a master: only her bookings, customers and cash


@router.post("/api/mobile/accounts")
def mobile_accounts_add(request: Request, body: StaffLoginIn):
    """A staff login with the panel's rules (joop/web/accounts.add_login). Only the owner, as the panel's page."""
    from .accounts import add_login

    with new_session() as s:
        who, denied = _owner_only(s, request)
        if denied:
            return denied
        b = who.business
        user, problem = add_login(s, b, body.name, body.login, body.password, str(body.staff_id or ""))
        if user is None:
            return _fail(422, problem)
        s.commit()
        return {**_logins(s, b), "added": user.login}


def _own_login(s: Session, b: Business, item_id: int) -> PanelUser | None:
    user = s.get(PanelUser, item_id)
    return user if user is not None and user.business_id == b.id else None


class LoginActiveIn(BaseModel):
    active: bool


@router.post("/api/mobile/accounts/{item_id}/active")
def mobile_accounts_active(request: Request, item_id: int, body: LoginActiveIn):
    """On or off; off ends the login's sessions at its next request (panel and app), as the panel's button."""
    with new_session() as s:
        who, denied = _owner_only(s, request)
        if denied:
            return denied
        user = _own_login(s, who.business, item_id)
        if user is None:
            return _fail(404, "Такого входа нет.")
        user.active = body.active
        s.add(user)
        s.commit()
        return _logins(s, who.business)


class LoginPasswordIn(BaseModel):
    password: str


@router.post("/api/mobile/accounts/{item_id}/password")
def mobile_accounts_password(request: Request, item_id: int, body: LoginPasswordIn):
    """A new password: the login's open sessions end, as a token carries the hash's last characters."""
    from .accounts import MIN_PASSWORD

    with new_session() as s:
        who, denied = _owner_only(s, request)
        if denied:
            return denied
        user = _own_login(s, who.business, item_id)
        if user is None:
            return _fail(404, "Такого входа нет.")
        if len(body.password) < MIN_PASSWORD:
            return _fail(422, f"Пароль должен быть не короче {MIN_PASSWORD} символов.")
        user.password_hash = hash_password(body.password)
        s.add(user)
        s.commit()
        return _logins(s, who.business)


# --- jobs in work ----------------------------------------------------------------------------------
# The panel's «Заказы в работе» (joop/web/jobs.py) on the phone, for a repair shop, a car service, an optician or a
# furniture maker: a receipt taken at the counter, its status, and «готов» sending the customer the panel's message.

JOBS_KEEP = timedelta(days=120)  # as the panel's page: older receipts are not listed
JOBS_DONE = 50
JOBS_OPEN = ("accepted", "in_progress", "ready")


def _jobs_business(s: Session, request: Request) -> tuple[Who | None, JSONResponse | None]:
    who, denied = _staff_only(s, request)
    if denied:
        return None, denied
    if not get_pack(who.business.niche).offers("jobs"):
        return None, _fail(404, "В этой сфере нет заказов в работе.")
    return who, None


def _job(j: Job, labels: dict[str, str], example: frozenset[int]) -> dict:
    return {"id": j.id, "number": j.number, "customer_name": j.customer_name, "customer_phone": j.customer_phone,
            "item": j.item, "status": j.status, "status_label": labels.get(j.status, j.status), "price": j.price,
            "ready_by": j.ready_by.isoformat() if j.ready_by else "", "note": j.note, "ready_notified": j.ready_notified,
            "conversation_id": j.conversation_id, "created_at": _iso(j.created_at), "example": j.id in example}


def _jobs(s: Session, b: Business, q: str = "") -> dict:
    from .. import jobs, samples

    rows = s.exec(select(Job).where(Job.business_id == b.id, Job.created_at >= utcnow() - JOBS_KEEP)
                  .order_by(Job.created_at.desc(), Job.id.desc())).all()
    if q.strip():  # the panel's search: a receipt number, a phone, words of the item or the name
        key, needle = phone_key(q), q.strip().lower()
        rows = [j for j in rows if (key and j.phone_key == key) or j.number == q.strip() or needle in j.item.lower()
                or needle in j.customer_name.lower()]
    pack, labels = get_pack(b.niche), jobs.statuses(b)
    example = samples.hidden_from_customers(s, b, "panel").jobs
    return {"delivered": pack.jobs_delivered, "words": pack.job_words,
            "statuses": [{"key": k, "label": v} for k, v in labels.items()], "next_number": jobs.next_number(s, b.id),
            "open": [_job(j, labels, example) for j in rows if j.status in JOBS_OPEN],
            "done": [_job(j, labels, example) for j in rows if j.status not in JOBS_OPEN][:JOBS_DONE]}


@router.get("/api/mobile/jobs")
def mobile_jobs(request: Request, q: str = ""):
    with new_session() as s:
        who, denied = _jobs_business(s, request)
        if denied:
            return denied
        return _jobs(s, who.business, q)


class JobIn(BaseModel):
    number: str = ""
    customer_name: str = ""
    customer_phone: str = ""
    item: str = ""
    price: str = ""
    ready_by: str = ""  # YYYY-MM-DD or empty
    note: str = ""


@router.post("/api/mobile/jobs")
def mobile_job_add(request: Request, body: JobIn, q: str = ""):
    """A receipt taken at the counter, with the panel's checks: what was left and the customer's phone, by which
    the AI finds the job, and a receipt number not used yet."""
    from .. import jobs
    from .jobs import _date

    with new_session() as s:
        who, denied = _jobs_business(s, request)
        if denied:
            return denied
        b = who.business
        if not body.item.strip() or not phone_key(body.customer_phone):
            what = "что изготавливаем" if get_pack(b.niche).jobs_delivered else "что сдали"
            return _fail(400, f"Укажите, {what}, и телефон клиента — по ним ИИ найдёт заказ.")
        number = body.number.strip()[:20] or jobs.next_number(s, b.id)
        if s.exec(select(Job.id).where(Job.business_id == b.id, Job.number == number)).first():
            return _fail(409, f"Квитанция №{number} уже есть.")
        job = Job(business_id=b.id, number=number, customer_name=body.customer_name.strip()[:120],
                  customer_phone=body.customer_phone.strip()[:40], phone_key=phone_key(body.customer_phone),
                  item=body.item.strip()[:300], price=body.price.strip()[:60], ready_by=_date(body.ready_by),
                  note=body.note.strip()[:300])
        s.add(job)
        s.commit()
        s.refresh(job)
        return {**_jobs(s, b, q), "job": _job(job, jobs.statuses(b), frozenset())}


class JobChangeIn(BaseModel):
    status: str
    note: str = ""
    price: str = ""
    ready_by: str = ""  # empty keeps the date, as the panel's form


@router.post("/api/mobile/jobs/{item_id}")
def mobile_job_change(request: Request, item_id: int, body: JobChangeIn, q: str = ""):
    """A status, note, price or date changed. Becoming «готов» sends the customer the panel's message, once, after
    the change is stored; `customer_told` says whether it went (null: nothing to send)."""
    from .. import jobs, samples
    from .jobs import _date

    if body.status not in jobs.STATUSES:
        return _fail(400, "Нет такого статуса.")
    with new_session() as s:
        who, denied = _jobs_business(s, request)
        if denied:
            return denied
        b = who.business
        job = s.get(Job, item_id)
        if job is None or job.business_id != b.id:
            return _fail(404, "Заказ не найден.")
        became_ready = body.status == "ready" and job.status != "ready"
        job.status, job.note, job.price = body.status, body.note.strip()[:300], body.price.strip()[:60]
        job.ready_by = _date(body.ready_by) if body.ready_by.strip() else job.ready_by
        job.updated_at = utcnow()
        s.add(job)
        s.commit()
        told = None
        if became_ready and not job.ready_notified:
            told = jobs.notify_ready(s, _rt(request), b, job, utcnow())  # the messenger is called outside the write
            s.commit()
        s.refresh(job)
        example = samples.hidden_from_customers(s, b, "panel").jobs
        return {**_jobs(s, b, q), "job": _job(job, jobs.statuses(b), example), "customer_told": told}


@router.post("/api/mobile/jobs/example/delete")
def mobile_jobs_example_delete(request: Request, q: str = ""):
    """The sign-up example's receipts out in one go: fictional customers, known to the test chat only."""
    from .. import samples

    with new_session() as s:
        who, denied = _jobs_business(s, request)
        if denied:
            return denied
        b = who.business
        ids = samples.hidden_from_customers(s, b, "panel").jobs
        for job in s.exec(select(Job).where(Job.business_id == b.id, Job.id.in_(ids))).all() if ids else []:
            s.delete(job)
        s.commit()
        return {**_jobs(s, b, q), "removed": len(ids)}


# --- customers -------------------------------------------------------------------------------------
# A customer opens one business by its code (the slug in its /c/<slug> link or QR code) and chats with its AI
# through the web chat's own API (POST /c/<slug>/chat, GET /c/<slug>/updates). There is no list of all businesses:
# a business joined Joop for its AI administrator, not for a public directory.


@router.get("/api/mobile/places/{slug}")
def mobile_place(request: Request, slug: str):
    """The public card of a business whose web chat is open: what its chat page and price page already show, with
    the Kyrgyz names of its services, and the addresses of its booking page (`book_url`, only while customers can
    book there: page_booking.unavailable) and its public page (`page_url` under `page_label`, while it is open), the
    same the counter card and the QR show."""
    from .. import page_booking, samples
    from .webchat import _business as chat_business

    with new_session() as s:
        try:
            b = chat_business(s, slug.strip().lower())
        except HTTPException:
            return _fail(404, "Такой компании нет или её чат выключен.")
        hidden = samples.hidden_from_customers(s, b, "web")  # the sign-up example's prices and hours are not real
        services = [x for x in s.exec(select(Service).where(Service.business_id == b.id, Service.available == True)  # noqa: E712
                                      .order_by(Service.sort, Service.id)).all()
                    if x.id not in hidden.services and not x.sold_out]
        pack = get_pack(b.niche)
        shown = {f: "" if f in hidden.contacts else getattr(b, f) for f in samples.CONTACTS}
        base = _base_url(request).rstrip("/")
        return {"slug": b.slug, "name": b.name, "niche": b.niche, "description": shown["description"],
                "address": shown["address"], "phone": shown["phone"], "hours": "" if hidden.hours else b.hours_text,
                "booking": pack.has("booking"),
                "book_url": f"{base}/m/{b.slug}/book" if page_booking.unavailable(s, b, utcnow()) == "" else "",
                "page_url": f"{base}/m/{b.slug}" if b.menu_enabled else "", "page_label": pack.online_label,
                "services": [{"id": x.id, "name": x.name, "name_ky": x.name_ky, "price": x.price, "category": x.category}
                             for x in services]}
