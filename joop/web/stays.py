"""Panel page "Брони номеров" ("Брони залов" for a banquet hall): stays and a two-week occupancy grid."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Form, HTTPException, Request
from sqlmodel import select

from .. import stays
from ..db import new_session
from ..models import Stay
from ..niches import get_pack
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
        return _render(request, "stays.html", "stays", b, upcoming=upcoming, grid=grid,
                       days=[today + timedelta(days=i) for i in range(14)])


@router.post("/panel/stays/{item_id}/cancel")
def stay_cancel(request: Request, item_id: int, csrf: str = Form("")):
    _check_csrf(request, csrf)
    with new_session() as s:
        b = _panel_business(s, request)
        stay = _own(s, Stay, item_id, b.id)
        if stay.status == "booked":
            stays.cancel(s, stay)
            s.commit()
            freed = ("зал на эту дату снова свободен. Клиенту" if get_pack(b.niche).by_day
                     else "номер на эти даты снова свободен. Гостю")
            _flash(request, f"Бронь {stay.customer_name} отменена, {freed} сообщите сами.")
    return _back("/panel/stays")
