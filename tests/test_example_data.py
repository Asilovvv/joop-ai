"""Sign-up puts the niche's fictional example into a new business so the test chat works at once (joop/samples.py).
The owner must see what is still the example, and the launch checklist must not count it as done."""

from sqlmodel import select

from joop import db, samples
from joop.models import Business, Faq, Service, Staff

from .test_saas import app_client, csrf_of, saas_settings, signup  # noqa: F401  (fixtures)


def business():
    with db.new_session() as s:
        return s.exec(select(Business)).one()


def test_example_is_flagged_until_the_owner_replaces_it(app_client):  # noqa: F811
    signup(app_client)  # a dental clinic: 9 example services, 3 doctors, 3 answers
    with db.new_session() as s:
        found = samples.left(s, business())
    assert (len(found.services), len(found.staff), len(found.faq)) == (9, 3, 3)
    page = app_client.get("/panel").text
    assert "Часть данных — ещё пример" in page and "Замените пример" in page
    assert "из них пример: 9" in app_client.get("/panel/setup").text

    with db.new_session() as s:  # a new price makes the row the clinic's own; deleting removes it
        rows = s.exec(select(Service)).all()
        rows[0].price = "4 000"
        s.add(rows[0])
        for row in rows[1:]:
            s.delete(row)
        s.commit()
        found = samples.left(s, s.exec(select(Business)).one())
    assert found.services == [] and len(found.staff) == 3
    setup = app_client.get("/panel/setup").text
    assert "из них пример" not in setup

    with db.new_session() as s:  # «Убрать» in «Врачи» switches a person off; answers are deleted
        for row in s.exec(select(Staff)).all():
            row.active = False
            s.add(row)
        for row in s.exec(select(Faq)).all():
            s.delete(row)
        s.commit()
    assert "Часть данных — ещё пример" not in app_client.get("/panel").text


def test_owner_can_confirm_that_the_example_rows_are_real(app_client):  # noqa: F811
    signup(app_client)
    token = csrf_of(app_client.get("/panel").text)
    r = app_client.post("/panel/example/ok", data={"csrf": token})
    assert "считаются вашими" in r.text and "Часть данных — ещё пример" not in r.text
    assert business().example_ok is True


def test_connecting_the_bot_says_what_is_still_the_example(app_client, rt):  # noqa: F811
    signup(app_client)
    rt.tg.get_me = lambda: {"username": "clinic_bot"}
    rt.tg.set_webhook = lambda url, secret: True
    token = csrf_of(app_client.get("/panel/setup").text)
    r = app_client.post("/panel/setup/telegram", data={"token": "123456789:" + "D" * 35, "csrf": token})
    assert "Бот @clinic_bot подключён" in r.text and "Ещё из примера — прайс:" in r.text
