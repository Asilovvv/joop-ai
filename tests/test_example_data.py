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


def _clinic():
    from joop.presets import create_business

    from .conftest import NOW_UTC

    with db.new_session() as s:  # signed up a minute ago: everything is still the example
        b = create_business(s, slug="new-clinic", name="Новая клиника", password="secret-pass", niche="dental", demo=True,
                            now_utc=NOW_UTC)
        s.commit()
        return b.id


def _ask(bid, channel, text="Сколько стоит чистка и когда можно прийти?", llm=None):
    from joop.agent.engine import handle_incoming
    from joop.channels.base import IncomingMessage

    from .conftest import NOW_UTC, FakeLLM

    llm = llm or FakeLLM()
    with db.new_session() as s:
        out = handle_incoming(s, s.get(Business, bid), IncomingMessage(channel, "c1", "text", text, "", f"{channel}:{text}"),
                              lambda: llm, NOW_UTC)
        s.commit()
    return out, (llm.calls[0]["system"] if llm.calls else "")


def test_real_customers_never_get_the_example_but_the_test_chat_does(engine):
    bid = _clinic()
    with db.new_session() as s:
        found = samples.left(s, s.get(Business, bid))
        answers = [f.answer for f in s.exec(select(Faq)).all()]
    _, system = _ask(bid, "telegram")
    assert not any(name in system for name in found.services + found.staff + answers)
    assert "список не заполнен, цены уточняет администратор" in system and "Свободного времени в системе нет" in system
    _, system = _ask(bid, "console")  # the owner trying the AI sees how it works with the example
    assert all(name in system for name in found.services[:3] + found.staff)


def test_a_time_of_an_example_person_cannot_be_booked_by_a_real_customer(engine):
    from joop.agent.llm import AgentReply
    from joop.models import Slot

    from .conftest import FakeLLM

    bid = _clinic()
    with db.new_session() as s:
        slot = s.exec(select(Slot).where(Slot.status == "free").order_by(Slot.start)).first()
    llm = FakeLLM([AgentReply("Записала!", booking={"slot_id": slot.id, "name": "Айбек", "phone": "0555123456"})])
    out, _ = _ask(bid, "telegram", "Запишите меня, Айбек, 0555123456", llm)
    assert out.booking_id is None
    with db.new_session() as s:
        assert s.get(Slot, slot.id).status == "free"


def test_an_edited_price_reaches_customers_and_a_confirmed_example_too(engine):
    bid = _clinic()
    with db.new_session() as s:
        rows = s.exec(select(Service).order_by(Service.id)).all()
        rows[0].price = "4 000"
        s.add(rows[0])
        s.commit()
        own, example = rows[0].name, rows[1].name
    _, system = _ask(bid, "telegram")
    assert own in system and "4 000" in system and example not in system
    with db.new_session() as s:
        b = s.get(Business, bid)
        b.example_ok = True
        s.add(b)
        s.commit()
    _, system = _ask(bid, "telegram", "А ещё вопрос")
    assert example in system


def test_price_list_marks_the_example_and_deletes_it_in_one_go(app_client):
    """The sign-up example is visible as such on «Прайс», and one button removes it; the owner's own rows stay."""
    from joop.models import Order, OrderLine, Service

    assert signup(app_client).status_code == 303
    page = app_client.get("/panel/services").text
    assert "— пример</b>" in page and 'class="chip warn">пример' in page and "Удалить весь пример" in page
    assert "Настоящим клиентам ИИ эти цены не называет" in page
    token = csrf_of(page)
    with db.new_session() as s:
        b = s.exec(select(Business).where(Business.slug == "ak-tish-dent")).one()
        first = s.exec(select(Service).where(Service.business_id == b.id)).first()
        order = Order(business_id=b.id, channel="console", total=1)
        s.add(order)
        s.commit()
        s.add(OrderLine(order_id=order.id, item_id=first.id, name=first.name, quantity=1, unit_price=1))  # a test-chat order
        s.add(Service(business_id=b.id, name="Своя услуга", price="900"))
        s.commit()
        bid = b.id
    app_client.post("/panel/services/example/delete", data={"csrf": token})
    with db.new_session() as s:
        assert [x.name for x in s.exec(select(Service).where(Service.business_id == bid)).all()] == ["Своя услуга"]
        assert s.exec(select(OrderLine)).one().item_id is None  # the order keeps its line
    page = app_client.get("/panel/services").text
    assert "Удалить весь пример" not in page and "+ Добавить" in page


def test_staff_and_faq_mark_the_example_and_remove_it_in_one_go(app_client):
    from joop.models import Faq, Slot, Staff

    assert signup(app_client).status_code == 303
    with db.new_session() as s:
        b = s.exec(select(Business).where(Business.slug == "ak-tish-dent")).one()
        bid = b.id
        s.add(Faq(business_id=bid, question="Своя парковка?", answer="Да, во дворе."))
        s.commit()
        n_staff = len(s.exec(select(Staff).where(Staff.business_id == bid, Staff.active == True)).all())  # noqa: E712
    for path, chip_rows in (("/panel/staff", n_staff), ("/panel/faq", None)):
        page = app_client.get(path).text
        assert "— пример</b>" in page and "Удалить весь пример" in page, path
        if chip_rows:
            assert page.count('class="chip warn">пример') == chip_rows
    token = csrf_of(app_client.get("/panel/staff").text)
    app_client.post("/panel/staff/example/delete", data={"csrf": token})
    app_client.post("/panel/faq/example/delete", data={"csrf": token})
    with db.new_session() as s:
        assert s.exec(select(Staff).where(Staff.business_id == bid, Staff.active == True)).all() == []  # noqa: E712
        assert s.exec(select(Slot).where(Slot.business_id == bid, Slot.status == "free", Slot.taken == 0)).all() == []
        assert [f.question for f in s.exec(select(Faq).where(Faq.business_id == bid)).all()] == ["Своя парковка?"]
    assert "Удалить весь пример" not in app_client.get("/panel/faq").text
    assert "+ Добавить вопрос" in app_client.get("/panel/faq").text
