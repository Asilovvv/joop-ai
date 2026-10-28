from types import SimpleNamespace

from eval.run_eval import summarize
from joop.agent import Agent
from joop.business import BusinessProfile
from joop.pricing import add_usage, cost_usd, empty_usage
from joop.storage import Storage

from .fakes import FakeLLM, response, text, tool

PROFILE = BusinessProfile.from_dict({"name": "Clinic", "description": "Dental clinic"})


def test_cost_uses_published_haiku_rates():
    usage = {"input_tokens": 1_000_000, "output_tokens": 1_000_000,
             "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
    assert cost_usd(usage, "claude-haiku-5-5") == 0.10 + 0.50


def test_unknown_model_has_no_cost():
    assert cost_usd(empty_usage(), "some-other-model") is None


def test_add_usage_ignores_missing_fields_and_none():
    total = empty_usage()
    add_usage(total, None)
    add_usage(total, SimpleNamespace(input_tokens=10, output_tokens=5))
    assert total["input_tokens"] == 10 and total["output_tokens"] == 5
    assert total["cache_read_input_tokens"] == 0


async def test_usage_is_summed_over_tool_rounds_and_stored():
    llm = FakeLLM(
        [
            response(tool("handoff_to_human", {"reason": "x"}), usage={"input_tokens": 1000, "output_tokens": 100}),
            response(text("ok"), usage={"input_tokens": 1200, "output_tokens": 50}),
        ]
    )
    storage = Storage(":memory:")
    agent = Agent(llm=llm, business=PROFILE, storage=storage, model="claude-haiku-5-5")
    r = await agent.reply(1, "позовите человека")
    assert r.usage["input_tokens"] == 2200 and r.usage["output_tokens"] == 150
    assert r.cost_usd == (2200 * 0.10 + 150 * 0.50) / 1_000_000
    stats = storage.stats()
    assert stats["replies"] == 1 and stats["input_tokens"] == 2200
    assert abs(stats["cost_usd"] - r.cost_usd) < 1e-12


def test_summarize():
    results = [
        {"passed": True, "avg_latency_s": 1.0, "usage": {"input_tokens": 10, "output_tokens": 2}, "cost_usd": 0.001},
        {"passed": False, "avg_latency_s": 3.0, "usage": {"input_tokens": 20, "output_tokens": 4}, "cost_usd": 0.003},
    ]
    s = summarize(results)
    assert s["passed"] == 1 and s["avg_latency_s"] == 2.0 and s["max_latency_s"] == 3.0
    assert s["input_tokens"] == 30 and s["avg_cost_usd_per_conversation"] == 0.002
