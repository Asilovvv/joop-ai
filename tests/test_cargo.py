"""Cargo and moving (joop/niches/cargo): the code finds the route in the price list, the model repeats it."""

from joop import db, routes
from joop.agent.engine import handle_incoming
from joop.agent.llm import AgentReply
from joop.channels.base import IncomingMessage
from joop.models import Business, Lead
from joop.niches import get_pack
from joop.presets import create_business

from .conftest import NOW_UTC, FakeLLM


def company(niche="cargo", slug="juk"):
    with db.new_session() as s:
        b = create_business(s, slug=slug, name="Жүк", password="juk-pass-123", niche=niche, demo=True, now_utc=NOW_UTC)
        b.example_ok = True  # its price list is its own
        s.commit()
        return b


def say(business_id, text, llm, ext, chat="g1"):
    with db.new_session() as s:
        out = handle_incoming(s, s.get(Business, business_id), IncomingMessage("telegram", chat, "text", text, "", ext), lambda: llm, NOW_UTC)
        s.commit()
        return out


def test_places_are_read_in_russian_kyrgyz_and_latin():
    assert routes.places_in("Из Джалал-Абада в Бишкек, 1 тонна?") == ["Джалал-Абад", "Бишкек"]
    assert routes.places_in("Бишкектен Ошко жүк") == ["Бишкек", "Ош"]
    assert routes.places_in("Osh to Bishkek") == ["Ош", "Бишкек"]
    assert routes.places_in("Нарынга, Каракола") == ["Нарын", "Каракол"]
    assert routes.places_in("кошка, кантип, ошол") == []  # words that only contain a place name
    assert routes.route_of("Бишкек — Ош, Газель до 2 т") == frozenset({"Бишкек", "Ош"})
    assert routes.route_of("Переезд по Бишкеку, Газель (до 2 т)") is None


def test_the_route_is_found_either_way_and_a_missing_one_is_said(engine):
    pack = get_pack("cargo")
    assert pack.offers("route_price") and pack.has("lead") and not pack.has("booking")
    b = company()
    llm = FakeLLM([AgentReply("Откуда и куда?"), AgentReply("От 20 000 сом."), AgentReply("Уточню у менеджера.")])
    say(b.id, "Сколько стоит перевозка?", llm, "a")
    say(b.id, "Из Джалал-Абада в Бишкек, 1 тонна", llm, "b")
    say(b.id, "А из Бишкека в Баткен?", llm, "c", chat="g2")
    nothing, found, missing = (c["system"] for c in llm.calls)
    assert "(проверено системой)" not in nothing
    assert "Маршрут Джалал-Абад — Бишкек найден в прайсе (проверено системой):" in found
    assert "- Бишкек — Джалал-Абад, Газель до 2 т: от 20 000 (за рейс)" in found
    hint = found.split("найден в прайсе (проверено системой):")[1].split("Называй только эти цены")[0]
    assert "Бишкек — Ош" not in hint and hint.count("\n- ") == 1
    assert "Маршрута Бишкек — Баткен нет в прайсе (проверено системой). Цену не называй" in missing


def test_an_earlier_message_keeps_the_route(engine):
    b = company()
    llm = FakeLLM([AgentReply("От 22 000."), AgentReply("Записала заявку.", lead={
        "name": "Эрлан", "phone": "0555787878", "details": "Бишкек — Ош; мебель; 1,5 т; суббота"})])
    say(b.id, "Бишкектен Ошко канча?", llm, "a")
    out = say(b.id, "Мебель 1,5 тонны, в субботу. Эрлан 0555 787 878", llm, "b")
    assert "Маршрут Бишкек — Ош найден в прайсе" in llm.calls[1]["system"]
    assert out.qualified_lead_id
    with db.new_session() as s:
        assert "Бишкек — Ош" in s.get(Lead, out.qualified_lead_id).details


def test_other_niches_get_no_route_hint(engine):
    b = company("wholesale", "opt")
    llm = FakeLLM([AgentReply("Уточню.")])
    say(b.id, "Доставка из Бишкека в Ош сколько?", llm, "a")
    assert "в прайсе (проверено системой)" not in llm.calls[0]["system"]
