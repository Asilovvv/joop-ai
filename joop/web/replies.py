"""Panel page «Готовые ответы»: staff keep the answers they type every day (joop/quick_replies.py)."""

from __future__ import annotations

from fastapi import APIRouter, Form, Request

from .. import quick_replies
from ..db import new_session
from ..models import QuickReply
from .app import _back, _business, _check_csrf, _flash, _own, _render

router = APIRouter()


@router.get("/panel/replies")
def replies_page(request: Request):
    with new_session() as s:
        b = _business(s, request)
        rows = quick_replies.listing(s, b)
        return _render(request, "replies.html", "replies", b, rows=rows, fields=quick_replies.FIELDS,
                       max_title=quick_replies.MAX_TITLE, max_text=quick_replies.MAX_TEXT,
                       previews={r.id: quick_replies.fill(r.text, b) for r in rows})


@router.post("/panel/replies")
def replies_add(request: Request, title: str = Form(""), text: str = Form(""), action: str = Form("add"), csrf: str = Form("")):
    _check_csrf(request, csrf)
    with new_session() as s:
        b = _business(s, request)
        if action == "starters":
            n = quick_replies.add_starters(s, b)
            s.commit()
            _flash(request, f"Добавлено примеров: {n}. Поправьте их под себя." if n else "Примеры уже добавлены.")
            return _back("/panel/replies")
        problem = quick_replies.add(s, b, title, text)
        if problem:
            _flash(request, problem, "error")
        else:
            s.commit()
            _flash(request, "Ответ сохранён. Он появится над полем ответа в каждом диалоге.")
    return _back("/panel/replies")


@router.post("/panel/replies/{item_id}")
def replies_edit(request: Request, item_id: int, title: str = Form(""), text: str = Form(""), action: str = Form("save"),
                 csrf: str = Form("")):
    _check_csrf(request, csrf)
    with new_session() as s:
        b = _business(s, request)
        row = _own(s, QuickReply, item_id, b.id)
        if action == "delete":
            s.delete(row)
            s.commit()
            _flash(request, "Ответ удалён.")
            return _back("/panel/replies")
        title, text = " ".join(title.split())[:quick_replies.MAX_TITLE], text.strip()[:quick_replies.MAX_TEXT]
        if not title or not text:
            _flash(request, "Нужны название и текст ответа.", "error")
            return _back("/panel/replies")
        row.title, row.text = title, text
        s.add(row)
        s.commit()
        _flash(request, "Сохранено.")
    return _back("/panel/replies")
