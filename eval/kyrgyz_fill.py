"""Kyrgyz suggestions for every niche pack's price list and FAQ, from the real model.

Usage (needs ANTHROPIC_API_KEY): python -m eval.kyrgyz_fill [eval/results_kyfill.json]

For each pack the Russian service names and FAQ questions go to joop.kyrgyz.suggest in one call, as the
panel button does. A case passes when the suggestion survives the cleanliness checks (Kyrgyz Cyrillic,
no Kazakh letters, not a copy). The hand-written Kyrgyz wording from the pack is stored beside it as a
reference for the native-speaker review; it is not an answer key.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from joop import kyrgyz
from joop.niches import all_packs
from joop.pricing import cost_usd, empty_usage
from joop.profile import load_profile


def main() -> None:
    from joop.config import get_settings
    from joop.runtime import Runtime

    settings = get_settings()
    if not settings.anthropic_api_key:
        sys.exit("ANTHROPIC_API_KEY is not set (environment or .env)")
    llm = Runtime(settings).get_llm()
    from eval.run_eval import preflight

    problem = preflight(lambda: llm)
    if problem:
        prefix = "::error::" if os.environ.get("GITHUB_ACTIONS") else ""
        sys.exit(f"{prefix}The model {settings.model} does not answer, so the check is skipped: {problem}")
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "eval/results_kyfill.json")
    cases, latencies, usage = [], [], empty_usage()
    for name, pack in sorted(all_packs().items()):
        data = load_profile(pack.demo_file)
        items = [(s.get("name", ""), s.get("name_ky", "")) for s in data.get("services") or []]
        items += [(f.get("q", ""), f.get("q_ky", "")) for f in data.get("faq") or []]
        items = [(src, ref) for src, ref in items if src][: kyrgyz.MAX_ITEMS]
        if not items:
            continue
        started = time.monotonic()
        raw: list = []
        got = kyrgyz.suggest(llm, [src for src, _ in items], usage, raw)
        latencies.append(round(time.monotonic() - started, 2))
        for i, (src, ref) in enumerate(items):
            ky = got[i] if got else ""
            fails = [] if ky else (["call failed"] if got is None else ["suggestion dropped by the checks"])
            cases.append({"id": f"{name}:{i}", "passed": not fails, "fails": fails, "source": src,
                          "final_reply": ky, "reference": ref, "avg_latency_s": latencies[-1],
                          **({"raw": raw} if i == 0 and (got is None or len(raw) > 1) else {})})
        print(f"{name}: {sum(1 for c in cases if c['id'].startswith(name + ':') and c['passed'])}/{len(items)}")
    total = cost_usd(usage, settings.model)
    summary = {"cases": len(cases), "passed": sum(c["passed"] for c in cases),
               "avg_latency_s": round(sum(latencies) / len(latencies), 2) if latencies else 0,
               "max_latency_s": max(latencies, default=0), "total_cost_usd": total,
               "avg_cost_usd_per_conversation": round(total / len(latencies), 6) if total is not None and latencies else None,
               "language_guard_fired": 0, "input_tokens": usage.get("input_tokens", 0), "output_tokens": usage.get("output_tokens", 0)}
    out.write_text(json.dumps({"model": settings.model, "business_file": "kyrgyz_fill (one call per pack)", "summary": summary,
                               "cases": cases}, ensure_ascii=False, indent=2), "utf-8")
    print(f"{summary['passed']}/{summary['cases']} usable suggestions; cost ${total}")


if __name__ == "__main__":
    main()
