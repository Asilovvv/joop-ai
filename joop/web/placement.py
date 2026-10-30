"""Level tests: the school's panel (/panel/tests) and the public test pages (/test/<code>, /t/<token>)."""

from __future__ import annotations

import logging
import re
import time

from fastapi import APIRouter, Form, HTTPException, Request
from sqlmodel import select

from .. import placement
from ..db import new_session
from ..dispatch import notify_admins
from ..models import Business, Conversation, Lead, Message, PlacementAttempt, PlacementTest
from ..studio import phone_digits
from ..timeutil import utcnow
from .app import _back, _business, _check_csrf, _csrf, _flash, _own, _render, _rt, templates

log = logging.getLogger(__name__)
router = APIRouter()

SAMPLE = "Раздел;Вопрос;Вариант 1;Вариант 2;Вариант 3;Вариант 4;Правильный\nГрамматика;She ___ a teacher.;am;is;are;be;2"


def _panel_business(s, request: Request) -> Business:
    b = _business(s, request)
    if not placement.enabled(b):
        raise HTTPException(status_code=404)
    return b


# --- school panel ------------------------------------------------------------------------------


@router.get("/panel/tests")
def tests_page(request: Request):
    with new_session() as s:
        b = _panel_business(s, request)
        rows = placement.stats(s, b.id)
        counts = {t.test.id: len(placement.questions_of(s, t.test.id)) for t in rows}
        recent = s.exec(select(PlacementAttempt).where(PlacementAttempt.business_id == b.id, PlacementAttempt.status == "finished")
                        .order_by(PlacementAttempt.finished_at.desc()).limit(50)).all()
        titles = {t.test.id: t.test.title for t in rows}
        return _render(request, "tests.html", "tests", b, rows=rows, counts=counts, recent=recent, titles=titles,
                       sections=placement.sections)


@router.post("/panel/tests")
def test_add(request: Request, title: str = Form(""), csrf: str = Form("")):
    _check_csrf(request, csrf)
    with new_session() as s:
        b = _panel_business(s, request)
        if not title.strip():
            _flash(request, "Укажите название теста, например «Английский: тест на уровень».", "error")
            return _back("/panel/tests")
        t = PlacementTest(business_id=b.id, code=placement.new_code(), title=title.strip()[:120],
                          scale_text="0-10 A1\n11-20 A2\n21-30 B1\n31-40 B2")
        s.add(t)
        s.commit()
        tid = t.id
    _flash(request, "Тест создан. Проверьте шкалу уровней и загрузите вопросы.")
    return _back(f"/panel/tests/{tid}")


@router.get("/panel/tests/{tid}")
def test_edit(request: Request, tid: int):
    with new_session() as s:
        b = _panel_business(s, request)
        t = _own(s, PlacementTest, tid, b.id)
        questions = placement.questions_of(s, t.id)
        return _render(request, "test_edit.html", "tests", b, t=t, questions=questions, options=placement.options,
                       sample=SAMPLE, link=f"{_base(request)}/test/{t.code}")


@router.post("/panel/tests/{tid}")
def test_save(request: Request, tid: int, title: str = Form(""), scale_text: str = Form(""), minutes: int = Form(20),
              active: str = Form(""), csrf: str = Form("")):
    _check_csrf(request, csrf)
    with new_session() as s:
        b = _panel_business(s, request)
        t = _own(s, PlacementTest, tid, b.id)
        bands, errors = placement.parse_scale(scale_text)
        if errors or not bands:
            for e in errors[:5] or ["Добавьте хотя бы одну строку шкалы, например «0-10 A1»."]:
                _flash(request, e, "error")
            return _back(f"/panel/tests/{tid}")
        t.title = title.strip()[:120] or t.title
        t.scale_text = "\n".join(f"{lo}-{hi} {label}" for lo, hi, label in bands)
        t.minutes = max(0, min(int(minutes or 0), 180))
        t.active = bool(active)
        s.add(t)
        s.commit()
    _flash(request, "Сохранено.")
    return _back(f"/panel/tests/{tid}")


