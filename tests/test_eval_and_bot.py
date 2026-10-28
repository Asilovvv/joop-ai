from pathlib import Path

import pytest
import yaml

from eval.run_eval import check_case, run_case
from joop.business import BusinessProfile

from .fakes import FakeLLM, response, text, tool

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("name", ["cases.yaml", "cases_dental.yaml"])
def test_eval_cases_file_is_valid(name):
    cases = yaml.safe_load((ROOT / "eval" / name).read_text("utf-8"))
    ids = [c["id"] for c in cases]
    assert len(ids) == len(set(ids))
    assert all(c["turns"] for c in cases)


def test_check_case_rules():
    case = {"expect_lead": True, "must_contain_any": ["500"], "must_not_contain": ["сом"]}
    assert check_case(case, "Цена 500", True, False) == []
    assert len(check_case(case, "Цена 600 сом", False, False)) == 3


async def test_run_case_with_fake_llm():
    business = BusinessProfile.from_yaml(ROOT / "business.example.yaml")
    llm = FakeLLM(
        [
            response(tool("save_lead", {"name": "A", "phone": "+996555123456", "service": "Маникюр"})),
            response(text("Заявка принята")),
        ]
    )
    res = await run_case(llm, business, "m", {"id": "x", "turns": ["hi"], "expect_lead": True})
    assert res["passed"], res


def test_bot_router_builds():
    from aiogram import Bot

    from joop.agent import Agent
    from joop.bot import build_router
    from joop.storage import Storage

    business = BusinessProfile.from_yaml(ROOT / "business.example.yaml")
    storage = Storage(":memory:")
    agent = Agent(llm=FakeLLM([]), business=business, storage=storage, model="m")
    router = build_router(agent, storage, Bot("123456:TEST-token"), owner_chat_id=1)
    assert len(router.message.handlers) >= 9


def test_kyrgyz_detection_on_real_replies():
    from eval.run_eval import looks_kyrgyz

    # Replies recorded in the 29 Oct 2026 run
    assert looks_kyrgyz("Кечириңиз, дары-дармек же дозалар боюнча кеңеш бере албайм. Жазылуу үчүн атыңызды жазып жибериңиз.")
    assert not looks_kyrgyz("Да, в клинике есть рентген: прицельный снимок делаем на месте.")
    # A Russian reply that only contains a Kyrgyz name and "Рахмат" is not Kyrgyz
    assert not looks_kyrgyz("Рахмат, Гүлнара! Вашу заявку на детский приём на завтра, 10:00, мы получили.")


def test_language_and_markdown_checks():
    ky_case = {"expect_lang": "ky"}
    assert check_case(ky_case, "Да, рентген есть.", False, False) == ["reply is not in Kyrgyz"]
    assert check_case({}, "Баасы **2500 сом**", False, False) == ["markdown in reply (Telegram shows it as raw symbols)"]
    assert check_case(ky_case, "Ооба, биздин клиникада рентген бар.", False, False) == []
