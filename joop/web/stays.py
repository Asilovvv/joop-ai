"""Panel page "Брони номеров" ("Брони залов" for a banquet hall): stays and a two-week occupancy grid."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Form, HTTPException, Request
from sqlmodel import select

from .. import stays
from ..db import new_session
from ..models import Stay
from ..niches import get_pack
from ..phone import normalize_phone
from ..samples import example_staff_ids
from ..timeutil import utcnow
from .app import _back, _business, _check_csrf, _flash, _now_local, _own, _render

router = APIRouter()


def _panel_business(s, request: Request):
    b = _business(s, request)
    if not get_pack(b.niche).has("stay"):
        raise HTTPException(status_code=404)
    return b


@router.get("/panel/stays")
def stays_page(request: Request):
    with new_session() as s:
        b = _panel_business(s, request)
        today = _now_local(b).date()
        halls = get_pack(b.niche).by_day
        # A hall's check_out is the day after the event: yesterday's wedding is not upcoming. A hotel guest leaving today is.
        ahead = Stay.check_in >= today if halls else Stay.check_out >= today
        upcoming = s.exec(select(Stay).where(Stay.business_id == b.id, ahead).order_by(Stay.check_in)).all()
        grid = stays.occupancy(s, b.id, today, 14, stays.HALL_UNITS if halls else None)
        rooms = stays.room_types(s, b.id, frozenset(example_staff_ids(s, b)))
        return _render(request, "stays.html", "stays", b, upcoming=upcoming, grid=grid, rooms=rooms, today=today,
                       tomorrow=today + timedelta(days=1), days=[today + timedelta(days=i) for i in range(14)])


@router.post("/panel/stays/new")
def stay_new(request: Request, csrf: str = Form(""), room_id: int = Form(0), check_in: str = Form(""),
             check_out: str = Form(""), guests: int = Form(1), name: str = Form(""), phone: str = Form("")):
    """A guest who phoned or walked in, booked by staff with the AI's rules (as «Забронировать» in the app)."""
    _check_csrf(request, csrf)
    with new_session() as s:
        b = _panel_business(s, request)
        name = name.strip()[:120]
        number = normalize_phone(phone) if phone.strip() else ""
        first, last = stays.parse_day(check_in), stays.parse_day(check_out) if check_out else None
        if not name:
            _flash(request, "Укажите имя клиента.")
        elif number is None:
            _flash(request, "Телефон не похож на номер. Пример: 0555 123 456.")
        elif first is None or (check_out and last is None):
            _flash(request, "Укажите даты.")
        else:
            stay, problem = stays.book_by_staff(s, b, room_id, first, last, guests, name, number, _now_local(b).date(),
                                                utcnow(), frozenset(example_staff_ids(s, b)))
            if stay is None:
                _flash(request, problem)
            else:
                s.commit()
                dates = (stay.check_in.strftime("%d.%m.%Y") if get_pack(b.niche).by_day
                         else f"{stay.check_in:%d.%m}–{stay.check_out:%d.%m}")
                _flash(request, f"Забронировано: {stay.customer_name}, «{stay.room_name}», {dates}.")
    return _back("/panel/stays")


@router.post("/panel/stays/{item_id}/cancel")
def stay_cancel(request: Request, item_id: int, csrf: str = Form("")):
    _check_csrf(request, csrf)
    with new_session() as s:
        b = _panel_business(s, request)
        stay = _own(s, Stay, item_id, b.id)
        if stay.status == "booked":
            stays.cancel(s, stay)
            s.commit()
            pack = get_pack(b.niche)
            freed = ("зал на эту дату снова свободен. Клиенту" if pack.by_day
                     else "машина на эти даты снова свободна. Клиенту" if pack.rental
                     else "номер на эти даты снова свободен. Гостю")
            _flash(request, f"Бронь {stay.customer_name} отменена, {freed} сообщите сами.")
    return _back("/panel/stays")
