"""Fixes from the independent review of PRs #164-#169."""

import json

import httpx
from fastapi.testclient import TestClient
from sqlmodel import select

from joop import area_price, db, repeat_order, routes
from joop.agent.engine import handle_incoming
from joop.agent.llm import AgentReply
from joop.agent.openai_compat import OpenAICompatLLM
from joop.channels.base import IncomingMessage
from joop.models import Booking, Business, Conversation, Order, Service, Slot, Staff
from joop.presets import create_business
from joop.web.app import create_app

from .conftest import NOW_UTC, FakeLLM


def make(niche, slug):
    with db.new_session() as s:
        b = create_business(s, slug=slug, name=slug.title(), password="pass-12345", niche=niche, demo=True, now_utc=NOW_UTC)
        b.example_ok = True
        s.commit()
        return b


def say(business_id, text, llm, ext, chat="r1"):
    with db.new_session() as s:
        out = handle_incoming(s, s.get(Business, business_id), IncomingMessage("telegram", chat, "text", text, "", ext), lambda: llm, NOW_UTC)
        s.commit()
        return out


def test_a_flat_number_is_not_the_area_and_a_rug_is_not_priced_by_the_flat():
    assert area_price.area_in(["Квартира 60 м², Асанбай 12 кв 40"]) == 60
    assert area_price.area_in(["Двушка 54 кв.м, Джал 29 кв 15"]) == 54
    assert area_price.area_in(["Асанбай 12, кв 40"]) is None


def test_cleaning_estimate_names_only_the_service_asked_about(engine):
    b = make("cleaning", "clean")
    llm = FakeLLM([AgentReply("От 8 400 сом.")])
    say(b.id, "Генеральная уборка квартиры 70 м², Джал 23 кв 15", llm, "a")
    hint = llm.calls[0]["system"].split("Расчёт по площади 70 м²")[1].split("Называй только")[0]
    assert "- Генеральная уборка: от 8 400 сом" in hint and "Химчистка ковра" not in hint and "Поддерживающая" not in hint


def test_route_needs_from_and_to_and_skips_places_inside_a_city():
    assert routes.route_in("Газель с Ош базара до Бишкек Парка, сколько?") is None
    assert routes.route_in("Я живу в Бишкеке, нужно перевезти груз из Оша в Джалал-Абад") == ("Ош", "Джалал-Абад")
    assert routes.route_in("Бишкек, Ош, Нарын — что дешевле?") is False
    assert routes.route_in("Оштон Бишкекке") == ("Ош", "Бишкек")
    assert routes.route_in("Токмоктон Нарынга") == ("Токмок", "Нарын")
    assert routes.route_in("из Алма-Аты в Бишкек") == ("Алматы", "Бишкек")
    assert routes.route_of("Бишкек-Ош, Газель") == routes.route_of("Бишкек—Ош") == frozenset({"Бишкек", "Ош"})


def test_cargo_hint_for_three_cities_and_for_lines_off_sale(engine):
    b = make("cargo", "juk")
    with db.new_session() as s:
        osh = s.exec(select(Service).where(Service.business_id == b.id, Service.name == "Бишкек — Ош, Газель до 2 т")).one()
        osh.available = False
        s.add(osh)
        s.commit()
    llm = FakeLLM([AgentReply("Откуда и куда?"), AgentReply("Уточню.")])
    say(b.id, "Бишкек, Ош, Нарын — куда дешевле?", llm, "a")
    say(b.id, "Из Бишкека в Ош сколько?", llm, "b", chat="r2")
    assert "Клиент назвал больше двух городов (проверено системой). Уточни, откуда и куда" in llm.calls[0]["system"]
    assert "Маршрута Бишкек — Ош нет в прайсе (проверено системой)" in llm.calls[1]["system"]  # off sale: not priced


def test_a_route_is_found_in_a_catalog_too_large_for_the_prompt(engine):
    b = make("cargo", "juk2")
    with db.new_session() as s:
        for i in range(90):
            s.add(Service(business_id=b.id, name=f"Коробка картонная №{i}", price="50"))
        s.commit()
    llm = FakeLLM([AgentReply("От 12 000.")])
    say(b.id, "Сколько из Бишкека в Каракол?", llm, "a")
    assert "Маршрут Бишкек — Каракол найден в прайсе (проверено системой):" in llm.calls[0]["system"]


