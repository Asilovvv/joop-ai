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
from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from itsdangerous import BadSignature, URLSafeTimedSerializer
from pydantic import BaseModel
from sqlmodel import Session, func, select

from .. import altegio, cash, customers, deposits, order_status, quick_replies, schedule, staff_reply, stays
from ..reschedule import blocked as move_blocked, reschedule
from ..api import booking_json, customer_json, lead_json, order_json
from ..db import free, new_session
from ..models import Booking, Business, Conversation, Lead, Message, Order, PanelUser, Service, Slot, Staff, Stay
from ..niches import get_pack, picker_packs
from ..phone import normalize_phone
from ..samples import example_staff_ids
from ..security import verify_password
from ..signup import Refused, register
from ..catalog import parse_price
from .. import page_booking, telegram_setup, try_chat
from ..slots import CLOSED, claim_slot, free_on_day, release_slot, seats_left, seats_needed
from ..stats import TEST_CHANNEL, activity, not_test, real_conversation, test_conversations
from ..timeutil import local_now, utcnow
from .app import _base_url, _by_phone, _delete_service, _login_fails, _rt, _settings, cancel_booking, client_ip, move_order, record_failure, throttled
from .saas import checklist, unique_slug
from .menu import qr_rows

router = APIRouter()

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
                             "stays": pack.has("stay") and not master},
                "stay_kind": _stay_kind(pack) if pack.has("stay") else None}


def _stay_kind(pack) -> str:
    """What a stay books: a banquet hall for one date, a car, or a hotel room (the panel's «Брони залов/машин/номеров»)."""
    return "hall" if pack.by_day else "car" if pack.rental else "room"


def _serializer(request: Request) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(_settings(request).session_secret, salt=SALT)


def _fail(status: int, text: str) -> JSONResponse:
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


def _setup(s: Session, request: Request, b: Business) -> dict:
    now = utcnow()
    pack = get_pack(b.niche)
    base = (_settings(request).public_base_url or str(request.base_url)).rstrip("/")
    why = page_booking.unavailable(s, b, now) if pack.has("booking") else "niche"
    return {
        "steps": [{"key": i["key"], "done": bool(i["done"]), "title": i["title"], "hint": i["hint"],
                   "panel": f"{base}{i['href']}" if str(i.get("href", "")).startswith("/") else ""}
                  for i in checklist(s, b, now)],
        "telegram": {"connected": bool(b.telegram_bot_token), "username": b.telegram_bot_username},
        "page_booking": {"available": pack.has("booking") and why != "altegio", "on": bool(b.page_booking and b.menu_enabled),
                         "works": why == "", "why": why, "url": f"{base}/m/{b.slug}/book",
                         "qr": qr_rows(f"{base}/m/{b.slug}/book")},
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
    """Counts for the app's home screen: active bookings today, tomorrow and in the next 7 days, and the next visit."""
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
                "deposits": [_booking(s, b) for b in to_check]}


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


# --- customers -------------------------------------------------------------------------------------
# A customer opens one business by its code (the slug in its /c/<slug> link or QR code) and chats with its AI
# through the web chat's own API (POST /c/<slug>/chat, GET /c/<slug>/updates). There is no list of all businesses:
# a business joined Joop for its AI administrator, not for a public directory.


@router.get("/api/mobile/places/{slug}")
def mobile_place(slug: str):
    """The public card of a business whose web chat is open: what its chat page and price page already show."""
    from .. import samples
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
        return {"slug": b.slug, "name": b.name, "niche": b.niche, "description": shown["description"],
                "address": shown["address"], "phone": shown["phone"], "hours": "" if hidden.hours else b.hours_text,
                "booking": pack.has("booking"),
                "services": [{"id": x.id, "name": x.name, "price": x.price, "category": x.category} for x in services]}
