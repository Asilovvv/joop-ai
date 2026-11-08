"""Fixes from the independent review of PRs #152-#156."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlmodel import select

from joop import db, jobs, order_status
from joop.agent.engine import handle_incoming
from joop.agent.llm import AgentReply
from joop.channels.base import IncomingMessage
from joop.models import Business, Conversation, Job, Message, Order, Service, Slot, Staff
from joop.presets import create_business
from joop.timeutil import utc_to_local
from joop.unfinished import _text as follow_up_text
from joop.web.app import create_app

from .conftest import NOW_UTC, FakeLLM
from .test_web import csrf_of

NOW_LOCAL = utc_to_local(NOW_UTC, "Asia/Bishkek").replace(second=0, microsecond=0)


def make(niche, slug, real=True, token=True):
    with db.new_session() as s:
        b = create_business(s, slug=slug, name=slug.title(), password="pass-12345", niche=niche, demo=True, now_utc=NOW_UTC)
        b.example_ok = real
        if token:
            b.telegram_bot_token = "123:TEST"
        s.commit()
        return b


def order_from(business_id, chat, channel="telegram", texts=("Платье M, Асель 0555 112 233",), mode="pickup"):
    with db.new_session() as s:
        dress = s.exec(select(Service).where(Service.business_id == business_id, Service.name == "Платье миди бежевое, размер M")).one()
    reply = AgentReply("Оформила.", order={"lines": [{"item_id": dress.id, "quantity": 1, "note": ""}], "mode": mode,
                                           "address": "Бишкек, Джал 23" if mode == "delivery" else "", "time": "",
                                           "name": "Асель", "phone": "0555112233", "comment": ""})
    llm = FakeLLM([AgentReply("Уточните контакты.")] * (len(texts) - 1) + [reply])
    out = None
    for i, text in enumerate(texts):
        with db.new_session() as s:
            out = handle_incoming(s, s.get(Business, business_id), IncomingMessage(channel, chat, "text", text, "", f"{chat}-{i}"),
                                  lambda: llm, NOW_UTC)
            s.commit()
    assert out.order_id
    return out.order_id


def panel(c, slug):
    token = csrf_of(c.get("/login").text)
    c.post("/login", data={"slug": slug, "password": "pass-12345", "csrf": token})


def move(c, order_id, status):
    token = csrf_of(c.get("/panel/orders").text)
    return c.post(f"/panel/orders/{order_id}/status", data={"status": status, "csrf": token})


def test_notices_leave_out_hours_copied_from_the_example(engine):
    """«Готов к выдаче» told customers the sign-up example's opening hours, which the AI itself no longer names."""
    shop = make("shop", "shop", real=False)
    with db.new_session() as s:
        b = s.get(Business, shop.id)
        b.address = "Бишкек, Киевская 10"
        order = Order(business_id=b.id, mode="pickup", status="sent")
        order.id = 7
        assert order_status.notice_text(b, order, False) == "Ваш заказ №7 готов, можно забирать — Бишкек, Киевская 10."
        b.hours_text = "11:00–20:00"  # the owner's own hours are facts again
        assert order_status.notice_text(b, order, False).endswith("Бишкек, Киевская 10, 11:00–20:00.")
    repair = make("repair", "repair", real=False)
    with db.new_session() as s:
        b = s.get(Business, repair.id)
        assert "Пн" not in jobs.ready_text(b, Job(number="1", item="Пальто"), False)


def test_a_stale_tab_cannot_move_an_order_back_or_revive_it(settings, rt, engine):
    shop = make("shop", "shop2")
    order_id = order_from(shop.id, "t1")
    with TestClient(create_app(settings, rt, init=False)) as c:
        panel(c, "shop2")
        move(c, order_id, "accepted")
        move(c, order_id, "sent")
        sent = len(rt.tg.sent)
        r = move(c, order_id, "accepted")  # an old tab still showing «Принять»
        assert "уже «Готов к выдаче»" in r.text and len(rt.tg.sent) == sent
        move(c, order_id, "cancelled")
        with db.new_session() as s:
            stock_after_cancel = s.exec(select(Service).where(Service.business_id == shop.id, Service.name == "Платье миди бежевое, размер M")).one().stock
        r = move(c, order_id, "sent")  # an old tab showing «Готов к выдаче» on a cancelled order
        assert "уже «Отменён»" in r.text and len(rt.tg.sent) == sent
    with db.new_session() as s:
        assert s.get(Order, order_id).status == "cancelled"
        assert s.exec(select(Service).where(Service.business_id == shop.id, Service.name == "Платье миди бежевое, размер M")).one().stock == stock_after_cancel