@router.post("/panel/tests/{tid}/questions")
async def test_questions(request: Request, tid: int):
    form = await request.form()
    _check_csrf(request, str(form.get("csrf", "")))
    text = str(form.get("csv", "") or "")
    upload = form.get("file")
    if upload is not None and hasattr(upload, "read"):
        raw = (await upload.read())[:500_000]
        if raw:
            text = raw.decode("utf-8-sig", errors="replace")
    questions, errors = placement.parse_questions(text)
    with new_session() as s:
        b = _panel_business(s, request)
        t = _own(s, PlacementTest, tid, b.id)
        if not questions:
            for e in errors[:5]:
                _flash(request, e, "error")
            return _back(f"/panel/tests/{tid}#import")
        placement.replace_questions(s, t, questions)
        s.commit()
    _flash(request, f"Загружено вопросов: {len(questions)}." + (f" Пропущено строк с ошибками: {len(errors)}." if errors else ""))
    for e in errors[:5]:
        _flash(request, e, "error")
    return _back(f"/panel/tests/{tid}")


def _base(request: Request) -> str:
    from .app import _base_url

    return _base_url(request)


# --- public test pages -------------------------------------------------------------------------


def _page(request: Request, template: str, **ctx):
    ctx.setdefault("flashes", request.session.pop("flash", []))
    ctx.setdefault("csrf", _csrf(request))
    return templates.TemplateResponse(request, template, {"request": request, **ctx})


def _active_test(s, code: str) -> tuple[PlacementTest, Business]:
    t = s.exec(select(PlacementTest).where(PlacementTest.code == code, PlacementTest.active == True)).first()  # noqa: E712
    b = s.get(Business, t.business_id) if t else None
    if t is None or b is None or not placement.questions_of(s, t.id):
        raise HTTPException(status_code=404)
    return t, b


def _attempt(s, token: str) -> tuple[PlacementAttempt, PlacementTest, Business]:
    a = s.exec(select(PlacementAttempt).where(PlacementAttempt.token == token)).first()
    t = s.get(PlacementTest, a.test_id) if a else None
    b = s.get(Business, a.business_id) if a else None
    if a is None or t is None or b is None:
        raise HTTPException(status_code=404)
    return a, t, b


def _valid_contact(name: str, phone: str, consent: str) -> str:
    if len(name.strip()) < 2 or len(re.sub(r"\D", "", phone)) < 9:
        return "Укажите имя и номер телефона."
    if not consent:
        return "Нужно согласие на обработку данных — без него мы не сможем сообщить результат."
    return ""


@router.get("/test/{code}")
def public_start(request: Request, code: str):
    with new_session() as s:
        t, b = _active_test(s, code)
        return _page(request, "test_start.html", t=t, b=b, count=len(placement.questions_of(s, t.id)),
                     action=f"/test/{code}", name="", phone="")


@router.post("/test/{code}")
def public_begin(request: Request, code: str, name: str = Form(""), phone: str = Form(""), consent: str = Form(""),
                 website: str = Form(""), csrf: str = Form("")):
    _check_csrf(request, csrf)
    if website:  # honeypot
        return _back(f"/test/{code}")
    error = _valid_contact(name, phone, consent)
    if error:
        _flash(request, error, "error")
        return _back(f"/test/{code}")
    if time.time() - float(request.session.get("test_at", 0) or 0) < 20:
        _flash(request, "Тест уже начат. Подождите немного, если хотите начать заново.", "error")
        return _back(f"/test/{code}")
    with new_session() as s:
        t, b = _active_test(s, code)
        a = PlacementAttempt(business_id=b.id, test_id=t.id, token=placement.new_token(), status="started",
                             name=name.strip()[:80], phone=phone.strip()[:40], consent=True, started_at=utcnow())
        s.add(a)
        s.commit()
        token = a.token
    request.session["test_at"] = time.time()
    return _back(f"/t/{token}")


