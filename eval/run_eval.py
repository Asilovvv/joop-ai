"""Run the scripted evaluation set against the real model and print metrics.

Usage (needs ANTHROPIC_API_KEY):
    python -m eval.run_eval [business.example.yaml] [eval/cases.yaml]
Writes eval/results.json for the thesis.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import yaml

from joop.agent import Agent
from joop.business import BusinessProfile
from joop.storage import Storage


def check_case(case: dict, final_text: str, lead_saved: bool, handoff: bool) -> list[str]:
    """Return a list of failure reasons (empty = pass)."""
    fails = []
    low = final_text.lower()
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
    for turn in case["turns"]:
        t0 = time.perf_counter()
        r = await agent.reply(1, turn, "eval")
        latencies.append(time.perf_counter() - t0)
        lead = lead or r.lead is not None
        handoff = handoff or r.handoff
        final = r.text
    fails = check_case(case, final, lead, handoff)
    return {
        "id": case["id"],
        "passed": not fails,
        "fails": fails,
        "final_reply": final,
        "lead": lead,
        "handoff": handoff,
        "avg_latency_s": round(sum(latencies) / len(latencies), 2),
    }


async def main() -> None:
    from anthropic import AsyncAnthropic

    from joop.config import Settings

    settings = Settings.from_env(require_telegram=False)
    business = BusinessProfile.from_yaml(sys.argv[1] if len(sys.argv) > 1 else "business.example.yaml")
    cases = yaml.safe_load(Path(sys.argv[2] if len(sys.argv) > 2 else "eval/cases.yaml").read_text("utf-8"))
    llm = AsyncAnthropic(api_key=settings.anthropic_api_key)

    results = [await run_case(llm, business, settings.model, c) for c in cases]
    passed = sum(r["passed"] for r in results)
    for r in results:
        mark = "PASS" if r["passed"] else "FAIL"
        print(f"{mark} {r['id']:<30} {r['avg_latency_s']}s  {'; '.join(r['fails'])}")
    print(f"\n{passed}/{len(results)} passed, model {settings.model}")
    Path("eval/results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), "utf-8")


if __name__ == "__main__":
    asyncio.run(main())
