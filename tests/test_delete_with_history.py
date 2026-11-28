"""Deleting what history still points to: a specialist one of whose customers cancelled, a time with a cancelled
booking, a price-list item somebody waits for.

The database refuses to delete a row another row points to. A cancelled booking still pointed to its time, and a
customer waiting for an item (joop/restock.py) to the item, so the delete failed: error 500 in the panel and in the app,
and a failed sync for a business on Altegio. Found by tests/test_tenant_isolation.py, which calls every route with a
row of the caller's own.
"""

import json
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlmodel import select

from joop import altegio, db, stock
from joop.agent.llm import AgentReply
from joop.models import Booking, Business, Conversation, Order, OrderLine, PanelUser, Prospect, Service, Slot, Staff, StockMove, StockWatch
from joop.profile import apply_profile
from joop.timeutil import utc_to_local, utcnow
from joop.web.app import create_app

from .conftest import NOW_UTC, FakeLLM
from .test_altegio import altegio_slot, book, fake, make_client, synced  # noqa: F401  (fixture)
from .test_mobile import auth, sign_in, tomorrow_slots
from .test_pitch import FOUND, SOURCE
from .test_saas import app_client, owner_login, saas_settings, signup  # noqa: F401  (fixtures)
from .test_web import csrf_of, login


def cancelled_booking(c, business, h) -> tuple[Slot, int]:
    """A customer booked a time and cancelled: the time is free again, the booking stays as history."""
    slot = tomorrow_slots(business.id)[0]
    r = c.post("/api/mobile/bookings", json={"slot_id": slot.id, "name": "Айгуль", "phone": "+996700000001", "service": "Консультация"}, headers=h)
    booking_id = r.json()["booking"]["id"]
    assert c.post(f"/api/mobile/bookings/{booking_id}/cancel", headers=h).status_code == 200
    with db.new_session() as s:
        assert (s.get(Slot, slot.id).status, s.get(Booking, booking_id).status, s.get(Booking, booking_id).slot_id) == ("free", "cancelled", slot.id)
    return slot, booking_id


def history_kept(booking_id: int, slot: Slot) -> None:
    with db.new_session() as s:
        x = s.get(Booking, booking_id)
        assert s.get(Slot, slot.id) is None  # the free time went with her
        assert (x.status, x.slot_id, x.start, x.staff_id) == ("cancelled", None, slot.start, slot.staff_id)  # the visit's own record stays
        assert x.customer_name == "Айгуль" and x.staff_name


def test_the_owner_removes_a_specialist_one_of_whose_customers_cancelled(settings, rt, business):
    with TestClient(create_app(settings, rt, init=False)) as c:
        token, h = login(c), auth(sign_in(c).json()["token"])
        slot, booking_id = cancelled_booking(c, business, h)
        r = c.post(f"/panel/staff/{slot.staff_id}/delete", data={"csrf": token})  # was: error 500
        assert r.status_code == 200 and "Специалист убран, его свободные окна удалены. Существующие записи остались." in r.text
        with db.new_session() as s:
            assert s.get(Staff, slot.staff_id).active is False
            assert s.exec(select(Slot).where(Slot.staff_id == slot.staff_id, Slot.status == "free")).all() == []
        history_kept(booking_id, slot)


def test_the_app_removes_such_a_specialist_too(settings, rt, business):
    with TestClient(create_app(settings, rt, init=False)) as c:
        h = auth(sign_in(c).json()["token"])
        slot, booking_id = cancelled_booking(c, business, h)
        r = c.post(f"/api/mobile/staff/{slot.staff_id}/delete", headers=h)  # was: error 500
        assert r.status_code == 200, r.text
        assert slot.staff_id not in [p["id"] for p in c.get("/api/mobile/staff", headers=h).json()["staff"]]
        history_kept(booking_id, slot)


def test_a_booked_time_keeps_its_specialists_time_and_a_login_of_hers_is_closed(settings, rt, business):
    """What removing a specialist always did, unchanged: a time somebody is booked into stays, with the booking."""
    with TestClient(create_app(settings, rt, init=False)) as c:
        token, h = login(c), auth(sign_in(c).json()["token"])
        slot = tomorrow_slots(business.id)[0]
        booking_id = c.post("/api/mobile/bookings", json={"slot_id": slot.id, "name": "Айгуль", "phone": "+996700000001",
                                                          "service": "Консультация"}, headers=h).json()["booking"]["id"]
        with db.new_session() as s:
            s.add(PanelUser(business_id=business.id, name="Она", login="she", password_hash="x", staff_id=slot.staff_id))
            s.commit()
        assert c.post(f"/panel/staff/{slot.staff_id}/delete", data={"csrf": token}).status_code == 200
        with db.new_session() as s:
            assert (s.get(Slot, slot.id).status, s.get(Booking, booking_id).status, s.get(Booking, booking_id).slot_id) == ("booked", "booked", slot.id)
            assert s.exec(select(PanelUser)).one().active is False


