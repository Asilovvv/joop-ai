"""Panel page "Доступ сотрудников": the owner gives each staff member their own login (models.PanelUser).

Staff log in with the company login plus their own login and password. They see dialogues, bookings, requests,
the price list and the FAQ; settings, channels, payment, broadcasts and this page stay with the owner (app.py,
OWNER_ONLY). Their name is kept next to the replies they send and the requests they close. Turning a login off
ends its open sessions at the next click.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Form, Request
from sqlmodel import select

from ..db import new_session
from ..models import PanelUser
from ..security import hash_password
from .app import _back, _business, _check_csrf, _flash, _own, _render

router = APIRouter()
LOGIN = re.compile(r"^[a-z0-9][a-z0-9._-]{2,31}$")
MIN_PASSWORD = 8
MAX_USERS = 20


@router.get("/panel/accounts")
def accounts_page(request: Request):
    with new_session() as s:
        b = _business(s, request)
        users = s.exec(select(PanelUser).where(PanelUser.business_id == b.id).order_by(PanelUser.id)).all()
        return _render(request, "accounts.html", "accounts", b, users=users, min_password=MIN_PASSWORD)


@router.post("/panel/accounts")
def accounts_add(request: Request, name: str = Form(""), login: str = Form(""), password: str = Form(""), csrf: str = Form("")):
    _check_csrf(request, csrf)
    name, login = " ".join(name.split())[:60], login.strip().lower()
    with new_session() as s:
        b = _business(s, request)
        users = s.exec(select(PanelUser).where(PanelUser.business_id == b.id)).all()
        if not name:
            _flash(request, "Напишите имя сотрудника.", "error")
        elif not LOGIN.match(login):
            _flash(request, "Логин: 3–32 латинские буквы или цифры, можно точку, дефис и подчёркивание.", "error")
        elif any(u.login == login for u in users):
            _flash(request, "Такой логин уже есть.", "error")
        elif len(password) < MIN_PASSWORD:
            _flash(request, f"Пароль должен быть не короче {MIN_PASSWORD} символов.", "error")
        elif len(users) >= MAX_USERS:
            _flash(request, f"Не больше {MAX_USERS} входов на компанию.", "error")
        else:
            s.add(PanelUser(business_id=b.id, name=name, login=login, password_hash=hash_password(password)))
            s.commit()
            _flash(request, f"Вход для «{name}» создан. Сотрудник входит с логином компании «{b.slug}», своим логином «{login}» и паролем.")
    return _back("/panel/accounts")


@router.post("/panel/accounts/{item_id}/toggle")
def accounts_toggle(request: Request, item_id: int, csrf: str = Form("")):
    _check_csrf(request, csrf)
    with new_session() as s:
        b = _business(s, request)
        user = _own(s, PanelUser, item_id, b.id)
        user.active = not user.active
        s.add(user)
        s.commit()
        _flash(request, f"Вход «{user.name}» {'включён' if user.active else 'выключен: сотрудник больше не войдёт в панель'}.")
    return _back("/panel/accounts")


@router.post("/panel/accounts/{item_id}/password")
def accounts_password(request: Request, item_id: int, password: str = Form(""), csrf: str = Form("")):
    _check_csrf(request, csrf)
    with new_session() as s:
        b = _business(s, request)
        user = _own(s, PanelUser, item_id, b.id)
        if len(password) < MIN_PASSWORD:
            _flash(request, f"Пароль должен быть не короче {MIN_PASSWORD} символов.", "error")
        else:
            user.password_hash = hash_password(password)
            s.add(user)
            s.commit()
            _flash(request, f"Пароль для «{user.name}» изменён.")
    return _back("/panel/accounts")
