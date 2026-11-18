"""The example's booking policy and order terms are fictional too: a real customer is not told them, a real order is
not held to them, and no customer is promised an example item «когда появится» (joop/samples.py, joop/restock.py).

The sign-up form empties these fields; a demo the founder makes for a prospect (/owner/prospects) keeps the whole
example, and its owner may connect the bot before opening the settings.
"""

from fastapi.testclient import TestClient
from sqlmodel import select

from joop import db, samples
from joop.agent.engine import handle_incoming
from joop.agent.llm import AgentReply
from joop.channels.base import IncomingMessage
from joop.models import Business, Order, Service, StockWatch
from joop.presets import create_business
from joop.web.app import create_app
from joop.web.saas import checklist

from .conftest import NOW_UTC, FakeLLM
from .test_saas import app_client, saas_settings, signup  # noqa: F401  (fixtures)
from .test_web import csrf_of

POLICY = "Стол держим 15 минут после времени брони. Доставка по центру города."  # the demo café's


def demo(niche="restaurant", **changes) -> int:
    """A prospect's demo with the bot connected and one dish of its own."""
    with db.new_session() as s:
        b = create_business(s, slug="bereke", name="Береке", password="pass-12345", niche=niche, demo=True, now_utc=NOW_UTC)
        b.telegram_bot_token = "123:TEST"
        for key, value in changes.items():
            setattr(b, key, value)
        s.add(Service(business_id=b.id, name="Бешбармак", price="400", price_value=400, sort=99))
        s.commit()
        return b.id


def chat(business_id, text, reply=None, channel="telegram", chat_id="c1"):
    llm = FakeLLM([reply or AgentReply("Здравствуйте!")])
    with db.new_session() as s:
        out = handle_incoming(s, s.get(Business, business_id), IncomingMessage(channel, chat_id, "text", text, "Клиент",
                                                                              f"{channel}-{chat_id}-{text}"), lambda: llm, NOW_UTC)
        s.commit()
    return out, llm.calls[0]["system"]


def order(business_id, quantity, channel="telegram", chat_id="c1"):
    with db.new_session() as s:
        dish = s.exec(select(Service).where(Service.business_id == business_id, Service.name == "Бешбармак")).one().id
    reply = AgentReply("Принял.", order={"lines": [{"item_id": dish, "quantity": quantity}], "mode": "delivery",
                                         "address": "Киевская 10", "name": "Айбек", "phone": "0555123456"})
    return chat(business_id, f"Бешбармак, {quantity} порции, доставка на Киевскую 10. Айбек, 0555123456", reply, channel, chat_id)[0]


def last_order(business_id) -> Order:
    with db.new_session() as s:
        return s.exec(select(Order).where(Order.business_id == business_id).order_by(Order.id.desc())).first()


def test_which_terms_are_still_the_example_s(engine):
    with db.new_session() as s:
        b = s.get(Business, demo())
        assert samples.example_terms(b) == {"booking_policy", "order"}
        assert samples.order_terms(b, samples.example_terms(b)) == (0, 0, 0) and samples.order_terms(b) == (600, 150, 2000)
        b.booking_policy = "Стол держим 20 минут."  # the owner's own rule
        assert samples.example_terms(b) == {"order"}
        b.delivery_fee = 200  # the owner opened the «Заказы» card and set the fee: the whole card is theirs now
        assert samples.example_terms(b) == frozenset() and samples.order_terms(b) == (600, 200, 2000)
        b.booking_policy, b.delivery_fee, b.example_ok = POLICY, 150, True  # «Это наши настоящие данные»
        assert samples.example_terms(b) == frozenset()
        b.example_ok, b.booking_policy, b.min_order, b.delivery_fee, b.free_delivery_from = False, "", 0, 0, 0  # as sign-up leaves it
        assert samples.example_terms(b) == frozenset()
        assert samples.example_settings(b) == ["адрес", "телефон", "часы работы", "описание компании"]  # the rest of a demo


