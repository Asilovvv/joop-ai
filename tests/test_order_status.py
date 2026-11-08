"""«Где мой заказ?»: staff move an order on, the customer hears it, the AI answers from the same status."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlmodel import select

from joop import db
from joop.agent.engine import handle_incoming
from joop.agent.llm import AgentReply
from joop.channels.base import IncomingMessage
from joop.models import Business, Conversation, Message, Order, Service
from joop.presets import create_business
from joop.web.app import create_app

from .conftest import NOW_UTC, FakeLLM
from .test_web import csrf_of


def shop(niche="shop", slug="shop"):
    with db.new_session() as s:
        b = create_business(s, slug=slug, name="Бутик", password="shop-pass-123", niche=niche, demo=True, now_utc=NOW_UTC)
        b.example_ok = True  # the shop's catalog is its own
        b.telegram_bot_token = "123:TEST"
        b.address, b.hours_text = "Бишкек, Киевская 10", "11:00–19:00"
        s.commit()
        return b


def item(business_id, name):
    with db.new_session() as s:
        return s.exec(select(Service).where(Service.business_id == business_id, Service.name == name)).one()


def say(business_id, text, llm, ext, chat="t1", channel="telegram"):
    with db.new_session() as s:
        out = handle_incoming(s, s.get(Business, business_id), IncomingMessage(channel, chat, "text", text, "", ext), lambda: llm, NOW_UTC)
        s.commit()
        return out


def place(business_id, chat="t1", mode="delivery", text="Платье M, Асель 0555 112 233, Бишкек, Джал 23", channel="telegram"):
    dress = item(business_id, "Платье миди бежевое, размер M")
    llm = FakeLLM([AgentReply("Оформила.", order={"lines": [{"item_id": dress.id, "quantity": 1, "note": ""}], "mode": mode,
                                                  "address": "Бишкек, Джал 23" if mode == "delivery" else "", "time": "",
                                                  "name": "Асель", "phone": "0555112233", "comment": ""})])
    out = say(business_id, text, llm, f"o-{chat}-{mode}", chat=chat, channel=channel)
    assert out.order_id
    return out.order_id


def move(c, order_id, status):
    token = csrf_of(c.get("/panel/orders").text)
    return c.post(f"/panel/orders/{order_id}/status", data={"status": status, "csrf": token})


def panel(settings, rt, slug="shop"):
    c = TestClient(create_app(settings, rt, init=False))
    token = csrf_of(c.get("/login").text)
    c.post("/login", data={"slug": slug, "password": "shop-pass-123", "csrf": token})
    return c


def test_customer_hears_confirmed_and_on_the_way_but_not_done(settings, rt, engine):
    b = shop()
    order_id = place(b.id)
    with panel(settings, rt) as c:
        r = move(c, order_id, "accepted")
        assert rt.tg.sent[-1] == ("t1", f"Ваш заказ №{order_id} подтверждён. Сумма: 3 400 сом.")
        assert f"Заказ #{order_id}: Принят. Клиенту отправлено сообщение." in r.text
        assert ">В пути</button>" in r.text and ">Принять</button>" not in r.text  # the next step, not the one done
        move(c, order_id, "sent")
        assert rt.tg.sent[-1] == ("t1", f"Ваш заказ №{order_id} передан в доставку и уже в пути.")
        sent = len(rt.tg.sent)
        move(c, order_id, "sent")  # pressed twice: one message
        r = move(c, order_id, "done")
        assert len(rt.tg.sent) == sent and '<span class="chip ok">Выполнен</span>' in r.text
    with db.new_session() as s:
        texts = s.exec(select(Message.text).where(Message.business_id == b.id, Message.role == "ai")).all()
    assert f"Ваш заказ №{order_id} передан в доставку и уже в пути." in texts  # kept in the dialogue for staff


def test_pickup_is_ready_to_collect_in_kyrgyz(settings, rt, engine):
    b = shop()
    order_id = place(b.id, mode="pickup", text="Көйнөк M өлчөмү керек, өзүм алып кетем. Асель 0555 112 233")
    with panel(settings, rt) as c:
        move(c, order_id, "accepted")
        r = move(c, order_id, "sent")
        assert '<span class="chip ok">Готов к выдаче</span>' in r.text
    assert rt.tg.sent[-1][1] == f"Сиздин №{order_id} буйрутмаңыз даяр, алып кетсеңиз болот — Бишкек, Киевская 10, 11:00–19:00."


def test_whatsapp_after_a_day_tells_staff_to_call(settings, rt, engine):
    b = shop()
    order_id = place(b.id)
    with db.new_session() as s:
        conv = s.exec(select(Conversation).where(Conversation.business_id == b.id)).one()
        conv.channel, conv.last_customer_at = "whatsapp", NOW_UTC - timedelta(days=2)  # outside WhatsApp's 24 hours
        s.add(conv)
        s.commit()
    with panel(settings, rt) as c:
        r = move(c, order_id, "accepted")
    assert "Написать клиенту не получилось" in r.text and "+996555112233" in r.text


def test_the_ai_sees_the_orders_of_this_chat_only(engine):
    b = shop()
    order_id = place(b.id)
    llm = FakeLLM([AgentReply("Ваш заказ ждёт подтверждения."), AgentReply("Уточню.")])
    say(b.id, "Где мой заказ?", llm, "w1")
    say(b.id, "Где заказ Асель? Её телефон 0555 112 233", llm, "w2", chat="t2")
    mine, other = llm.calls[0]["system"], llm.calls[1]["system"]
    assert "Заказы клиента в этом чате (данные из системы, статус меняют сотрудники):" in mine
    assert (f"- №{order_id} от 04.11: 1 × Платье миди бежевое, размер M; 3 400 сом; доставка: Бишкек, Джал 23"
            " — статус: принят, ждёт подтверждения сотрудника") in mine
    assert "Заказы клиента в этом чате" not in other and "Платье миди бежевое, размер M; 3 400 сом" not in other
    with db.new_session() as s:
        order = s.get(Order, order_id)
        order.created_at = NOW_UTC - timedelta(days=31)  # a month old: no longer brought into the chat
        s.add(order)
        s.commit()
    llm = FakeLLM([AgentReply("Уточню.")])
    say(b.id, "А где заказ?", llm, "w3")
    assert "Заказы клиента в этом чате" not in llm.calls[0]["system"]


def test_the_test_chat_shows_the_notice(settings, rt, engine):
    b = shop()
    from joop.web.saas import TRY_CHAT_ID

    order_id = place(b.id, chat=TRY_CHAT_ID, channel="console")
    with panel(settings, rt) as c:
        r = move(c, order_id, "accepted")
        assert "Клиенту отправлено сообщение." in r.text
        assert f"Ваш заказ №{order_id} подтверждён." in c.get("/panel/try").text
    assert rt.tg.sent == []