@router.get("/t/{token}")
def attempt_page(request: Request, token: str):
    with new_session() as s:
        a, t, b = _attempt(s, token)
        if a.status == "finished":
            return _page(request, "test_result.html", a=a, t=t, b=b, sections=placement.sections(a), wa=phone_digits(b.phone))
        questions = placement.questions_of(s, t.id)
        if a.status == "invited":
            if not t.active or not questions:
                raise HTTPException(status_code=404)
            return _page(request, "test_start.html", t=t, b=b, count=len(questions), action=f"/t/{token}/start",
                         name=a.name, phone=a.phone)
        left = None
        if t.minutes and a.started_at:
            left = max(0, int(t.minutes * 60 - (utcnow() - a.started_at).total_seconds()))
        return _page(request, "test_take.html", a=a, t=t, b=b, questions=questions, options=placement.options, left=left)


@router.post("/t/{token}/start")
def attempt_start(request: Request, token: str, name: str = Form(""), phone: str = Form(""), consent: str = Form(""),
                  csrf: str = Form("")):
    _check_csrf(request, csrf)
    error = _valid_contact(name, phone, consent)
    if error:
        _flash(request, error, "error")
        return _back(f"/t/{token}")
    with new_session() as s:
        a, t, b = _attempt(s, token)
        if a.status == "invited":
            a.status, a.started_at, a.consent = "started", utcnow(), True
            a.name, a.phone = name.strip()[:80], phone.strip()[:40]
            if a.conversation_id:
                conv = s.get(Conversation, a.conversation_id)
                if conv is not None:
                    conv.customer_name = conv.customer_name or a.name
                    conv.customer_phone = conv.customer_phone or a.phone
                    s.add(conv)
            s.add(a)
            s.commit()
    return _back(f"/t/{token}")


@router.post("/t/{token}")
async def attempt_submit(request: Request, token: str):
    form = await request.form()
    _check_csrf(request, str(form.get("csrf", "")))
    now = utcnow()
    with new_session() as s:
        a, t, b = _attempt(s, token)
        if a.status != "started":
            return _back(f"/t/{token}")  # repeated submit or not started: show what there is
        answers: dict[int, int] = {}
        for q in placement.questions_of(s, t.id):
            value = str(form.get(f"q{q.id}", ""))
            if value.isdigit() and int(value) < len(placement.options(q)):
                answers[q.id] = int(value)
        placement.finish(s, t, a, answers, now)
        conv = s.get(Conversation, a.conversation_id) if a.conversation_id else None
        kyrgyz = placement.wants_kyrgyz(s, a)
        note = placement.admin_note(t, a)
        s.add(Lead(business_id=b.id, conversation_id=a.conversation_id, kind="lead", summary=note,
                   details=f"Тест: {t.title}; баллы: {a.score} из {a.max_score}; уровень: {a.level or 'не определён'}",
                   customer_name=a.name, customer_phone=a.phone, channel=conv.channel if conv else "test",
                   chat_id=conv.chat_id if conv else ""))
        reply = placement.result_text(t, a, kyrgyz) if conv else ""
        if conv is not None:
            s.add(Message(business_id=b.id, conversation_id=conv.id, role="ai", text=reply, created_at=now))
            conv.last_message_at = now
            s.add(conv)
        s.commit()
        channel, chat_id, attempt_id = (conv.channel, conv.chat_id, a.id) if conv else ("", "", a.id)
    rt = _rt(request)
    if channel and channel != "console":
        try:
            client = rt.channel_client(b, channel)
            sent = bool(client and client.send_text(chat_id, reply))
        except Exception:
            log.exception("Test result for %s was not delivered", b.slug)
            sent = False
        if sent:
            with new_session() as s:
                a = s.get(PlacementAttempt, attempt_id)
                a.result_sent = True
                s.add(a)
                s.commit()
        else:
            note += " Результат не дошёл до клиента в чат — сообщите ему сами."
    try:
        notify_admins(rt, b, [note])
    except Exception:
        log.exception("Admin note about a test for %s failed", b.slug)
    return _back(f"/t/{token}")
