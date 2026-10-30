"""Panel page "Заказы в работе": items left for work, their status, and ready notices to customers."""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Form, HTTPException, Request
from sqlmodel import select

from .. import jobs
from ..db import new_session
from ..memberships import phone_key
from ..models import Job
from ..niches import get_pack
from ..timeutil import utcnow
from .app import _back, _business, _check_csrf, _flash, _own, _render, _rt

router = APIRouter()


def _panel_business(s, request: Request):
    b = _business(s, request)
    if not get_pack(b.niche).offers("jobs"):
        raise HTTPException(status_code=404)
    return b


def _date(value: str) -> date | None:
    try:
        return date.fromisoformat(value.strip()) if value.strip() else None
    except ValueError:
        return None


@router.get("/panel/jobs")
def jobs_page(request: Request, q: str = ""):
    with new_session() as s:
        b = _panel_business(s, request)
        rows = s.exec(select(Job).where(Job.business_id == b.id, Job.created_at >= utcnow() - timedelta(days=120))
                      .order_by(Job.created_at.desc())).all()
        if q.strip():
            key, needle = phone_key(q), q.strip().lower()
            rows = [j for j in rows if (key and j.phone_key == key) or j.number == q.strip() or needle in j.item.lower()
                    or needle in j.customer_name.lower()]
        open_rows = [j for j in rows if j.status in {"accepted", "in_progress", "ready"}]
        done_rows = [j for j in rows if j.status not in {"accepted", "in_progress", "ready"}][:50]
        return _render(request, "jobs.html", "jobs", b, open_rows=open_rows, done_rows=done_rows, q=q,
                       statuses=jobs.STATUSES, next_number=jobs.next_number(s, b.id))


@router.post("/panel/jobs")
def job_add(request: Request, number: str = Form(""), customer_name: str = Form(""), customer_phone: str = Form(""),
            item: str = Form(""), price: str = Form(""), ready_by: str = Form(""), note: str = Form(""), csrf: str = Form("")):
    _check_csrf(request, csrf)
    with new_session() as s:
        b = _panel_business(s, request)
        number = number.strip()[:20] or jobs.next_number(s, b.id)
        if not item.strip() or not phone_key(customer_phone):
            _flash(request, "Укажите, что сдали, и телефон клиента — по ним ИИ найдёт заказ.", "error")
            return _back("/panel/jobs")
        if s.exec(select(Job.id).where(Job.business_id == b.id, Job.number == number)).first():
            _flash(request, f"Квитанция №{number} уже есть.", "error")
            return _back("/panel/jobs")
        s.add(Job(business_id=b.id, number=number, customer_name=customer_name.strip()[:120], customer_phone=customer_phone.strip()[:40],
                  phone_key=phone_key(customer_phone), item=item.strip()[:300], price=price.strip()[:60], ready_by=_date(ready_by),
                  note=note.strip()[:300]))
        s.commit()
    _flash(request, f"Заказ №{number} принят. Назовите клиенту номер квитанции: по нему и телефону ИИ ответит, готово ли.")
    return _back("/panel/jobs")


@router.post("/panel/jobs/{item_id}")
def job_update(request: Request, item_id: int, status: str = Form(""), note: str = Form(""), ready_by: str = Form(""),
               price: str = Form(""), csrf: str = Form("")):
    _check_csrf(request, csrf)
    if status not in jobs.STATUSES:
        raise HTTPException(status_code=400)
    with new_session() as s:
        b = _panel_business(s, request)
        job = _own(s, Job, item_id, b.id)
        became_ready = status == "ready" and job.status != "ready"
        job.status, job.note, job.price = status, note.strip()[:300], price.strip()[:60]
        job.ready_by = _date(ready_by) if ready_by.strip() else job.ready_by
        job.updated_at = utcnow()
        s.add(job)
        if became_ready and not job.ready_notified:
            sent = jobs.notify_ready(s, _rt(request), b, job, utcnow())
            _flash(request, f"Заказ №{job.number} готов. " + ("Клиенту отправлено сообщение." if sent else
                   "Написать клиенту не получилось (нет чата или прошло больше суток в WhatsApp) — позвоните: " + job.customer_phone),
                   "ok" if sent else "error")
        else:
            _flash(request, f"Заказ №{job.number}: {jobs.STATUSES[status]}.")
        s.commit()
    return _back("/panel/jobs")
