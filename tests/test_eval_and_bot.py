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


def test_fallback_and_early_confirmation_are_failures():
    from joop.agent import FALLBACK_TEXT

    # A fallback is never a correct answer, even when every keyword check passes
    assert check_case({"must_not_contain": ["аспирин"]}, FALLBACK_TEXT, False, False) == [
        "no answer: the bot sent the generic fallback"
    ]
    # Recorded 29 Oct 2026: "accepted" said before the phone number was given
    case = {"expect_lead": False, "must_not_contain": ["принята", "кабыл алдым"]}
    reply = "Бермет, маникюр жазуусун кабыл алдым: эртең саат 14:00. Телефон номериңизди жазыңызчы."
    assert check_case(case, reply, False, False) == ["contains forbidden 'кабыл алдым'"]


def test_summary_renders_results(tmp_path):
    import json

    from eval.summary import render

    f = tmp_path / "r.json"
    f.write_text(json.dumps({
        "business_file": "business.example.yaml",
        "summary": {"cases": 2, "passed": 1, "avg_latency_s": 2.0, "max_latency_s": 3.0,
                    "avg_cost_usd_per_conversation": 0.0004, "language_guard_fired": 0},
        "cases": [{"id": "a", "passed": True, "fails": []}, {"id": "b", "passed": False, "fails": ["x"]}],
    }), "utf-8")
    out = render([str(f), str(tmp_path / "missing.json")])
    assert "| business.example.yaml | 1/2 | 2.0 / 3.0 | 0.0004 | 0 |" in out
    assert "- `b`: x" in out and "missing.json | no results" in out
