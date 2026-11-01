"""Panel: the AI drafts the price list and the FAQ from pasted text; the owner checks and adds (joop/autofill.py)."""

from __future__ import annotations

import time

from fastapi import APIRouter, Request
from sqlalchemy import func
from sqlmodel import select

from .. import autofill
from ..catalog import parse_price
from ..db import new_session
from ..followups import _plural
from ..models import Faq, Service
from .app import _back, _business, _check_csrf, _flash, _render, _rt

router = APIRouter()
PER_DAY = 10
_runs: dict[int, list[float]] = {}  # business id -> times of AI drafts in the last day (per process)


@router.post("/panel/autofill")
async def autofill_preview(request: Request):
    form = await request.form()
    _check_csrf(request, str(form.get("csrf", "")))
    back = "/panel/faq" if form.get("back") == "faq" else "/panel/services"
    source = str(form.get("source", "")).strip()
    if not source:
        _flash(request, "Вставьте текст с ценами или ответами на частые вопросы.", "error")
        return _back(back)
    now = time.time()
    with new_session() as s:
        b = _business(s, request)
        recent = [t for t in _runs.get(b.id, []) if now - t < 86400]
        if len(recent) >= PER_DAY:
            _flash(request, f"ИИ разбирает текст до {PER_DAY} раз в сутки. Остальное добавьте вручную.", "error")
            return _back(back)
        _runs[b.id] = recent + [now]
        names = list(s.exec(select(Service.name).where(Service.business_id == b.id)).all())
        questions = list(s.exec(select(Faq.question).where(Faq.business_id == b.id)).all())
        try:
            proposal = autofill.propose(_rt(request).get_llm(), source, names, questions)
        except Exception:
            proposal = None
        if proposal is None:
            _flash(request, "ИИ сейчас не смог разобрать текст. Попробуйте через минуту.", "error")
            return _back(back)
        if proposal.empty:
            _flash(request, "В тексте не нашлось услуг с ценами или ответов на вопросы.", "error")
            return _back(back)
        n = proposal.dropped
        dropped = f"{n} {_plural(n, 'строку', 'строки', 'строк')}" if n else ""
        return _render(request, "autofill.html", "services", b, proposal=proposal, back=back, dropped=dropped,
                       cut=len(source) > autofill.MAX_SOURCE, max_source=autofill.MAX_SOURCE)


@router.post("/panel/autofill/save")
async def autofill_save(request: Request):
    form = await request.form()
    _check_csrf(request, str(form.get("csrf", "")))
    back = "/panel/faq" if form.get("back") == "faq" else "/panel/services"

    def field(key: str, limit: int) -> str:
        return " ".join(str(form.get(key, "")).split())[:limit]

    added_services = added_faq = 0
    with new_session() as s:
        b = _business(s, request)
        have = {n.lower() for n in s.exec(select(Service.name).where(Service.business_id == b.id)).all()}
        asked = {q.lower() for q in s.exec(select(Faq.question).where(Faq.business_id == b.id)).all()}
        sort = s.exec(select(func.max(Service.sort)).where(Service.business_id == b.id)).one() or 0
        for i in range(autofill.MAX_SERVICES):
            name = field(f"s{i}_name", 120)
            if not form.get(f"s{i}_on") or not name or name.lower() in have:
                continue
            price = field(f"s{i}_price", 40)
            sort += 1
            s.add(Service(business_id=b.id, name=name, name_ky=field(f"s{i}_name_ky", 120), price=price,
                          price_value=parse_price(price), note=field(f"s{i}_note", 200), sort=sort))
            have.add(name.lower())
            added_services += 1
        for i in range(autofill.MAX_FAQ):
            q, a = field(f"f{i}_q", 200), field(f"f{i}_a", 500)
            if not form.get(f"f{i}_on") or not q or not a or q.lower() in asked:
                continue
            s.add(Faq(business_id=b.id, question=q, answer=a))
            asked.add(q.lower())
            added_faq += 1
        s.commit()
    if added_services or added_faq:
        _flash(request, f"Добавлено: услуг {added_services}, вопросов {added_faq}. Проверьте их в прайсе и в «Вопросах».")
    else:
        _flash(request, "Ничего не добавлено: не отмечено ни одной строки.", "error")
    return _back(back)


def reset_limits() -> None:
    """For tests."""
    _runs.clear()
