"""Contacts and opening hours from the owner's app: the launch list's «Контакты и часы работы» step without the
panel. The example's address, phone and hours are marked, and customers are told only the business's own."""

from fastapi.testclient import TestClient
from sqlmodel import select

from joop import db, samples
from joop.agent.llm import AgentReply
from joop.models import Business, Order, PanelUser, Service, Staff
from joop.security import hash_password
from joop.web.app import create_app

from .test_mobile import auth, client, sign_in  # noqa: F401 - the client fixture

FORM = {"name": "Салон Айгерим", "niche": "beauty", "phone": "0555 123 456", "password": "aigerim-2026", "contact_name": "Айгерим"}


def _step(c, h):
    return next(x for x in c.get("/api/mobile/setup", headers=h).json()["steps"] if x["key"] == "contacts")


def test_a_new_business_writes_its_own_contacts_and_hours_from_the_phone(engine, settings, rt):
    with TestClient(create_app(settings, rt, init=False)) as c:
        h = auth(c.post("/api/mobile/signup", json=FORM).json()["token"])
        before = c.get("/api/mobile/contacts", headers=h).json()
        assert "hours_text" in before["example"] and _step(c, h)["done"] is False
        r = c.post("/api/mobile/contacts", headers=h, json={
            "address": "Бишкек, ул. Токтогула 100", "phone": "+996 555 123 456", "hours_text": "Пн–Сб 10:00–20:00",
            "work_start": "10:00", "work_end": "20:00", "days_off": [7, 9]})
        assert r.status_code == 200, r.text
        assert r.json() == {"address": "Бишкек, ул. Токтогула 100", "phone": "+996 555 123 456",
                            "hours_text": "Пн–Сб 10:00–20:00", "work_start": "10:00", "work_end": "20:00",
                            "days_off": [7], "example": [], "orders": None}  # a salon takes no orders
        assert _step(c, h)["done"] is True
    with db.new_session() as s:
        b = s.exec(select(Business).where(Business.slug == "salon-aygerim")).one()
        assert (b.days_off, samples.customer_hours(b), samples.customer_contact(b, "address")) == \
            ("7", "Пн–Сб 10:00–20:00", "Бишкек, ул. Токтогула 100")


def test_hours_that_end_before_they_start_are_refused_and_nothing_changes(client, business):
    h = auth(sign_in(client).json()["token"])
    before = client.get("/api/mobile/contacts", headers=h).json()
    r = client.post("/api/mobile/contacts", headers=h, json={**before, "address": "Другой", "work_start": "18:00", "work_end": "09:00"})
    assert r.status_code == 422 and "позже начала" in r.json()["error"]
    assert client.post("/api/mobile/contacts", headers=h, json={**before, "work_start": "9 утра"}).status_code == 422
    assert client.get("/api/mobile/contacts", headers=h).json() == before


def test_a_master_does_not_change_the_contacts(client, business):
    with db.new_session() as s:
        master = Staff(business_id=business.id, name="Мастер")
        s.add(master)
        s.flush()
        s.add(PanelUser(business_id=business.id, login="m1", name="Мастер", password_hash=hash_password("master-pass-1"),
                        staff_id=master.id))
        s.commit()
    hm = auth(sign_in(client, user="m1", password="master-pass-1").json()["token"])
    assert client.get("/api/mobile/contacts", headers=hm).status_code == 403
    assert client.post("/api/mobile/contacts", headers=hm, json={"address": "X"}).status_code == 403
    assert client.get("/api/mobile/contacts").status_code == 401


SHOP = {"name": "Гаджет Шоп", "niche": "shop", "phone": "0555 222 333", "password": "shop-pass-2026", "contact_name": "Бакыт"}


def test_a_shop_sets_its_order_terms_from_the_phone_and_orders_follow_them(engine, settings, rt, llm):
    """Sign-up clears the example's order terms (joop/signup.py), and only the panel could set them: a delivery order
    was counted without the shop's delivery fee or minimum."""
    with TestClient(create_app(settings, rt, init=False)) as c:
        h = auth(c.post("/api/mobile/signup", json=SHOP).json()["token"])
        slug = "gadzhet-shop"
        before = c.get("/api/mobile/contacts", headers=h).json()
        assert before["orders"] == {"min_order": 0, "delivery_fee": 0, "free_delivery_from": 0, "example": False}
        assert c.post("/api/mobile/contacts", headers=h, json={"delivery_fee": 99_000_000}).status_code == 422
        r = c.post("/api/mobile/contacts", headers=h, json={"min_order": 1000, "delivery_fee": 150,
                                                             "free_delivery_from": -5})
        assert r.status_code == 200, r.text
        assert r.json()["orders"] == {"min_order": 1000, "delivery_fee": 150, "free_delivery_from": 0, "example": False}
        assert {k: r.json()[k] for k in ("address", "work_start", "days_off")} == \
            {k: before[k] for k in ("address", "work_start", "days_off")}  # the fields not sent keep their values
        c.post("/api/mobile/services/example/delete", headers=h)
        c.post("/api/mobile/services", headers=h, json={"name": "Чехол для iPhone 15", "price": "800"})
        with db.new_session() as s:
            item = s.exec(select(Service).where(Service.name == "Чехол для iPhone 15")).one().id
        c.cookies.clear()
        llm.replies.append(AgentReply("Заказ оформлен.", order={"lines": [{"item_id": item, "quantity": 2}], "mode": "delivery",
                                                               "address": "Асанбай 12", "name": "Нурия", "phone": "0700 555 666"}))
        reply = c.post(f"/c/{slug}/chat", json={"text": "Два чехла, доставка Асанбай 12, Нурия 0700 555 666",
                                                "visitor": "d" * 24}).json()["reply"]
        assert "Сумма заказа: 1 750 сом, включая доставку 150 сом." in reply
        assert "доставка 150 сом" in llm.calls[-1]["system"] and "минимальная сумма заказа 1000 сом" in llm.calls[-1]["system"]
    with db.new_session() as s:
        order = s.exec(select(Order).where(Order.customer_name == "Нурия")).one()
        assert (order.total, order.delivery_fee) == (1750, 150)


def test_order_terms_are_the_owners_and_only_where_orders_are_taken(client, business):
    h = auth(sign_in(client).json()["token"])  # a clinic: no «Заказы» card, the sums are not stored
    assert client.post("/api/mobile/contacts", headers=h, json={"delivery_fee": 150}).json()["orders"] is None
    with db.new_session() as s:
        assert s.get(Business, business.id).delivery_fee == 0
