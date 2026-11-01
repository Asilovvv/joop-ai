"""Panel page "Рассылки": one message to a group of customers (joop/broadcasts.py)."""

from __future__ import annotations

from fastapi import APIRouter, Request
from sqlmodel import select

from .. import broadcasts
from ..db import new_session
from ..dispatch import admin_chat_ids, notify_admins
from ..models import Broadcast, Service
from ..niches import get_pack
from ..timeutil import utcnow
from .app import _back, _business, _check_csrf, _flash, _own, _render, _rt

router = APIRouter()


def _books(business) -> bool:
    pack = get_pack(business.niche)
    return pack.has("booking") or pack.has("request")


def _page(request: Request, s, b, form: dict | None = None, pv: broadcasts.Preview | None = None):
    books = _books(b)
    services = s.exec(select(Service).where(Service.business_id == b.id).order_by(Service.sort, Service.id)).all() if books else []
    history = s.exec(select(Broadcast).where(Broadcast.business_id == b.id).order_by(Broadcast.id.desc()).limit(20)).all()
    return _render(request, "broadcasts.html", "broadcasts", b, segments=broadcasts.segments_for(books), services=services,
                   history=history, label=broadcasts.segment_label, form=form or {"segment": "all", "days": broadcasts.LAPSED_DAYS},
                   pv=pv, opted_out=broadcasts.opted_out_count(s, b), footer=broadcasts.FOOTER, footer_ky=broadcasts.FOOTER_KY,
                   hours=broadcasts.SEND_HOURS, max_text=broadcasts.MAX_TEXT, linked=bool(admin_chat_ids(b)))


@router.get("/panel/broadcasts")
def broadcasts_page(request: Request):
    with new_session() as s:
        return _page(request, s, _business(s, request))


@router.post("/panel/broadcasts")
async def broadcasts_post(request: Request):
    data = await request.form()
    _check_csrf(request, str(data.get("csrf", "")))
    segment = str(data.get("segment", "all"))
    form = {
        "segment": segment,
        "days": str(data.get("days", "")).strip()[:4] or str(broadcasts.LAPSED_DAYS),
        "service": str(data.get("service", "")).strip()[:120],
        "text": str(data.get("text", "")).strip()[:broadcasts.MAX_TEXT],
        "text_ky": str(data.get("text_ky", "")).strip()[:broadcasts.MAX_TEXT],
    }
    arg = form["days"] if segment == "lapsed" else form["service"] if segment == "service" else ""
    action, now = str(data.get("action", "preview")), utcnow()
    with new_session() as s:
        b = _business(s, request)
        if action == "send":
            item, error = broadcasts.start(s, b, form["text"], form["text_ky"], segment, arg, _books(b), now)
            if item is None:
                _flash(request, error, "error")
                return _page(request, s, b, form, broadcasts.preview(s, b, segment, arg, now))
            s.commit()
            _flash(request, f"Рассылка запущена: {item.total} клиентам. Сообщения уходят партиями с "
                            f"{broadcasts.SEND_HOURS[0]}:00 до {broadcasts.SEND_HOURS[1]}:00, итог придёт вам в Telegram.")
            return _back("/panel/broadcasts")
        if action == "test":
            if not form["text"]:
                _flash(request, "Напишите текст рассылки.", "error")
            else:
                draft = Broadcast(business_id=b.id, text=form["text"], text_ky=form["text_ky"])
                texts = [broadcasts.compose(draft, False)] + ([broadcasts.compose(draft, True)] if form["text_ky"] else [])
                if notify_admins(_rt(request), b, texts):
                    _flash(request, "Пробное сообщение отправлено вам в Telegram.")
                else:
                    _flash(request, "Не получилось отправить: привяжите свой Telegram в «Настройках».", "error")
        return _page(request, s, b, form, broadcasts.preview(s, b, segment, arg, now))


@router.post("/panel/broadcasts/{item_id}/stop")
async def broadcasts_stop(request: Request, item_id: int):
    data = await request.form()
    _check_csrf(request, str(data.get("csrf", "")))
    with new_session() as s:
        b = _business(s, request)
        item = _own(s, Broadcast, item_id, b.id)
        broadcasts.cancel(s, item, utcnow())
        s.commit()
    _flash(request, "Рассылка остановлена.")
    return _back("/panel/broadcasts")
