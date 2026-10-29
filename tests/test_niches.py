from datetime import datetime

import pytest
from sqlmodel import select

from joop import db
from joop.agent.engine import handle_incoming
from joop.agent.llm import AgentReply, coerce_reply, response_schema
from joop.channels.base import IncomingMessage
from joop.models import Business, Lead, Order, OrderLine, Service, Slot, Staff
from joop.niches import all_packs, get_pack
from joop.presets import create_business
from joop.profile import load_profile

from .conftest import NOW_UTC, FakeLLM

ALL = sorted(all_packs())


def make(niche):
    with db.new_session() as s:
        b = create_business(s, slug=f"t-{niche}", name="", password="x" * 8, niche=niche, demo=True, now_utc=NOW_UTC)
        s.commit()
        return b


def say(business, text, llm, ext):
    with db.new_session() as s:
        b = s.get(Business, business.id)
        out = handle_incoming(s, b, IncomingMessage("telegram", "c1", "text", text, "", ext), lambda: llm, NOW_UTC)
        s.commit()
        return out


def item(business, name):
    with db.new_session() as s:
        return s.exec(select(Service).where(Service.business_id == business.id, Service.name == name)).one()


@pytest.mark.parametrize("niche", ALL)
def test_every_pack_has_demo_and_cases(niche, engine):
    pack = get_pack(niche)
    assert pack.demo_file.exists() and load_profile(pack.demo_file)["niche"] == niche
    if niche != "other":
        assert pack.cases_file.exists(), niche
    b = make(niche)
    llm = FakeLLM([AgentReply("Здравствуйте!")])
    say(b, "Здравствуйте", llm, "hello")
    system, schema = llm.calls[0]["system"], llm.calls[0]["schema"]
    assert pack.who in system
    assert set(schema["properties"]) - {"reply", "handoff"} == (
        ({"booking"} if pack.has("booking") or pack.has("request") else set())
        | ({"order"} if pack.has("order") else set())
        | ({"lead"} if pack.has("lead") else set())
    )
    for rule in pack.rules:
        assert rule in system


def test_restaurant_order_total_is_computed_by_code(engine):
    b = make("restaurant")
    plov, tea = item(b, "Плов"), item(b, "Чай чёрный, чайник")
    llm = FakeLLM([AgentReply("Принято, ждём вас к 19:00.", order={
        "lines": [{"item_id": plov.id, "quantity": 2, "note": ""}, {"item_id": tea.id, "quantity": 1, "note": "с лимоном"}],
        "mode": "pickup", "address": "", "time": "19:00", "name": "Айбек", "phone": "0555 123 456", "comment": "",
    })])
    out = say(b, "2 плова и чай, заберу в 19:00, Айбек 0555123456", llm, "o1")
    assert out.order_id and out.reply.endswith("Сумма заказа: 820 сом.")
    assert "Новый заказ" in out.admin_notes[0] and "2 × Плов" in out.admin_notes[0] and "с лимоном" in out.admin_notes[0]
    with db.new_session() as s:
        order = s.get(Order, out.order_id)
        assert order.total == 820 and order.customer_phone == "+996555123456" and order.mode == "pickup"
        assert len(s.exec(select(OrderLine).where(OrderLine.order_id == order.id)).all()) == 2
    # the prompt shows item ids and hides the stop list
    system = llm.calls[0]["system"]
    assert f"[{plov.id}] Плов" in system and "Сейчас нет в наличии (не предлагай): Борщ" in system


def test_order_rejects_stop_list_unknown_items_and_missing_address(engine):
    b = make("restaurant")
    borsch = item(b, "Борщ")
    base = {"mode": "pickup", "address": "", "time": "", "name": "Айбек", "phone": "0555123456", "comment": ""}
    llm = FakeLLM([
        AgentReply("Готово!", order={**base, "lines": [{"item_id": borsch.id, "quantity": 1, "note": ""}]}),
        AgentReply("Готово!", order={**base, "lines": [{"item_id": 999999, "quantity": 1, "note": ""}]}),
        AgentReply("Готово!", order={**base, "mode": "delivery", "lines": [{"item_id": item(b, "Плов").id, "quantity": 1, "note": ""}]}),
        AgentReply("Готово!", order={**base, "lines": [{"item_id": item(b, "Плов").id, "quantity": 500, "note": ""}]}),
    ])
    assert "«Борщ» сейчас нет в наличии" in say(b, "борщ", llm, "o2").reply
    assert "одной позиции нет в списке" in say(b, "суши", llm, "o3").reply
    assert say(b, "доставка", llm, "o4").reply == "Напишите, пожалуйста, адрес доставки."
    assert "количество «Плов» должно быть от 1 до 50" in say(b, "500 пловов", llm, "o5").reply
    with db.new_session() as s:
        assert s.exec(select(Order)).all() == []


