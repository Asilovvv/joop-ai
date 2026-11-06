"""Stock for goods sold in the chat (joop/stock.py, /panel/stock)."""

from fastapi.testclient import TestClient
from sqlmodel import select

from joop import db, stock
from joop.agent.llm import AgentReply
from joop.models import Business, Order, Service, StockMove
from joop.web.app import create_app

from .conftest import NOW_UTC, FakeLLM
from .test_niches import item, make, say
from .test_web import csrf_of


def _order(b, plov_id, qty, ext):
    llm = FakeLLM([AgentReply("Принято!", order={"lines": [{"item_id": plov_id, "quantity": qty, "note": ""}], "mode": "pickup", "address": "",
                                                "time": "", "name": "Айбек", "phone": "0555 123 456", "comment": ""})])
    return say(b, "плов", llm, ext)


def test_orders_take_stock_refuse_more_than_there_is_and_sell_out(engine):
    b = make("restaurant")
    plov = item(b, "Плов")
    with db.new_session() as s:
        row = s.get(Service, plov.id)
        stock.recount(s, row, 5, 2, "Владелец", NOW_UTC)
        s.commit()
    out = _order(b, plov.id, 3, "s1")
    assert out.order_id and any("Склад: «Плов» осталось 2 шт. (минимум 2)." == n for n in out.admin_notes)
    refused = _order(b, plov.id, 3, "s2")
    assert refused.order_id is None and "«Плов» осталось 2 шт." in refused.reply  # code counts the shelf
    out = _order(b, plov.id, 2, "s3")
    assert any("закончился" in n for n in out.admin_notes)
    with db.new_session() as s:
        row = s.get(Service, plov.id)
        assert row.stock == 0 and row.available is False
        assert [m.reason for m in s.exec(select(StockMove).order_by(StockMove.id)).all()] == ["recount", "order", "order"]
    assert "закончился" in _order(b, plov.id, 1, "s4").reply or "нет в наличии" in _order(b, plov.id, 1, "s5").reply


def test_cancel_returns_goods_once_and_the_page_recounts(engine, settings, rt):
    b = make("restaurant")
    plov = item(b, "Плов")
    with db.new_session() as s:
        stock.recount(s, s.get(Service, plov.id), 1, 0, "Владелец", NOW_UTC)
        biz = s.get(Business, b.id)
        biz.min_order = 0  # one portion is a valid order here
        s.add(biz)
        s.commit()
    order_id = _order(b, plov.id, 1, "c1").order_id
    with TestClient(create_app(settings, rt, init=False)) as c:
        token = csrf_of(c.get("/login").text)
        c.post("/login", data={"slug": b.slug, "password": "x" * 8, "csrf": token})
        page = c.get("/panel/stock").text
        assert "Склад" in page and "закончился" in page and 'href="/panel/stock"' in page
        token = csrf_of(page)
        for _ in range(2):  # cancelling twice returns once
            c.post(f"/panel/orders/{order_id}/status", data={"csrf": token, "status": "cancelled"})
        with db.new_session() as s:
            row = s.get(Service, plov.id)
            assert row.stock == 1 and row.available is True and s.get(Order, order_id).status == "cancelled"
        c.post(f"/panel/stock/{plov.id}", data={"csrf": token, "counted": "7", "minimum": "3"})
        with db.new_session() as s:
            row = s.get(Service, plov.id)
            assert row.stock == 7 and row.stock_min == 3
            assert s.exec(select(StockMove).order_by(StockMove.id.desc())).first().delta == 6
        assert "пересчёт" in c.get("/panel/stock").text
        c.post(f"/panel/stock/{plov.id}", data={"csrf": token, "counted": "", "minimum": "0"})
        with db.new_session() as s:
            assert s.get(Service, plov.id).stock is None  # tracking off
        with db.new_session() as s:
            other = s.exec(select(Business).where(Business.id != b.id)).first()
        if other:
            other_item = None
            with db.new_session() as s:
                other_item = s.exec(select(Service).where(Service.business_id == other.id)).first()
            if other_item:
                assert c.post(f"/panel/stock/{other_item.id}", data={"csrf": token, "counted": "1"}).status_code == 404
