"""Panel page "Абонементы": passes and packages of visits sold to customers."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Form, HTTPException, Request
from sqlmodel import select

from .. import memberships
from ..db import new_session
from ..models import Membership
from ..niches import get_pack
from .app import _back, _business, _check_csrf, _flash, _now_local, _own, _render

router = APIRouter()


def _panel_business(s, request: Request):
    b = _business(s, request)
    if not get_pack(b.niche).offers("memberships"):
        raise HTTPException(status_code=404)
    return b


def _date(value: str) -> date | None:
    try:
        return date.fromisoformat(value.strip()) if value.strip() else None
    except ValueError:
        return None


@router.get("/panel/memberships")
def memberships_page(request: Request, q: str = ""):
    with new_session() as s:
        b = _panel_business(s, request)
        query = select(Membership).where(Membership.business_id == b.id).order_by(Membership.active.desc(), Membership.created_at.desc())
        rows = s.exec(query).all()
        if q.strip():
            key, needle = memberships.phone_key(q), q.strip().lower()
            rows = [m for m in rows if (key and m.phone_key == key) or needle in m.customer_name.lower() or needle in m.title.lower()]
        today = _now_local(b).date()
        return _render(request, "memberships.html", "memberships", b, rows=rows[:300], q=q, today=today,
                       left=memberships.left, usable=memberships.usable)


@router.post("/panel/memberships")
def membership_add(request: Request, customer_name: str = Form(""), customer_phone: str = Form(""), title: str = Form(""),
                   visits_total: int = Form(0), valid_until: str = Form(""), csrf: str = Form("")):
    _check_csrf(request, csrf)
    with new_session() as s:
        b = _panel_business(s, request)
        key = memberships.phone_key(customer_phone)
        if not key or not title.strip():
            _flash(request, "Укажите телефон клиента и название абонемента.", "error")
            return _back("/panel/memberships")
        s.add(Membership(business_id=b.id, customer_name=customer_name.strip()[:120], customer_phone=customer_phone.strip()[:40],
                         phone_key=key, title=title.strip()[:120], visits_total=max(0, min(visits_total, 1000)),
                         valid_until=_date(valid_until)))
        s.commit()
    _flash(request, "Абонемент добавлен. ИИ ответит клиенту об остатке, когда тот напишет с этого номера в WhatsApp или после первого визита.")
    return _back("/panel/memberships")


@router.post("/panel/memberships/{item_id}")
def membership_action(request: Request, item_id: int, action: str = Form(""), csrf: str = Form("")):
    _check_csrf(request, csrf)
    with new_session() as s:
        b = _panel_business(s, request)
        m = _own(s, Membership, item_id, b.id)
        if action == "visit":
            if m.visits_total and m.visits_used >= m.visits_total:
                _flash(request, "Посещений не осталось.", "error")
            else:
                m.visits_used += 1
                n = memberships.left(m)
                _flash(request, f"Посещение отмечено: {m.customer_name or m.customer_phone}" + (f", осталось {n}." if n is not None else "."))
        elif action == "undo" and m.visits_used > 0:
            m.visits_used -= 1
        elif action in {"close", "open"}:
            m.active = action == "open"
        else:
            raise HTTPException(status_code=400)
        s.add(m)
        s.commit()
    return _back("/panel/memberships")