def test_order_with_inexact_price_has_no_total(engine):
    b = make("auto")  # auto has no order outcome: the order must be ignored
    llm = FakeLLM([AgentReply("Ок", order={"lines": [{"item_id": 1, "quantity": 1, "note": ""}], "mode": "pickup", "address": "", "time": "", "name": "А", "phone": "0555123456", "comment": ""})])
    assert say(b, "x", llm, "o6").order_id is None


def test_table_booking_checks_party_size(engine):
    b = make("restaurant")
    with db.new_session() as s:
        small = s.exec(select(Slot).join(Staff).where(Staff.business_id == b.id, Staff.name == "Стол 1").order_by(Slot.start)).first()
    booking = {"slot_id": small.id, "name": "Айбек", "phone": "0555123456", "service": "ужин", "preferred_time": ""}
    llm = FakeLLM([
        AgentReply("Забронировала!", booking={**booking, "party_size": 0}),
        AgentReply("Забронировала!", booking={**booking, "party_size": 5}),
        AgentReply("Забронировала стол на двоих.", booking={**booking, "party_size": 2}),
    ])
    assert say(b, "стол", llm, "t1").reply.startswith("Сколько будет гостей?")
    big = say(b, "нас пятеро", llm, "t2")
    assert big.booking_id is None and big.reply.startswith("Этот стол рассчитан на 2 гостей. Подойдут:")
    assert "Стол 1" not in big.reply.split("Подойдут:")[1]
    ok = say(b, "нас двое", llm, "t3")
    assert ok.booking_id
    with db.new_session() as s:
        assert s.get(Slot, small.id).status == "booked"


def test_realty_qualified_lead(engine):
    b = make("realty")
    llm = FakeLLM([AgentReply("Спасибо! Агент свяжется с вами сегодня.", lead={"name": "Жылдыз", "phone": "0700 111 222", "details": "Покупка; бюджет: до 80 000 $; район: Джал; комнат: 2"})])
    out = say(b, "Ищу двушку в Джале до 80 тысяч", llm, "l1")
    assert out.qualified_lead_id and out.admin_notes[0].startswith("Новый лид")
    assert "район: Джал" in out.admin_notes[0]
    with db.new_session() as s:
        lead = s.get(Lead, out.qualified_lead_id)
        assert lead.kind == "lead" and lead.customer_phone == "+996700111222"
    assert "покупка или аренда, бюджет, район" in llm.calls[0]["system"]


def test_wholesale_has_no_bookings(engine):
    b = make("wholesale")
    llm = FakeLLM([AgentReply("Ок", booking={"slot_id": None, "name": "А", "phone": "0555123456", "service": "x", "preferred_time": "", "party_size": 0})])
    out = say(b, "x", llm, "w1")
    assert out.request_id is None and out.booking_id is None
    assert "Свободное время" not in llm.calls[0]["system"]


def test_coerce_order_and_lead():
    r = coerce_reply({"reply": "ok", "order": {"lines": [{"item_id": "3", "quantity": "2"}], "mode": "pickup", "name": "А"}, "lead": {"name": "Б", "phone": "1"}, "handoff": None})
    assert r.order["lines"] == [{"item_id": 3, "quantity": 2, "note": ""}] and r.order["phone"] == ""
    assert r.lead == {"name": "Б", "phone": "1", "details": ""}
    assert "order" in response_schema({"order"})["properties"]


