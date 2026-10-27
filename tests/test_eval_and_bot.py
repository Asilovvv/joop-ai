from pathlib import Path

import yaml

from eval.run_eval import check_case, run_case
from joop.business import BusinessProfile

from .fakes import FakeLLM, response, text, tool

ROOT = Path(__file__).resolve().parent.parent


def test_eval_cases_file_is_valid():
    cases = yaml.safe_load((ROOT / "eval" / "cases.yaml").read_text("utf-8"))
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
