"""Panel page "Доступ сотрудников": the owner gives each staff member their own login (models.PanelUser).

Staff log in with the company login plus their own login and password. They see dialogues, bookings, requests,
the price list and the FAQ; settings, channels, payment, broadcasts and this page stay with the owner (app.py,
OWNER_ONLY). Their name is kept next to the replies they send and the requests they close. Turning a login off
ends its open sessions at the next click.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Form, Request
from sqlmodel import Session, select

from ..db import new_session
from ..models import Business, PanelUser, Staff
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
        staff = s.exec(select(Staff).where(Staff.business_id == b.id, Staff.active == True).order_by(Staff.name)).all()  # noqa: E712
        names = {x.id: x.name for x in staff}
        return _render(request, "accounts.html", "accounts", b, users=users, min_password=MIN_PASSWORD, staff=staff, staff_names=names)


def add_login(s: Session, b: Business, name: str, login: str, password: str, staff_id: str) -> tuple[PanelUser | None, str]:
    """A staff member's own login, or why not: the panel's page and the owner's app share these rules. `staff_id`
    links the login to one of the business's people (a master: only her bookings, customers and cash). The caller
    commits."""
    name, login = " ".join(name.split())[:60], login.strip().lower()
    users = s.exec(select(PanelUser).where(PanelUser.business_id == b.id)).all()
    if not name:
        return None, "Напишите имя сотрудника."
    if not LOGIN.match(login):
        return None, "Логин: 3–32 латинские буквы или цифры, можно точку, дефис и подчёркивание."
    if any(u.login == login for u in users):
        return None, "Такой логин уже есть."
    if len(password) < MIN_PASSWORD:
        return None, f"Пароль должен быть не короче {MIN_PASSWORD} символов."
    if len(users) >= MAX_USERS:
        return None, f"Не больше {MAX_USERS} входов на компанию."
    master = s.get(Staff, int(staff_id)) if staff_id.isascii() and staff_id.isdigit() else None
    linked = master.id if master and master.business_id == b.id else None
    user = PanelUser(business_id=b.id, name=name, login=login, password_hash=hash_password(password), staff_id=linked)
    s.add(user)
    return user, ""


@router.post("/panel/accounts")
def accounts_add(request: Request, name: str = Form(""), login: str = Form(""), password: str = Form(""), staff_id: str = Form(""),
                 csrf: str = Form("")):
    _check_csrf(request, csrf)
    with new_session() as s:
        b = _business(s, request)
        user, problem = add_login(s, b, name, login, password, staff_id)
        if user is None:
            _flash(request, problem, "error")
        else:
            s.commit()
            _flash(request, f"Вход для «{user.name}» создан. Сотрудник входит с логином компании «{b.slug}», своим логином «{user.login}» и паролем.")
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