@pytest.mark.parametrize("niche", [n for n in ALL if n != "other"])
def test_pack_cases_are_well_formed(niche):
    import yaml

    from joop.lang import is_kyrgyz_message

    cases = yaml.safe_load(get_pack(niche).cases_file.read_text("utf-8"))
    assert len(cases) >= 12 and len({c["id"] for c in cases}) == len(cases)
    assert sum(1 for c in cases if c.get("expect_lang") == "ky") >= 4
    for case in cases:
        if case.get("expect_lang") == "ky":
            assert is_kyrgyz_message(case["turns"][0]), case["id"]
        else:
            assert not any(is_kyrgyz_message(t) for t in case["turns"]), case["id"]


def test_eval_runs_a_pack_with_orders(tmp_path):
    import json

    from eval.run_eval import run

    pack = get_pack("restaurant")
    cases = [{"id": "order", "turns": ["2 плова на вынос, Айбек 0555123456, к 19:00"], "expect_order": True}]
    f = tmp_path / "cases.yaml"
    f.write_text(json.dumps(cases, ensure_ascii=False), "utf-8")

    def scripted(system, messages):
        import re

        plov = re.search(r"\[(\d+)\] Плов", system).group(1)
        return AgentReply("Готово, ждём к 19:00.", order={"lines": [{"item_id": int(plov), "quantity": 2, "note": ""}], "mode": "pickup",
                                                          "address": "", "time": "19:00", "name": "Айбек", "phone": "0555123456", "comment": ""})

    data = run(str(pack.demo_file), str(f), lambda: FakeLLM([scripted]), "claude-haiku-5-5")
    assert data["summary"]["passed"] == 1, data["cases"]
    assert data["cases"][0]["final_reply"].endswith("Сумма заказа: 700 сом.")


def test_min_order_and_delivery_fee(engine):
    b = make("restaurant")  # demo: min order 600, delivery 150, free from 2000
    plov, shashlik = item(b, "Плов"), item(b, "Шашлык из баранины")
    base = {"address": "Киевская 1", "time": "", "name": "Айбек", "phone": "0555123456", "comment": ""}
    llm = FakeLLM([
        AgentReply("Готово.", order={**base, "mode": "delivery", "lines": [{"item_id": plov.id, "quantity": 1, "note": ""}]}),
        AgentReply("Готово.", order={**base, "mode": "delivery", "lines": [{"item_id": plov.id, "quantity": 2, "note": ""}]}),
        AgentReply("Готово.", order={**base, "mode": "delivery", "lines": [{"item_id": shashlik.id, "quantity": 5, "note": ""}]}),
        AgentReply("Готово.", order={**base, "mode": "pickup", "lines": [{"item_id": plov.id, "quantity": 2, "note": ""}]}),
    ])
    small = say(b, "1 плов", llm, "m1")
    assert small.order_id is None and small.reply.startswith("Минимальная сумма заказа — 600 сом, сейчас в заказе на 350 сом.")
    assert say(b, "2 плова", llm, "m2").reply.endswith("Сумма заказа: 850 сом, включая доставку 150 сом.")
    assert say(b, "5 шашлыков", llm, "m3").reply.endswith("Сумма заказа: 2 250 сом.")
    assert say(b, "2 плова сам", llm, "m4").reply.endswith("Сумма заказа: 700 сом.")
    assert "Условия заказа: минимальная сумма заказа 600 сом; доставка 150 сом; бесплатная доставка от 2000 сом." in llm.calls[0]["system"]


def test_large_catalog_sends_only_relevant_items(engine):
    b = make("wholesale")
    with db.new_session() as s:
        for i in range(120):
            s.add(Service(business_id=b.id, name=f"Товар {i}: кружка керамическая" if i % 30 == 0 else f"Товар {i}: полотенце", price="100", category="посуда" if i % 30 == 0 else "текстиль", sort=100 + i))
        s.commit()
    llm = FakeLLM([AgentReply("Есть кружки.")])
    say(b, "Есть керамические кружки?", llm, "big")
    system = llm.calls[0]["system"]
    assert "кружка керамическая" in system and "Товар 1: полотенце" not in system
    assert "позиций, подходящих к вопросу клиента. Категории: дом, посуда, текстиль." in system


def test_select_relevant_falls_back_to_first_items():
    from types import SimpleNamespace

    from joop.catalog import select_relevant

    items = [SimpleNamespace(name=f"x{i}", name_ky="", category="", note="") for i in range(10)]
    assert select_relevant(items, ["ничего общего"], limit=3) == items[:3]