def test_a_new_business_tries_the_ai_and_then_removes_the_example(app_client, llm):  # noqa: F811
    """The first hour of every new business: the test chat books a time with an example specialist, «Новый диалог»
    cancels it, and «Удалить пример» on the staff page answered with error 500."""
    signup(app_client)
    with db.new_session() as s:
        b = s.exec(select(Business)).one()
        now_local = utc_to_local(utcnow(), b.timezone)
        slot = s.exec(select(Slot).where(Slot.business_id == b.id, Slot.status == "free", Slot.start > now_local + timedelta(hours=3))
                      .order_by(Slot.start)).first()
    llm.replies.append(AgentReply("Записала вас!", booking={"slot_id": slot.id, "name": "Тест", "phone": "0555 123 456"}))
    token = csrf_of(app_client.get("/panel/try").text)
    app_client.post("/panel/try", data={"text": "Запишите меня, Тест, 0555 123 456", "csrf": token})
    assert "Тестовые записи отменены, время снова свободно: 1." in app_client.post("/panel/try/reset", data={"csrf": token}).text
    r = app_client.post("/panel/staff/example/delete", data={"csrf": token})
    assert r.status_code == 200 and "Пример удалён" in r.text
    with db.new_session() as s:
        assert s.exec(select(Staff).where(Staff.active == True)).all() == []  # noqa: E712
        assert s.exec(select(Slot).where(Slot.status == "free")).all() == []
        assert (s.exec(select(Booking)).one().status, s.exec(select(Booking)).one().slot_id) == ("cancelled", None)


def test_the_app_removes_the_example_after_a_test_booking(app_client, llm):  # noqa: F811
    signup(app_client)
    with db.new_session() as s:
        b = s.exec(select(Business)).one()
        slot = s.exec(select(Slot).where(Slot.business_id == b.id, Slot.status == "free",
                                         Slot.start > utc_to_local(utcnow(), b.timezone) + timedelta(hours=3)).order_by(Slot.start)).first()
    h = auth(sign_in(app_client, company=b.slug, password="long-password").json()["token"])
    llm.replies.append(AgentReply("Записала вас!", booking={"slot_id": slot.id, "name": "Тест", "phone": "0555 123 456"}))
    assert app_client.post("/api/mobile/try", json={"text": "Запишите меня, Тест, 0555 123 456"}, headers=h).status_code == 200
    assert app_client.post("/api/mobile/try/reset", headers=h).json()["cancelled"] == 1
    r = app_client.post("/api/mobile/staff/example/delete", headers=h)  # was: error 500
    assert r.status_code == 200 and r.json()["staff"] == []


def test_a_time_whose_booking_was_cancelled_can_be_deleted_and_a_booked_one_cannot(settings, rt, business):
    with TestClient(create_app(settings, rt, init=False)) as c:
        token, h = login(c), auth(sign_in(c).json()["token"])
        slot, booking_id = cancelled_booking(c, business, h)
        r = c.post(f"/panel/slots/{slot.id}/delete", data={"csrf": token})
        assert "сначала отмените запись" not in r.text  # it is cancelled already: the panel sent the owner in a circle
        history_kept(booking_id, slot)
        taken = tomorrow_slots(business.id)[0]
        c.post("/api/mobile/bookings", json={"slot_id": taken.id, "name": "Бакыт", "phone": "+996700000002", "service": "Консультация"}, headers=h)
        r = c.post(f"/panel/slots/{taken.id}/delete", data={"csrf": token})
        assert "Окно с записью удалить нельзя, сначала отмените запись." in r.text
        with db.new_session() as s:
            assert s.get(Slot, taken.id).status == "booked"


def test_altegio_takes_a_time_whose_visit_was_cancelled_and_the_sync_goes_on(business, fake):  # noqa: F811
    """A visit is cancelled in Altegio (Joop closes its booking and offers the time), then somebody takes the time in
    Altegio itself. The sync deletes the time in Joop; it failed on the cancelled booking, at this sync and every next."""
    synced(business, fake)
    slot = altegio_slot(business)
    out = book(business, fake, slot.id)
    fake.times[7] = [f"{fake.day}T10:00:00+06:00", f"{fake.day}T12:00:00+06:00"]
    with db.new_session() as s:
        assert altegio.sync(s, s.get(Business, business.id), make_client(fake), NOW_UTC + timedelta(minutes=20)).released == 1
        s.commit()
    fake.times[7] = [f"{fake.day}T12:00:00+06:00", f"{fake.day}T14:00:00+06:00"]
    with db.new_session() as s:
        res = altegio.sync(s, s.get(Business, business.id), make_client(fake), NOW_UTC + timedelta(minutes=40))
        s.commit()
    assert (res.slots_removed, res.slots_added) == (1, 1)
    with db.new_session() as s:
        x = s.get(Booking, out.booking_id)
        assert s.get(Slot, slot.id) is None and (x.status, x.slot_id, x.start) == ("cancelled", None, slot.start)
        assert s.get(Business, business.id).altegio_error == ""


