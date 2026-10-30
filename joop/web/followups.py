"""Panel page "Отзывы и возврат": rating requests after visits and invitations to come again."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Request
from sqlmodel import select

from .. import followups
from ..db import new_session
from ..models import Booking, Service
from ..timeutil import utcnow
from .app import _back, _business, _check_csrf, _flash, _render

router = APIRouter()
URL_PREFIXES = ("https://2gis.", "https://go.2gis.com/", "https://maps.app.goo.gl/", "https://g.page/",
                "https://www.google.com/maps", "https://maps.google.", "https://yandex.", "https://instagram.com/",
                "https://www.instagram.com/")


@router.get("/panel/followups")
def followups_page(request: Request):
    with new_session() as s:
        b = _business(s, request)
        services = s.exec(select(Service).where(Service.business_id == b.id).order_by(Service.sort, Service.id)).all()
        st = followups.stats(s, b.id, utcnow() - timedelta(days=30))
        recent = s.exec(select(Booking).where(Booking.business_id == b.id, Booking.rating != None)  # noqa: E711
                        .order_by(Booking.start.desc()).limit(30)).all()
        return _render(request, "followups.html", "followups", b, services=services, st=st, recent=recent)


@router.post("/panel/followups")
async def followups_save(request: Request):
    form = await request.form()
    _check_csrf(request, str(form.get("csrf", "")))
    with new_session() as s:
        b = _business(s, request)
        b.review_requests = bool(form.get("review_requests"))
        b.return_invites = bool(form.get("return_invites"))
        b.intake_questions = "\n".join(line.strip()[:200] for line in str(form.get("intake_questions", "")).splitlines()
                                        if line.strip())[:1100]
        try:
            b.loyalty_every = max(0, min(int(str(form.get("loyalty_every") or 0)), 100))
        except ValueError:
            pass
        b.loyalty_reward = str(form.get("loyalty_reward", "")).strip()[:120]
        url = str(form.get("review_url", "")).strip()[:300]
        if url and not url.startswith(URL_PREFIXES):
            _flash(request, "Ссылка на отзывы должна вести на 2ГИС, Google Карты, Яндекс Карты или Instagram — она не сохранена.", "error")
        else:
            b.review_url = url
        s.add(b)
        for service in s.exec(select(Service).where(Service.business_id == b.id)).all():
            key = f"repeat_{service.id}"
            if key in form:
                try:
                    service.repeat_days = max(0, min(365, int(str(form.get(key) or 0))))
                except ValueError:
                    continue
                s.add(service)
        s.commit()
    _flash(request, "Сохранено.")
    return _back("/panel/followups")