def test_site_chat_customer_gets_the_notice_and_a_kyrgyz_chat_stays_kyrgyz(settings, rt, engine):
    from joop.lang import chat_is_kyrgyz

    shop = make("shop", "shop3")
    web_order = order_from(shop.id, "visitor-1", channel="web")
    ky_order = order_from(shop.id, "t9", texts=("Саламатсызбы, беж көйнөктүн M өлчөмүн алайын", "Асель, 0555 112 233"))
    with TestClient(create_app(settings, rt, init=False)) as c:
        panel(c, "shop3")
        r = move(c, web_order, "accepted")
        assert "Клиенту отправлено сообщение." in r.text
        move(c, ky_order, "accepted")
    with db.new_session() as s:
        conv = s.get(Conversation, s.get(Order, web_order).conversation_id)
        staff_msgs = s.exec(select(Message.text).where(Message.conversation_id == conv.id, Message.role == "staff")).all()
    assert staff_msgs == [f"Ваш заказ №{web_order} подтверждён. Сумма: 3 400 сом."]  # the site chat polls «staff» messages
    assert rt.tg.sent[-1] == ("t9", f"Сиздин №{ky_order} буйрутмаңыз ырасталды. Суммасы: 3 400 сом.")
    assert chat_is_kyrgyz(["Асель, 0555 112 233", "беж көйнөктүн M өлчөмүн алайын"])
    assert not chat_is_kyrgyz(["Асель, 0555 112 233", "Хочу платье M"])


def test_restaurant_page_keeps_orders_and_table_codes(settings, rt, engine):
    make("restaurant", "cafe", token=False)
    with TestClient(create_app(settings, rt, init=False)) as c:
        panel(c, "cafe")
        page = c.get("/panel/menu").text
    assert "Ваша публичная страница записи" in page and "кнопка заказа в мессенджер" in page
    assert "Распечатайте QR-коды на столы, витрину или визитки." in page


def test_follow_ups_use_the_niche_lead_time_and_skip_example_people(engine):
    wash = make("carwash", "wash", real=False, token=False)
    with db.new_session() as s:
        b = s.get(Business, wash.id)
        real = Staff(business_id=b.id, name="Бокс А", role="мойка")
        s.add(real)
        s.flush()
        s.add(Slot(business_id=b.id, staff_id=real.id, start=NOW_LOCAL + timedelta(minutes=30), duration_min=60))
        example_first = s.exec(select(Slot).join(Staff).where(Staff.business_id == b.id, Staff.name == "Бокс 1").order_by(Slot.start)).first()
        conv = Conversation(business_id=b.id, channel="telegram", chat_id="w1", created_at=NOW_UTC)
        s.add(conv)
        s.commit()
        text = follow_up_text(s, b, conv, NOW_LOCAL)
    assert (NOW_LOCAL + timedelta(minutes=30)).strftime("%H:%M") in text
    assert example_first.start.strftime("%d.%m %H:%M") not in text


def test_leftover_words_follow_the_niche(settings, rt, engine):
    make("furniture", "mebel")
    make("renovation", "remont")
    with db.new_session() as s:
        job = s.exec(select(Job).join(Business).where(Business.slug == "mebel", Job.number == "20533")).one()
        job.status = "issued"  # delivered: listed among the closed ones
        s.add(job)
        for row in s.exec(select(Staff).join(Business).where(Business.slug == "remont")).all():
            row.active = False  # nobody left to book with
            s.add(row)
        s.commit()
    with TestClient(create_app(settings, rt, init=False)) as c:
        panel(c, "mebel")
        assert "Доставленные и отменённые" in c.get("/panel/jobs").text
        c.get("/logout")
        panel(c, "remont")
        assert "Сначала заполните раздел <a href=\"/panel/staff\">«Замерщики»</a>" in c.get("/panel/slots").text
