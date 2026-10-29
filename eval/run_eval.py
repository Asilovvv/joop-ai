"""Run the scripted evaluation set against the real model and print metrics.

Usage (needs ANTHROPIC_API_KEY):
    python -m eval.run_eval [business.example.yaml] [eval/cases.yaml]
Writes eval/results.json for the thesis.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
import time
from pathlib import Path

import yaml

from joop.agent import FALLBACK_TEXT, Agent
from joop.business import BusinessProfile
from joop.lang import KY_REPLY_MARKERS as KY_MARKERS, looks_kyrgyz  # noqa: F401  (re-exported for tests)
from joop.pricing import cost_usd, empty_usage
from joop.storage import Storage


def check_case(case: dict, final_text: str, lead_saved: bool, handoff: bool) -> list[str]:
    """Return a list of failure reasons (empty = pass)."""
    fails = []
    low = final_text.lower()
    if final_text.strip() == FALLBACK_TEXT:
        fails.append("no answer: the bot sent the generic fallback")
    if "**" in final_text or re.search(r"(?m)^#{1,6} ", final_text):
        fails.append("markdown in reply (Telegram shows it as raw symbols)")
    if case.get("expect_lang") == "ky" and not looks_kyrgyz(final_text):
        fails.append("reply is not in Kyrgyz")
    if "expect_lead" in case and bool(case["expect_lead"]) != lead_saved:
        fails.append(f"expect_lead={case['expect_lead']} got {lead_saved}")
    if "expect_handoff" in case and bool(case["expect_handoff"]) != handoff:
        fails.append(f"expect_handoff={case['expect_handoff']} got {handoff}")
    any_of = case.get("must_contain_any")
    if any_of and not any(s.lower() in low for s in any_of):
        fails.append(f"missing any of {any_of}")
    for s in case.get("must_not_contain", []):
        if s.lower() in low:
            fails.append(f"contains forbidden '{s}'")
    return fails


async def run_case(llm, business, model, case) -> dict:
    agent = Agent(llm=llm, business=business, storage=Storage(":memory:"), model=model)
    lead = handoff = False
    final = ""
    latencies = []
    usage = empty_usage()
    language_fixed = False
    for turn in case["turns"]:
        t0 = time.perf_counter()
        r = await agent.reply(1, turn, "eval")
        latencies.append(time.perf_counter() - t0)
        lead = lead or r.lead is not None
        handoff = handoff or r.handoff
        final = r.text
        language_fixed = language_fixed or r.language_fixed
        for k in usage:
            usage[k] += r.usage.get(k, 0)
    fails = check_case(case, final, lead, handoff)
    return {
        "id": case["id"],
        "passed": not fails,
        "fails": fails,
        "final_reply": final,
        "lead": lead,
        "handoff": handoff,
        "avg_latency_s": round(sum(latencies) / len(latencies), 2),
        "usage": usage,
        "cost_usd": cost_usd(usage, model),
        "language_fixed": language_fixed,
    }


def summarize(results: list[dict]) -> dict:
    """Aggregate metrics for the thesis table."""
    n = len(results)
    costs = [r["cost_usd"] for r in results if r.get("cost_usd") is not None]
    return {
        "cases": n,
        "passed": sum(r["passed"] for r in results),
        "avg_latency_s": round(sum(r["avg_latency_s"] for r in results) / n, 2) if n else None,
        "max_latency_s": max((r["avg_latency_s"] for r in results), default=None),
        "input_tokens": sum(r.get("usage", {}).get("input_tokens", 0) for r in results),
        "output_tokens": sum(r.get("usage", {}).get("output_tokens", 0) for r in results),
        "avg_cost_usd_per_conversation": round(sum(costs) / len(costs), 6) if costs else None,
        "total_cost_usd": round(sum(costs), 6) if costs else None,
        "language_guard_fired": sum(1 for r in results if r.get("language_fixed")),
    }


async def main() -> None:
    from anthropic import AsyncAnthropic

    from joop.config import Settings

    settings = Settings.from_env(require_telegram=False)
    business = BusinessProfile.from_yaml(sys.argv[1] if len(sys.argv) > 1 else "business.example.yaml")
    cases = yaml.safe_load(Path(sys.argv[2] if len(sys.argv) > 2 else "eval/cases.yaml").read_text("utf-8"))
    llm = AsyncAnthropic(api_key=settings.anthropic_api_key)

    results = [await run_case(llm, business, settings.model, c) for c in cases]
    for r in results:
        mark = "PASS" if r["passed"] else "FAIL"
        print(f"{mark} {r['id']:<30} {r['avg_latency_s']}s  {'; '.join(r['fails'])}")
    summary = summarize(results)
    print(f"\n{summary['passed']}/{summary['cases']} passed, model {settings.model}")
    print(f"Language guard rewrote replies in {summary['language_guard_fired']} case(s)")
    if summary["avg_cost_usd_per_conversation"] is not None:
        print(f"Average cost per conversation: ${summary['avg_cost_usd_per_conversation']:.6f}; "
              f"total ${summary['total_cost_usd']:.6f}")
    out = Path(sys.argv[3]) if len(sys.argv) > 3 else Path("eval/results.json")
    out.write_text(
        json.dumps({"model": settings.model, "business_file": str(sys.argv[1] if len(sys.argv) > 1 else "business.example.yaml"),
                    "summary": summary, "cases": results}, ensure_ascii=False, indent=2),
        "utf-8",
    )
    print(f"Saved to {out}")


if __name__ == "__main__":
    asyncio.run(main())
