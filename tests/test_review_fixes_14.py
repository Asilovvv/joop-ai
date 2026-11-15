"""Fixes from the independent review of PRs #187-#195."""

from datetime import timedelta

from sqlmodel import select

from joop import db, prescription, restock, staff_reply
from joop.models import Business, Conversation, Message, Order, OrderLine, Service, StockWatch

from .conftest import NOW_UTC
from .test_holds import with_bot
from .test_pharmacy import item, order, pharmacy
from .test_restock import masks, restock_masks
from .test_restock import run as notify


def test_ordinary_comments_do_not_block_a_delivery(engine):
    b = pharmacy()
    with db.new_session() as s:
        for name in ("Преднизолон 5 мг", "Трамадол 50 мг", "Лирика 75 мг", "Капли глазные Тимолол", "Раствор для инъекций Кеторол"):
            s.add(Service(business_id=b.id, name=name, price="300", category="по рецепту", stock=5))
        s.commit()
        catalog = list(s.exec(select(Service).where(Service.business_id == b.id)).all())
    for comment in ("Позвоните предварительно", "Предъявлю паспорт", "у остановки трамвая", "Лирическая улица",
                    "капли от насморка тоже посмотрю", "Раствор не нужен", "Срочно, пара упаковок"):
        assert prescription.named_in(comment, catalog) == [], comment
    para = item(b.id, "Парацетамол 500 мг, 20 таблеток")
    out, _ = order(b.id, [{"item_id": para.id, "quantity": 10, "note": "Позвоните предварительно"}], "delivery", "pr")
    assert out.order_id


def test_restock_asks_are_not_lookalike_words(engine):
    b = pharmacy()
    with db.new_session() as s:
        for name in ("Пара носков", "Тест на беременность", "Крем для рук"):
            s.add(Service(business_id=b.id, name=name, price="100", stock=0, available=False, sold_out=True))
        s.commit()
        sold = list(s.exec(select(Service).where(Service.business_id == b.id, Service.sold_out)).all())
    for text in ("Срочно нужен парацетамол", "Тестовое сообщение", "Есть детский крем?", "маскара есть?"):
        assert restock.asked_for(text, sold) == [], text


def test_test_chats_keep_no_watch_and_night_waits_for_the_morning(engine, rt):
    from joop.agent.engine import handle_incoming
    from joop.agent.llm import AgentReply
    from joop.channels.base import IncomingMessage
    from joop.web.saas import TRY_CHAT_ID

    from .conftest import FakeLLM
    from .test_restock import ask

    b = pharmacy()
    with_bot(b.id)
    with db.new_session() as s:
        out = handle_incoming(s, s.get(Business, b.id), IncomingMessage("console", TRY_CHAT_ID, "text", "Маски есть?", "", "t1"),
                              lambda: FakeLLM([AgentReply("Нет.")]), NOW_UTC)
        s.commit()
        assert "напишем вам сюда" not in out.reply and not s.exec(select(StockWatch)).all()
    ask(b.id, "Маски есть?", "a")
    restock_masks(b.id)
    assert notify(rt, b.id, NOW_UTC + timedelta(days=2, hours=1)) == {}  # 00:14 in Bishkek
    assert notify(rt, b.id, NOW_UTC + timedelta(days=2, hours=16)) == {"sent": 1}  # 09:14


def test_bought_counts_customers_and_the_item_only(engine, rt):
    b = pharmacy()
    with_bot(b.id)
    from .test_restock import ask

    ask(b.id, "Маски есть?", "a")
    restock_masks(b.id)
    told = NOW_UTC + timedelta(days=2, hours=16)
    notify(rt, b.id, told)
    with db.new_session() as s:
        conv = s.exec(select(Conversation).where(Conversation.business_id == b.id)).one()
        para = s.exec(select(Service).where(Service.business_id == b.id, Service.name.startswith("Парацетамол"))).one()
        for total, lines in ((3250, [(masks(b.id).id, 1, 250), (para.id, 10, 300)]), (250, [(masks(b.id).id, 1, 250)])):
            o = Order(business_id=b.id, conversation_id=conv.id, mode="pickup", status="new", total=total, created_at=told + timedelta(hours=1))
            s.add(o)
            s.flush()
            for item_id, qty, price in lines:
                s.add(OrderLine(order_id=o.id, item_id=item_id, name="x", quantity=qty, unit_price=price))
        s.commit()
        assert restock.results(s, b.id, NOW_UTC) == (1, 1, 500)  # one customer, the masks' lines only


def test_a_second_identical_answer_to_a_new_question_is_sent(business, rt):
    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.telegram_bot_token = "123:TEST"
        conv = Conversation(business_id=b.id, channel="telegram", chat_id="t2", created_at=NOW_UTC)
        s.add(conv)
        s.commit()
        staff_reply.send(s, rt, b, conv, "Да", NOW_UTC, author="Айгуль")
        s.add(Message(business_id=b.id, conversation_id=conv.id, role="customer", text="А в субботу работаете?",
                      created_at=NOW_UTC + timedelta(seconds=30)))
        s.commit()
        staff_reply.send(s, rt, b, conv, "Да", NOW_UTC + timedelta(minutes=1), author="Айгуль")
        s.commit()
    assert [t for chat, t in rt.tg.sent if chat == "t2"] == ["Да", "Да"]
