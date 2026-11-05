"""The free chat audit page: /audit takes WhatsApp exports, /audit/lead takes the phone for the demo."""

from __future__ import annotations

import logging
import re
import time

from fastapi import APIRouter, File, Form, Request, UploadFile
from sqlmodel import select

from .. import audit, health
from ..db import new_session
from ..models import Prospect
from ..niches import all_packs
from ..timeutil import utcnow
from .app import _check_csrf, _csrf, _rt, _site

log = logging.getLogger(__name__)
router = APIRouter()
COOLDOWN = 30  # seconds between two leads from one browser, as on every other public form


def _page(request: Request, **ctx):
    base = {"csrf": _csrf(request), "report": None, "error": "", "work_start": "10:00", "work_end": "20:00", "weekend_off": False,
            "packs": {k: p for k, p in all_packs().items()}, "token": ""}
    base.update(ctx)
    return _site(request, "site_audit.html", **base)


@router.get("/audit")
def audit_form(request: Request):
    return _page(request)


@router.post("/audit")
async def audit_run(request: Request, chats: list[UploadFile] = File(default=[]), work_start: str = Form("10:00"), work_end: str = Form("20:00"),
                    weekend_off: str = Form(""), me: str = Form(""), csrf: str = Form("")):
    _check_csrf(request, csrf)
    parsed = []
    total = 0
    for f in chats[:audit.MAX_FILES]:
        raw = await f.read(audit.MAX_BYTES - total + 1)  # never more than the cap into memory
        total += len(raw)
        if total > audit.MAX_BYTES:
            break
        msgs = audit.parse(raw.decode("utf-8", errors="replace"))
        if msgs:
            parsed.append(msgs)
    weekend = bool(weekend_off)
    if not parsed:
        return _page(request, work_start=work_start, work_end=work_end, weekend_off=weekend,
                     error="Не нашли сообщений WhatsApp в этих файлах. Нужен экспорт чата: в WhatsApp откройте диалог → «Ещё» → "
                           "«Экспорт чата» → «Без файлов», и загрузите полученный .txt.")
    business = me.strip() or audit.guess_business(parsed)
    rep = audit.report(parsed, business, work_start, work_end, weekend)
    del parsed  # the chats are not kept: only the numbers
    return _page(request, report=rep, token=audit.keep(rep), work_start=work_start, work_end=work_end, weekend_off=weekend,
                 summary=audit.summary(rep))


@router.post("/audit/lead")
def audit_lead(request: Request, token: str = Form(""), business: str = Form(""), contact_name: str = Form(""), phone: str = Form(""),
               niche: str = Form("other"), website: str = Form(""), csrf: str = Form("")):
    _check_csrf(request, csrf)
    if website or time.time() - float(request.session.get("audit_lead_at", 0) or 0) < COOLDOWN:  # honeypot and the cooldown
        return _page(request)
    rep = audit.take(token)
    if rep is None:
        return _page(request, error="Разбор устарел — загрузите файлы ещё раз, это секунда.")
    if len(business.strip()) < 2 or len(re.sub(r"\D", "", phone)) < 9:
        return _page(request, report=rep, token=audit.keep(rep), summary=audit.summary(rep), error="Укажите название и телефон или WhatsApp.")
    note = audit.summary(rep)
    with new_session() as s:
        row = s.exec(select(Prospect).where(Prospect.phone == phone.strip())).first()
        if row is None:
            row = Prospect(name=business.strip()[:120], contact_name=contact_name.strip()[:80], phone=phone.strip()[:40],
                           niche=niche if niche in all_packs() else "other", status="replied")  # came with their own chats: warm
        elif row.status in ("new", "contacted"):
            row.status = "replied"  # never walk a demo / trial / paid / lost prospect back
        row.notes = (f"Аудит переписки с сайта. {note}\n" + row.notes).strip()[:4000]
        row.updated_at = utcnow()
        s.add(row)
        s.commit()
    request.session["audit_lead_at"] = time.time()
    try:
        health.tell_founder(_rt(request), f"Joop AI: аудит переписки — «{business.strip()}», {contact_name.strip() or 'без имени'}, "
                                          f"{phone.strip()}. {note} Сделайте демо на их прайсе: консоль → «Продажи».")
    except Exception:
        log.exception("Founder note about an audit lead failed")
    return _page(request, report=rep, summary=note, thanks=True)