def _client(answers, seen):
    def handler(request):
        seen.append(json.loads(request.content))
        status, body = answers.pop(0)
        return httpx.Response(status, json=body) if isinstance(body, dict) else httpx.Response(status, text=body)
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_only_a_format_error_lowers_the_output_format():
    seen = []
    ok = {"choices": [{"message": {"content": '{"reply": "ok"}'}}], "usage": {}}
    llm = OpenAICompatLLM("https://api.example.test/v1", "k", "m", http=_client(
        [(400, "This model's maximum context length is 8192 tokens"), (200, ok)], seen))
    try:
        llm.respond("s", [{"role": "user", "content": "x"}])
    except Exception as exc:
        assert "400" in str(exc)
    assert llm.format == "json_schema" and len(seen) == 1  # a long dialogue did not cost every later customer the schema
    assert llm.respond("s", [{"role": "user", "content": "x"}]).reply == "ok"


def test_a_gateway_page_is_a_model_error_and_a_rewrite_sends_the_draft():
    llm = OpenAICompatLLM("https://api.example.test/v1", "k", "m", http=_client([(200, "<html>502</html>"), (200, "<html>")], []))
    try:
        llm.respond("s", [{"role": "user", "content": "x"}])
        raise AssertionError("expected LLMError")
    except Exception as exc:
        assert type(exc).__name__ == "LLMError" and "non-JSON" in str(exc)
    assert llm.remove_false_confirmation("Записала.", {"input_tokens": 0, "output_tokens": 0}) is None


def test_the_test_chat_repeats_its_own_order(engine):
    from joop.web.saas import TRY_CHAT_ID

    b = make("water", "suu")
    with db.new_session() as s:
        water = s.exec(select(Service).where(Service.business_id == b.id, Service.name == "Вода питьевая, бутыль 19 л")).one()
    llm = FakeLLM([AgentReply("Оформила.", order={"lines": [{"item_id": water.id, "quantity": 2, "note": ""}], "mode": "delivery",
                                                  "address": "Джал 23", "time": "", "name": "Владелец", "phone": "0555000111", "comment": ""})])
    with db.new_session() as s:
        out = handle_incoming(s, s.get(Business, b.id), IncomingMessage("console", TRY_CHAT_ID, "text", "2 бутыля, Джал 23, 0555 000 111", "", "t1"),
                              lambda: llm, NOW_UTC)
        s.commit()
        conv = s.get(Conversation, s.get(Order, out.order_id).conversation_id)
        assert "Прошлый заказ этого клиента" in repeat_order.prompt_hint(s, s.get(Business, b.id), conv, NOW_UTC)
        stranger = Conversation(business_id=b.id, channel="telegram", chat_id="x", customer_phone="+996555000111", customer_name="Владелец")
        s.add(stranger)
        s.flush()
        assert repeat_order.prompt_hint(s, s.get(Business, b.id), stranger, NOW_UTC) == ""  # a test order is not a real customer's


def test_mobile_api_leaves_out_staff_test_chats_and_far_dates(settings, rt, engine, business):
    from joop.web.app import _login_fails

    from .test_mobile import TOMORROW, auth, book, sign_in

    with db.new_session() as s:
        slots = s.exec(select(Slot).where(Slot.business_id == business.id, Slot.start >= TOMORROW).order_by(Slot.start)).all()[:2]
        conv = Conversation(business_id=business.id, channel="telegram", chat_id="owner", staff_test=True)
        s.add(conv)
        s.commit()
        conv_id = conv.id
    real = book(business.id, slots[0], name="Айгуль")
    test = book(business.id, slots[1], name="Владелец проверяет", channel="telegram")
    with db.new_session() as s:
        row = s.get(Booking, test)
        row.conversation_id = conv_id  # the owner tried his own bot
        s.add(row)
        s.commit()
    _login_fails.clear()
    with TestClient(create_app(settings, rt, init=False)) as c:
        headers = auth(sign_in(c).json()["token"])
        ids = [r["id"] for r in c.get(f"/api/mobile/bookings?day={TOMORROW.date().isoformat()}", headers=headers).json()["bookings"]]
        assert real in ids and test not in ids
        assert c.get("/api/mobile/bookings?day=9999-12-31", headers=headers).status_code == 400
