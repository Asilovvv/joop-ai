from pathlib import Path

import pytest
import yaml

from joop.agent import Agent
from joop.business import BusinessProfile
from joop.lang import is_kyrgyz_message, looks_kyrgyz
from joop.storage import Storage

from .fakes import FakeLLM, response, text, tool

ROOT = Path(__file__).resolve().parent.parent
PROFILE = BusinessProfile.from_dict(
    {"name": "Test Clinic", "description": "Clinic", "services": [{"name": "Удаление зуба", "name_ky": "Тиш жулуу", "price": "1500 сом"}]}
)
RU_DRAFT = "Удаление зуба стоит 1500 сом. Записать вас?"
KY_TRANSLATION = "Тиш жулуу 1500 сом турат. Сизди жазып коёлубу? Атыңызды жана номериңизди жазыңыз."


def make_agent(llm):
    return Agent(llm=llm, business=PROFILE, storage=Storage(":memory:"), model="test-model")


@pytest.mark.parametrize("name", ["cases.yaml", "cases_dental.yaml"])
def test_message_language_matches_eval_labels(name):
    """Every turn of a Kyrgyz-labelled case is detected as Kyrgyz; Russian-only cases are not."""
    cases = yaml.safe_load((ROOT / "eval" / name).read_text("utf-8"))
    for case in cases:
        if case.get("expect_lang") == "ky":
            assert is_kyrgyz_message(case["turns"][0]), case["id"]
        elif not case["id"].startswith("mixed"):
            for turn in case["turns"]:
                assert not is_kyrgyz_message(turn), (case["id"], turn)


def test_mixed_message_with_russian_majority_is_not_kyrgyz():
    assert not is_kyrgyz_message("Саламатсызбы, маникюр сколько стоит?")
    assert is_kyrgyz_message("Рахмат")


async def test_guard_rewrites_russian_reply_to_kyrgyz_message():
    llm = FakeLLM([
        response(text(RU_DRAFT), usage={"input_tokens": 100, "output_tokens": 20}),
        response(text(KY_TRANSLATION), usage={"input_tokens": 30, "output_tokens": 25}),
    ])
    agent = make_agent(llm)
    r = await agent.reply(1, "Тиш жулуу канча турат?")
    assert r.text == KY_TRANSLATION and r.language_fixed
    assert len(llm.calls) == 2
    second = llm.calls[1]
    assert "tools" not in second  # the rewrite cannot save leads or hand off
    assert second["messages"] == [{"role": "user", "content": RU_DRAFT}]
    assert r.usage["input_tokens"] == 130 and r.usage["output_tokens"] == 45
    # history stores what the customer actually received
    assert agent.storage.history(1)[-1]["content"] == KY_TRANSLATION


async def test_guard_skips_russian_messages_and_kyrgyz_replies():
    llm = FakeLLM([response(text(RU_DRAFT))])
    r = await make_agent(llm).reply(1, "Сколько стоит удаление зуба?")
    assert r.text == RU_DRAFT and not r.language_fixed and len(llm.calls) == 1

    llm = FakeLLM([response(text(KY_TRANSLATION))])
    r = await make_agent(llm).reply(1, "Тиш жулуу канча турат?")
    assert r.text == KY_TRANSLATION and not r.language_fixed and len(llm.calls) == 1


async def test_guard_keeps_draft_when_rewrite_is_not_kyrgyz_or_fails():
    llm = FakeLLM([response(text(RU_DRAFT)), response(text("Удаление зуба: 1500 сом."))])
    r = await make_agent(llm).reply(1, "Тиш жулуу канча турат?")
    assert r.text == RU_DRAFT and not r.language_fixed

    llm = FakeLLM([response(text(RU_DRAFT))])  # second call raises: no scripted response
    r = await make_agent(llm).reply(1, "Тиш жулуу канча турат?")
    assert r.text == RU_DRAFT and not r.language_fixed


async def test_guard_runs_after_a_saved_lead_without_saving_twice():
    llm = FakeLLM([
        response(tool("save_lead", {"name": "Нургуль", "phone": "0555987654", "service": "Тиш жулуу"})),
        response(text("Спасибо, Нургуль! Заявка принята, администратор скоро позвонит.")),
        response(text("Рахмат, Нургуль! Сиздин арызыңыз кабыл алынды, администратор жакында чалат.")),
    ])
    agent = make_agent(llm)
    r = await agent.reply(1, "Атым Нургуль, телефон 0555 987 654, тиш жулдургум келет")
    assert r.lead is not None and r.language_fixed
    assert len(agent.storage.recent_leads()) == 1


def test_kyrgyz_service_names_are_rendered():
    rendered = PROFILE.render()
    assert "Удаление зуба (in Kyrgyz: Тиш жулуу)" in rendered
    for f in ["business.example.yaml", "business.dental.example.yaml"]:
        profile = BusinessProfile.from_yaml(ROOT / f)
        assert all(s.name_ky for s in profile.services), f
