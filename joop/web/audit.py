"""The free chat audit page: /audit takes WhatsApp exports, /audit/lead takes the phone for the demo."""

from __future__ import annotations

import logging
import re

from fastapi import APIRouter, File, Form, Request, UploadFile
from sqlmodel import select

from .. import audit, health
from ..db import new_session
from ..models import Prospect
from ..niches import all_packs
from .app import _check_csrf, _csrf, _rt, _site

log = logging.getLogger(__name__)
router = APIRouter()


@router.get("/audit")
def audit_form(request: Request):
    return _site(request, "site_audit.html", csrf=_csrf(request), report=None, error="", work_start="10:00", work_end="20:00")


@router.post("/audit")
async def audit_run(request: Request, chats: list[UploadFile] = File(default=[]), work_start: str = Form("10:00"), work_end: str = Form("20:00"),
                    me: str = Form(""), csrf: str = Form("")):
    _check_csrf(request, csrf)
    parsed = []
    total = 0
    for f in chats[:audit.MAX_FILES]:
        raw = await f.read()
        total += len(raw)
        if total > audit.MAX_BYTES:
            break
        msgs = audit.parse(raw.decode("utf-8", errors="replace"))
        if msgs:
            parsed.append(msgs)
    if not parsed:
        return _site(request, "site_audit.html", csrf=_csrf(request), report=None, work_start=work_start, work_end=work_end,
                     error="Не нашли сообщений WhatsApp в этих файлах. Нужен экспорт чата: в WhatsApp откройте диалог → «Ещё» → "
                           "«Экспорт чата» → «Без файлов», и загрузите полученный .txt.")
    business = me.strip() or audit.guess_business(parsed)
    rep = audit.report(parsed, business, work_start, work_end)
    token = audit.keep(parsed, rep)
    return _site(request, "site_audit.html", csrf=_csrf(request), report=rep, token=token, error="", work_start=work_start,
                 work_end=work_end, summary=audit.summary(rep))


@router.post("/audit/lead")
def audit_lead(request: Request, token: str = Form(""), business: str = Form(""), contact_name: str = Form(""), phone: str = Form(""),
               niche: str = Form("beauty"), csrf: str = Form("")):
    _check_csrf(request, csrf)
    rep = audit.take(token)
    if rep is None:
        return _site(request, "site_audit.html", csrf=_csrf(request), report=None, work_start="10:00", work_end="20:00",
                     error="Разбор устарел — загрузите файлы ещё раз, это секунда.")
    if len(business.strip()) < 2 or len(re.sub(r"\D", "", phone)) < 9:
        return _site(request, "site_audit.html", csrf=_csrf(request), report=rep, token=audit.keep([], rep), summary=audit.summary(rep),
                     work_start="10:00", work_end="20:00", error="Укажите название и телефон или WhatsApp.")
    note = audit.summary(rep)
    with new_session() as s:
        row = s.exec(select(Prospect).where(Prospect.phone == phone.strip())).first() or Prospect(name=business.strip()[:120])
        row.name = business.strip()[:120]
        row.contact_name, row.phone = contact_name.strip()[:80], phone.strip()[:40]
        row.niche = niche if niche in all_packs() else "other"
        row.status = "replied"  # they came to us with their own chats: the warmest lead there is
        row.notes = (f"Аудит переписки с сайта. {note}\n" + row.notes).strip()[:4000]
        s.add(row)
        s.commit()
    try:
        health.tell_founder(_rt(request), f"Joop AI: аудит переписки — «{business.strip()}», {contact_name.strip() or 'без имени'}, "
                                          f"{phone.strip()}. {note} Сделайте демо на их прайсе: консоль → «Продажи».")
    except Exception:
        log.exception("Founder note about an audit lead failed")
    return _site(request, "site_audit.html", csrf=_csrf(request), report=rep, token="", summary=note, work_start="10:00", work_end="20:00",
                 error="", thanks=True)
