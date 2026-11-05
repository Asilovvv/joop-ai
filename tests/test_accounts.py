"""Staff logins to the panel: their own password, daily-work sections only, their name on what they do."""

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from joop import db
from joop.models import Conversation, Lead, Message, PanelUser
from joop.timeutil import utcnow
from joop.web.app import _login_fails, create_app

from .test_web import csrf_of, login


@pytest.fixture
def app(settings, rt, business):
    _login_fails.clear()
    yield create_app(settings, rt, init=False)
    _login_fails.clear()


def staff_login(c, user="aigerim", password="staff-pass-1"):
    token = csrf_of(c.get("/login").text)
    return c.post("/login", data={"slug": "aktish", "user": user, "password": password, "csrf": token}, follow_redirects=False)


def add(owner, **data):
    form = {"name": "Айгерим", "login": "aigerim", "password": "staff-pass-1", **data}
    return owner.post("/panel/accounts", data={"csrf": csrf_of(owner.get("/panel/accounts").text), **form}).text


def test_owner_creates_logins_with_checks(app, business):
    with TestClient(app) as owner:
        login(owner)
        assert "Доступ сотрудников" in owner.get("/panel").text
        assert "Логин: 3–32 латинские буквы" in add(owner, login="Ай")
        assert "не короче 8 символов" in add(owner, password="short")
        assert "Вход для «Айгерим» создан" in add(owner)
        assert "Такой логин уже есть" in add(owner)
    with db.new_session() as s:
        user = s.exec(select(PanelUser)).one()
        assert user.business_id == business.id and user.password_hash.startswith("scrypt$") and "staff-pass-1" not in user.password_hash


def test_staff_see_daily_work_only_and_their_name_stays_on_what_they_do(app, business, rt):
    with TestClient(app) as owner, TestClient(app) as staff:
        login(owner)
        add(owner)
        assert staff_login(staff).status_code == 303
        panel = staff.get("/panel").text
        assert "Айгерим" in panel and 'href="/panel/conversations"' in panel
        for hidden in ("/panel/settings", "/panel/channels", "/panel/billing", "/panel/accounts", "/panel/broadcasts"):
            assert f'href="{hidden}"' not in panel
            r = staff.get(hidden)
            assert r.status_code == 403 and "только владелец" in r.text
        with db.new_session() as s:
            conv = Conversation(business_id=business.id, channel="telegram", chat_id="c1", last_customer_at=utcnow())
            s.add(conv)
            s.flush()
            lead_a = Lead(business_id=business.id, conversation_id=conv.id, summary="Жалоба")
            lead_b = Lead(business_id=business.id, summary="Перезвонить")
            s.add_all([lead_a, lead_b])
            s.commit()
            conv_id, lead_b_id = conv.id, lead_b.id
        page = staff.get(f"/panel/conversations/{conv_id}").text
        staff.post(f"/panel/conversations/{conv_id}/reply", data={"csrf": csrf_of(page), "text": "Здравствуйте!"})
        staff.post(f"/panel/leads/{lead_b_id}/done", data={"csrf": csrf_of(page)})
        assert "Администратор (Айгерим)" in owner.get(f"/panel/conversations/{conv_id}").text
        leads = owner.get("/panel/leads").text
        assert leads.count("закрыл(а): Айгерим") == 2
        with db.new_session() as s:
            assert s.exec(select(Message.author).where(Message.conversation_id == conv_id)).one() == "Айгерим"
            assert s.exec(select(PanelUser.last_login_at)).one() is not None


def test_turning_a_login_off_ends_its_session(app, business):
    with TestClient(app) as owner, TestClient(app) as staff:
        login(owner)
        add(owner)
        staff_login(staff)
        assert staff.get("/panel", follow_redirects=False).status_code == 200
        with db.new_session() as s:
            uid = s.exec(select(PanelUser.id)).one()
        page = owner.get("/panel/accounts").text
        assert "выключен: сотрудник больше не войдёт" in owner.post(f"/panel/accounts/{uid}/toggle", data={"csrf": csrf_of(page)}).text
        r = staff.get("/panel", follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/login"
        assert "Неверный логин или пароль" in staff.post("/login", data={
            "slug": "aktish", "user": "aigerim", "password": "staff-pass-1", "csrf": csrf_of(staff.get("/login").text)}).text


def test_wrong_passwords_and_new_password(app, business):
    with TestClient(app) as owner, TestClient(app) as staff:
        login(owner)
        add(owner)
        assert staff_login(staff, password="secret-pass").headers["location"] == "/login"  # the company password is not theirs
        assert staff_login(staff, user="nobody").headers["location"] == "/login"
        with db.new_session() as s:
            uid = s.exec(select(PanelUser.id)).one()
        page = owner.get("/panel/accounts").text
        assert "Пароль для «Айгерим» изменён" in owner.post(f"/panel/accounts/{uid}/password",
                                                             data={"csrf": csrf_of(page), "password": "new-staff-pass"}).text
        assert staff_login(staff, password="new-staff-pass").headers["location"] == "/panel"
        owner.post(f"/panel/accounts/{uid}/password", data={"csrf": csrf_of(page), "password": "newer-staff-pass"})
        assert staff.get("/panel", follow_redirects=False).headers["location"] == "/login"  # the old session is over
    with TestClient(app) as guesser:
        for _ in range(5):
            staff_login(guesser, password="wrong-pass")
        r = guesser.post("/login", data={"slug": "aktish", "user": "aigerim", "password": "new-staff-pass",
                                         "csrf": csrf_of(guesser.get("/login").text)})
        assert "Слишком много неудачных попыток" in r.text
        login(guesser)  # the owner's login is counted apart from the staff member's


def test_a_masters_login_sees_only_her_own_bookings_customers_and_cash(app, business):
    """A login linked to a Staff row: bookings, customers and the cash page are hers only; the owner sees everything."""
    from datetime import timedelta

    from joop.models import Booking, Staff
    from .conftest import NOW_UTC

    with db.new_session() as s:
        masters = s.exec(select(Staff).where(Staff.business_id == business.id).order_by(Staff.id)).all()
        a, b2 = masters[0], masters[1]
        s.add(Booking(business_id=business.id, staff_id=a.id, staff_name=a.name, customer_name="Клиент А", customer_phone="+996555000001",
                      service="Консультация", start=NOW_UTC + timedelta(days=1), channel="telegram"))
        s.add(Booking(business_id=business.id, staff_id=b2.id, staff_name=b2.name, customer_name="Клиент Б", customer_phone="+996555000002",
                      service="Консультация", start=NOW_UTC + timedelta(days=1), channel="telegram", paid_som=700, paid_method="cash"))
        s.commit()
    with TestClient(app) as owner:
        login(owner)
        page = owner.get("/panel/accounts").text
        assert "Это мастер" in page and a.name in page
        assert f"мастер: {a.name}" in add(owner, staff_id=str(a.id))
        assert "Клиент А" in owner.get("/panel/bookings").text and "Клиент Б" in owner.get("/panel/bookings").text
    with TestClient(app) as master:
        assert staff_login(master).status_code == 303
        bookings = master.get("/panel/bookings").text
        assert "Клиент А" in bookings and "Клиент Б" not in bookings
        customers = master.get("/panel/customers").text
        assert "Клиент А" in customers and "Клиент Б" not in customers
        assert master.get("/panel/customers/555000002").status_code == 404
        assert master.get("/panel/customers/555000001").status_code == 200
        cash_page = master.get("/panel/cash").text
        assert "700" not in cash_page