def test_the_ai_is_told_the_owner_s_policy_and_terms_but_not_the_example_s(engine):
    business_id = demo()
    told = chat(business_id, "Как заказать доставку?")[1]
    assert "Порядок записи и заказа" not in told and "Условия заказа" not in told and "15 минут" not in told
    in_test_chat = chat(business_id, "Как заказать доставку?", channel="console", chat_id="t1")[1]
    assert f"Порядок записи и заказа в компании: {POLICY}" in in_test_chat  # the owner tries the example there
    assert "Условия заказа: минимальная сумма заказа 600 сом; доставка 150 сом; бесплатная доставка от 2000 сом." in in_test_chat
    with db.new_session() as s:
        b = s.get(Business, business_id)
        b.booking_policy, b.delivery_fee = "Стол держим 20 минут.", 200
        s.commit()
    told = chat(business_id, "А доставка сколько стоит?", chat_id="c2")[1]
    assert "Порядок записи и заказа в компании: Стол держим 20 минут." in told
    assert "Условия заказа: минимальная сумма заказа 600 сом; доставка 200 сом; бесплатная доставка от 2000 сом." in told


def test_a_real_order_is_not_held_to_the_example_s_minimum_or_charged_its_delivery_fee(engine):
    """The owner replaced the menu and connected the bot; the settings still held the demo café's «минимальный заказ
    600, доставка 150»: a 400-som order was refused, a bigger one got 150 som added that the café never charges."""
    business_id = demo()
    out = order(business_id, 1)
    saved = last_order(business_id)
    assert (saved.total, saved.delivery_fee) == (400, 0)
    assert "Сумма заказа: 400 сом." in out.reply and "доставку" not in out.reply
    out = order(business_id, 1, channel="console", chat_id="t1")  # the owner's test chat shows the example's rule at work
    assert out.reply.startswith("Минимальная сумма заказа — 600 сом, сейчас в заказе на 400 сом.") and out.order_id is None
    out = order(business_id, 2, channel="console", chat_id="t2")
    assert "Сумма заказа: 950 сом, включая доставку 150 сом." in out.reply


def test_the_owner_s_own_terms_are_applied(engine):
    business_id = demo(delivery_fee=200)  # the fee is the owner's; the minimum and the threshold happen to equal the example's
    out = order(business_id, 1)
    assert out.reply.startswith("Минимальная сумма заказа — 600 сом, сейчас в заказе на 400 сом.") and out.order_id is None
    out = order(business_id, 2, chat_id="c2")
    assert "Сумма заказа: 1 000 сом, включая доставку 200 сом." in out.reply
    assert order(business_id, 5, chat_id="c3").reply.count("доставку") == 0 and last_order(business_id).total == 2000  # free from 2 000


def test_the_example_s_terms_apply_once_the_owner_says_they_are_real(engine):
    business_id = demo(example_ok=True)
    assert "Сумма заказа: 950 сом, включая доставку 150 сом." in order(business_id, 2).reply
    assert POLICY in chat(business_id, "Как забронировать стол?", chat_id="c2")[1]


def test_no_customer_is_promised_an_example_item_back_in_stock(engine):
    """A new pharmacy's example has «Маски медицинские, 50 шт.» sold out: a real customer who asked for masks was told
    «Когда «Маски медицинские, 50 шт.» снова появится, напишем вам сюда», and later its example price."""
    business_id = demo("pharmacy")
    out, told = chat(business_id, "Медицинские маски есть?")
    assert "Маски медицинские" not in told  # the item is not in this customer's list at all
    assert "снова появится" not in out.reply and "Маски" not in out.reply
    with db.new_session() as s:
        assert s.exec(select(StockWatch)).all() == []
        s.add(Service(business_id=business_id, name="Бинт стерильный", price="60", price_value=60, stock=0, sold_out=True,
                      available=False, sort=98))  # the pharmacy's own item, sold out
        s.commit()
    out, _ = chat(business_id, "А бинт есть?", chat_id="c2")
    assert out.reply.endswith("Когда «Бинт стерильный» снова появится, напишем вам сюда. Не нужно — напишите «стоп».")
    with db.new_session() as s:
        assert len(s.exec(select(StockWatch)).all()) == 1


