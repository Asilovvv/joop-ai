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

import time as time_module
from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from itsdangerous import BadSignature, URLSafeTimedSerializer
from pydantic import BaseModel
from sqlmodel import Session, select

from ..api import booking_json
from ..db import new_session
from ..models import Booking, Business, PanelUser, Service
from ..security import verify_password
from ..stats import TEST_CHANNEL
from ..timeutil import local_now
from .app import _by_phone, _login_fails, _rt, _settings, cancel_booking, client_ip, record_failure, throttled

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
        return {"business": {"id": b.id, "slug": b.slug, "name": b.name, "niche": b.niche, "timezone": b.timezone,
                             "address": b.address, "phone": b.phone},
                "who": self.user.name if self.user else "Владелец", "role": role}


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


def _bookings(s: Session, who: Who, first: date, last: date) -> list[Booking]:
    own = [Booking.staff_id == who.master_staff_id] if who.master_staff_id else []
    return list(s.exec(
        select(Booking)
        .where(Booking.business_id == who.business.id, Booking.start >= datetime.combine(first, time.min),
               Booking.start < datetime.combine(last + timedelta(days=1), time.min), Booking.channel != TEST_CHANNEL, *own)
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
        if first is None:
            return _fail(400, "day: нужна дата в виде 2026-11-20.")
        days = max(1, min(days, MAX_DAYS))
        rows = _bookings(s, who, first, first + timedelta(days=days - 1))
        return {"from": first.isoformat(), "days": days, "bookings": [booking_json(b) for b in rows]}


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
        return {"today": sum(1 for b in week if b.start.date() == today),
                "tomorrow": sum(1 for b in week if b.start.date() == today + timedelta(days=1)),
                "week": len(week),
                "next": booking_json(upcoming[0]) if upcoming else None}


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


@router.get("/api/mobile/services")
def mobile_services(request: Request):
    with new_session() as s:
        who = _signed_in(s, request)
        if who is None:
            return _fail(401, "Войдите заново.")
        rows = s.exec(select(Service).where(Service.business_id == who.business.id).order_by(Service.sort, Service.id)).all()
        return {"services": [{"id": x.id, "name": x.name, "name_ky": x.name_ky, "price": x.price, "price_value": x.price_value,
                              "category": x.category, "available": x.available and not x.sold_out} for x in rows]}


# --- customers -------------------------------------------------------------------------------------
# A customer opens one business by its code (the slug in its /c/<slug> link or QR code) and chats with its AI
# through the web chat's own API (POST /c/<slug>/chat, GET /c/<slug>/updates). There is no list of all businesses:
# a business joined Joop for its AI administrator, not for a public directory.


@router.get("/api/mobile/places/{slug}")
def mobile_place(slug: str):
    """The public card of a business whose web chat is open: what its chat page and price page already show."""
    from .. import samples
    from ..niches import get_pack
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
        return {"slug": b.slug, "name": b.name, "niche": b.niche, "description": b.description, "address": b.address,
                "phone": b.phone, "hours": "" if hidden.hours else b.hours_text, "booking": pack.has("booking"),
                "services": [{"id": x.id, "name": x.name, "price": x.price, "category": x.category} for x in services]}