def waited_for(business) -> int:
    """A price-list item with everything that can hang on it: a count on the shelf, an order, a customer waiting."""
    with db.new_session() as s:
        item = s.exec(select(Service).where(Service.business_id == business.id)).first()
        conv = Conversation(business_id=business.id, channel="telegram", chat_id="77", customer_name="Айгуль")
        order = Order(business_id=business.id, customer_name="Айгуль")
        s.add(conv)
        s.add(order)
        s.commit()
        s.add(StockWatch(business_id=business.id, service_id=item.id, conversation_id=conv.id))
        s.add(StockMove(business_id=business.id, service_id=item.id, delta=-1, left=0, reason="order"))
        s.add(OrderLine(order_id=order.id, item_id=item.id, name=item.name, unit_price=500))
        s.commit()
        return item.id


def gone_with_its_history(item_id: int | None) -> None:
    with db.new_session() as s:
        assert item_id is None or s.get(Service, item_id) is None
        assert s.exec(select(StockWatch)).all() == [] and s.exec(select(StockMove)).all() == []
        line = s.exec(select(OrderLine)).one()
        assert (line.item_id, line.unit_price) == (None, 500) and line.name  # the order still says what was bought


def test_the_owner_deletes_an_item_a_customer_waits_for(settings, rt, business):
    item_id = waited_for(business)
    with TestClient(create_app(settings, rt, init=False)) as c:
        token = login(c)
        r = c.post(f"/panel/services/{item_id}/delete", data={"csrf": token})  # was: error 500
        assert r.status_code == 200 and "Услуга удалена." in r.text
    gone_with_its_history(item_id)


def test_the_app_deletes_such_an_item_too(settings, rt, business):
    item_id = waited_for(business)
    with TestClient(create_app(settings, rt, init=False)) as c:
        h = auth(sign_in(c).json()["token"])
        r = c.post(f"/api/mobile/services/{item_id}/delete", headers=h)  # was: error 500
        assert r.status_code == 200, r.text
    gone_with_its_history(item_id)


def test_a_profile_loaded_again_replaces_a_price_list_that_has_history(business):
    """`python -m joop load` on a business that already sold something."""
    waited_for(business)
    with db.new_session() as s:
        b = s.get(Business, business.id)
        apply_profile(s, b, {"name": b.name, "services": [{"name": "Новая услуга", "price": "100"}]}, replace=True, now_utc=NOW_UTC)
        s.commit()
        assert [x.name for x in s.exec(select(Service).where(Service.business_id == b.id)).all()] == ["Новая услуга"]
    gone_with_its_history(None)  # SQLite gives the freed number to the new row: the old item is not looked up by it


def test_a_demo_is_refilled_after_somebody_ordered_in_it(app_client, rt):  # noqa: F811
    token = owner_login(app_client)
    app_client.post("/owner/prospects", data={"name": "Салон «Айгерим»", "niche": "beauty", "instagram": "aigerim.kg", "csrf": token})
    with db.new_session() as s:
        pid = s.exec(select(Prospect.id)).one()

    def pitch():
        rt._llm = FakeLLM([AgentReply("Ок."), AgentReply("Ок.")])
        rt._llm.write = lambda instruction, text, usage: json.dumps(FOUND, ensure_ascii=False)
        return app_client.post(f"/owner/prospects/{pid}", data={"action": "pitch", "source": SOURCE, "csrf": token}, follow_redirects=False)

    assert pitch().headers["location"] == f"/owner/prospects/{pid}/pitch"
    with db.new_session() as s:
        b = s.get(Business, s.get(Prospect, pid).demo_business_id)
        item = s.exec(select(Service).where(Service.business_id == b.id)).first()
        order = Order(business_id=b.id, customer_name="Айгуль")
        s.add(order)
        s.commit()
        s.add(OrderLine(order_id=order.id, item_id=item.id, name=item.name, unit_price=1200))
        s.commit()
    assert pitch().headers["location"] == f"/owner/prospects/{pid}/pitch"  # was: error 500
    with db.new_session() as s:
        assert len(s.exec(select(Service).where(Service.business_id == b.id)).all()) == 3
        assert (s.exec(select(OrderLine)).one().item_id, s.exec(select(OrderLine)).one().name) == (None, "Маникюр с покрытием")


def test_delete_item_alone(business):
    item_id = waited_for(business)
    with db.new_session() as s:
        stock.delete_item(s, s.get(Service, item_id))
        s.commit()
    gone_with_its_history(item_id)