def make_the_rows_its_own(s, business_id):
    """The owner went through the price list, the people and the answers: no row equals the example any more."""
    services, staff, faq = samples._rows(s, s.get(Business, business_id))
    for row in services:
        row.price = "999"
    for row in staff:
        row.role = "свой"
    for row in faq:
        row.answer = "Свой ответ."
    s.add_all([*services, *staff, *faq])
    s.commit()


def login(c, slug="bereke"):
    c.post("/login", data={"slug": slug, "password": "pass-12345", "csrf": csrf_of(c.get("/login").text)})


def test_the_panel_says_what_in_the_settings_is_still_the_example_and_takes_the_owner_s_word(settings, rt, engine):
    business_id = demo(hours_text="Ежедневно 09:00–21:00", address="Бишкек, Токтогула 1", phone="+996 700 123 456", description="")
    with db.new_session() as s:
        make_the_rows_its_own(s, business_id)
        assert samples.left(s, s.get(Business, business_id)).settings == ["порядок записи", "условия заказа"]
        contacts = next(i for i in checklist(s, s.get(Business, business_id), NOW_UTC) if i["key"] == "contacts")
    assert not contacts["done"]
    assert f"порядок записи (сейчас из примера: {POLICY})" in contacts["hint"]
    assert ("условия заказа (сейчас из примера: минимальный заказ 600 сом, доставка 150 сом, бесплатная доставка от 2000 сом)"
            in contacts["hint"])
    with TestClient(create_app(settings, rt, init=False)) as c:
        login(c)
        home = c.get("/panel").text
        assert "Часть данных — ещё пример" in home
        assert ('<a href="/panel/settings">Настройки</a>: порядок записи, условия заказа — минимальную сумму и доставку из '
                "примера система к заказам клиентов не применяет") in home
        page = c.get("/panel/settings").text
        assert "Ещё из примера: порядок записи, условия заказа." in page
        assert "к заказам настоящих клиентов они не применяются" in page and "Этот порядок — из примера" in page
        c.post("/panel/example/ok", data={"csrf": csrf_of(home)})
        assert "Часть данных — ещё пример" not in c.get("/panel").text and "из примера" not in c.get("/panel/settings").text
    with db.new_session() as s:
        b = s.get(Business, business_id)
        assert samples.example_terms(b) == frozenset()
        assert next(i for i in checklist(s, b, NOW_UTC) if i["key"] == "contacts")["done"]
    assert "Сумма заказа: 950 сом, включая доставку 150 сом." in order(business_id, 2).reply


def test_hours_that_equal_the_example_s_can_be_confirmed_after_the_rows_are_replaced(app_client):
    """A new café whose real hours are the example's had no way to say so once its price list was its own: the
    «Это наши настоящие данные» button showed only while example rows were left, and saving the settings unchanged
    kept the hours hidden from customers."""
    signup(app_client, name="Кафе Береке", niche="restaurant")
    with db.new_session() as s:
        b = s.exec(select(Business).where(Business.name == "Кафе Береке")).one()
        make_the_rows_its_own(s, b.id)
        assert samples.left(s, b).settings == ["часы работы"] and samples.hours_are_example(b)
    home = app_client.get("/panel").text
    assert '<a href="/panel/settings">Настройки</a>: часы работы</li>' in home
    app_client.post("/panel/example/ok", data={"csrf": csrf_of(home)})
    with db.new_session() as s:
        b = s.exec(select(Business).where(Business.name == "Кафе Береке")).one()
        assert not samples.hours_are_example(b) and samples.customer_hours(b) == b.hours_text
