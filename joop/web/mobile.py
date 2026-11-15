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
from sqlmodel import Session, func, select

from .. import altegio, cash, customers, order_status, staff_reply
from ..reschedule import blocked as move_blocked, reschedule
from ..api import booking_json, customer_json, lead_json, order_json
from ..db import new_session
from ..models import Booking, Business, Conversation, Lead, Message, Order, PanelUser, Service, Slot, Staff
from ..niches import get_pack
from ..phone import normalize_phone
from ..samples import example_staff_ids
from ..security import verify_password
from ..slots import claim_slot, free_on_day, release_slot, seats_left, seats_needed
from ..stats import activity, not_test, real_conversation
from ..timeutil import local_now, utcnow
from .app import _by_phone, _login_fails, _rt, _settings, cancel_booking, client_ip, move_order, record_failure, throttled

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
                             "orders": pack.has("order") and not master, "leads": not master}}


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
    return {**booking_json(b), "customer_key": key,
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
        return {"today": sum(1 for b in week if b.start.date() == today),
                "tomorrow": sum(1 for b in week if b.start.date() == today + timedelta(days=1)),
                "week": len(week),
                "next": _booking(s, upcoming[0]) if upcoming else None}


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
            try:
                record_id = altegio.push_booking(s, b, client, slot, member, service, name, phone or "",
                                                 api_id=f"joop-{b.id}-{slot.id}")
            except altegio.AltegioError as exc:
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
        return {"services": [_service(who.business, x) for x in rows]}


def _service(b: Business, x: Service) -> dict:
    """`available`: the AI offers it. `sold_out`: the stock reached zero (joop/stock.py). `from_altegio`: the salon's
    Altegio price list sets it on every sync, so a stop here would not last."""
    return {"id": x.id, "name": x.name, "name_ky": x.name_ky, "price": x.price, "price_value": x.price_value,
            "category": x.category, "available": x.available and not x.sold_out, "sold_out": x.sold_out,
            "from_altegio": bool(b.altegio_location_id)}


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
        return {"service": _service(who.business, row)}


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
    return {"id": conv.id, "channel": conv.channel, "customer": {"name": conv.customer_name, "phone": conv.customer_phone},
            "ai_paused": paused is not None,
            "ai_paused_until": paused.isoformat() + "Z" if paused else None,
            # how long a staff reply keeps the AI out of the chat, as the owner chose in the settings
            "takeover_minutes": s.get(Business, conv.business_id).takeover_minutes,
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
        return {"slug": b.slug, "name": b.name, "niche": b.niche, "description": b.description, "address": b.address,
                "phone": b.phone, "hours": "" if hidden.hours else b.hours_text, "booking": pack.has("booking"),
                "services": [{"id": x.id, "name": x.name, "price": x.price, "category": x.category} for x in services]}
