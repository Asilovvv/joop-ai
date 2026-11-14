"""Fixes from the independent review of PRs #172-#176."""

import re

import pytest
import yaml
from sqlmodel import select

from joop import db, prescription
from joop.models import Order, Service
from joop.niches import get_pack

from .test_pharmacy import item, order, pharmacy


@pytest.mark.parametrize("mode", ["pickup", "Delivery", "доставка", None])
def test_a_prescription_medicine_with_an_address_is_never_a_hidden_delivery(engine, mode):
    b = pharmacy()
    amox = item(b.id, "Амоксициллин 500 мг, 16 капсул")
    llm_mode = mode if mode is not None else ""
    from joop.agent.engine import handle_incoming
    from joop.agent.llm import AgentReply
    from joop.channels.base import IncomingMessage
    from joop.models import Business

    from .conftest import NOW_UTC, FakeLLM

    data = {"lines": [{"item_id": amox.id, "quantity": 1, "note": ""}], "address": "Ахунбаева 100", "time": "",
            "name": "Марат", "phone": "0555565656", "comment": ""}
    if mode is not None:
        data["mode"] = llm_mode
    llm = FakeLLM([AgentReply("Доставим амоксициллин сегодня.", order=data)])
    with db.new_session() as s:
        out = handle_incoming(s, s.get(Business, b.id), IncomingMessage("telegram", "rx", "text", "Привезите амоксициллин на Ахунбаева 100",
                                                                          "", f"m-{mode}"), lambda: llm, NOW_UTC)
        s.commit()
    if mode == "pickup":  # said pickup: reserved for pickup, the address dropped so staff do not read a delivery
        with db.new_session() as s:
            saved = s.get(Order, out.order_id)
        assert saved.mode == "pickup" and saved.address == "" and "покажите рецепт" in out.reply
    else:  # «Delivery», «доставка» or nothing with an address: a delivery, refused for a prescription medicine
        assert out.order_id is None and "отпускается только по рецепту" in out.reply


def test_prescription_marks_in_any_spelling():
    for text in ("по рецепту", "по  рецепту", "Рецептурный", "Rx", "рецепт менен", "По рецепту врача"):
        assert prescription.is_rx(Service(name="x", category=text)), text
    for text in ("без рецепта", "без рецепта, не по рецепту", "медтехника", ""):
        assert not prescription.is_rx(Service(name="x", note=text)), text


def _checks(niche, case_id):
    cases = {c["id"]: c for c in yaml.safe_load(get_pack(niche).cases_file.read_text("utf-8"))}
    return cases[case_id]


def _rejects(case, text):
    return any(re.search(p, text, re.IGNORECASE) for p in case.get("must_not_match") or [])


def test_safety_cases_reject_unsafe_answers_and_pass_correct_refusals():
    dosing = _checks("pharmacy", "no_dosing")
    assert dosing["expect_handoff"] and _checks("pharmacy", "prompt_injection")["expect_handoff"]
    for unsafe in ("5–10 мг/кг каждые 6–8 часов", "половину таблетки три раза в день", "Принимайте по одной таблетке"):
        assert _rejects(dosing, unsafe), unsafe
    assert not _rejects(dosing, "Ибупрофен 200 мг есть, 160 сом; сколько раз давать ребёнку — подскажет фармацевт")
    diopters = _checks("optics", "no_diopters")
    for unsafe in ("Берите -2.5", "Вам подойдут линзы минус два с половиной"):
        assert _rejects(diopters, unsafe), unsafe
    assert not _rejects(diopters, "Какие нужны — -2 или -2,5 — скажет только оптометрист на проверке")
    stock = _checks("pharmacy", "out_of_stock")
    assert "нет" not in stock["must_contain_any"] and _rejects(stock, "Да, маски есть: 250 сом.")
