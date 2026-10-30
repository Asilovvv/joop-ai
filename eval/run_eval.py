"""Run a scripted evaluation set against the real model and print metrics.

Usage (needs ANTHROPIC_API_KEY in the environment or .env):
    python -m eval.run_eval [business.example.yaml] [eval/cases.yaml] [eval/results.json]
    python -m eval.run_eval restaurant          # a niche pack: its demo.yaml and cases.yaml
    python -m eval.run_eval all                 # every niche pack

Every case is a fresh conversation with a business loaded from the YAML profile. Profiles without
`slots` take bookings as requests; pack demos have slots generated from the current time.
Writes the results file used in the thesis and by the CI summary (eval/summary.py).
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
import time
from pathlib import Path

import yaml
from sqlmodel import select

from joop import db
from joop.agent.engine import ERROR_REPLY, handle_incoming
from joop.channels.base import IncomingMessage
from joop.lang import RU_MESSAGE_MARKERS, looks_kyrgyz


def looks_russian(text: str) -> bool:
    """Short neutral replies ("Манты — 300 сом") are fine in either language; a Russian sentence is not."""
    words = re.findall(r"[а-яё]+", text.lower())
    return sum(1 for w in words if w in RU_MESSAGE_MARKERS) >= 2
from joop.models import Business, Lead
from joop.presets import create_business
from joop.pricing import cost_usd, empty_usage
from joop.niches import all_packs
from joop.profile import apply_profile, load_profile


def check_case(case: dict, final_text: str, lead_saved: bool, handoff: bool, order_saved: bool = False) -> list[str]:
    """Return a list of failure reasons (empty = pass)."""
    fails = []
    low = final_text.lower()
    if final_text.strip() == ERROR_REPLY:
        fails.append("no answer: the bot sent the generic fallback")
    if "**" in final_text or re.search(r"(?m)^#{1,6} ", final_text):
        fails.append("markdown in reply (messengers show it as raw symbols)")
    if case.get("expect_lang") == "ky" and not looks_kyrgyz(final_text) and looks_russian(final_text):
        fails.append("reply is in Russian, not Kyrgyz")
    if "expect_lead" in case and bool(case["expect_lead"]) != lead_saved:
        fails.append(f"expect_lead={case['expect_lead']} got {lead_saved}")
    if "expect_order" in case and bool(case["expect_order"]) != order_saved:
        fails.append(f"expect_order={case['expect_order']} got {order_saved}")
    if "expect_handoff" in case and bool(case["expect_handoff"]) != handoff:
        fails.append(f"expect_handoff={case['expect_handoff']} got {handoff}")
    any_of = case.get("must_contain_any")
    if any_of and not any(s.lower() in low for s in any_of):
        fails.append(f"missing any of {any_of}")
    for s in case.get("must_not_contain", []):
        if s.lower() in low:
            fails.append(f"contains forbidden '{s}'")
    for pattern in case.get("must_not_match", []):  # regex, case-insensitive: forbids a claim, not a word
        if re.search(pattern, final_text, re.IGNORECASE):
            fails.append(f"matches forbidden /{pattern}/")
    return fails


def run_case(get_llm, profile: dict, case: dict, model: str, index: int) -> dict:
    """One case = one new business and one conversation.

    'lead' = a booking, a booking request or a qualified lead; 'order' = an order with checked lines.
    """
    with db.new_session() as s:
        business = create_business(
            s, slug=f"eval{index}", name=profile["name"], password="eval-only-password", niche=profile.get("niche", "other")
        )
        apply_profile(s, business, profile)
        s.commit()
        business_id = business.id

    lead = handoff = order = language_fixed = confirmation_fixed = False
    final = ""
    latencies: list[float] = []
    usage = empty_usage()
    for turn_no, turn in enumerate(case["turns"]):
        incoming = IncomingMessage("telegram", "eval", "text", turn, "eval", f"eval:{index}:{turn_no}")
        t0 = time.perf_counter()
        with db.new_session() as s:
            business = s.get(Business, business_id)
            out = handle_incoming(s, business, incoming, get_llm, base_url="https://joop.example")
            s.commit()
            if out.lead_id is not None:
                handoff = handoff or s.get(Lead, out.lead_id).kind == "handoff"
        latencies.append(time.perf_counter() - t0)
        lead = lead or any(x is not None for x in (out.booking_id, out.request_id, out.qualified_lead_id, out.stay_id))
        order = order or out.order_id is not None
        language_fixed = language_fixed or out.language_fixed
        confirmation_fixed = confirmation_fixed or out.confirmation_fixed
        final = out.reply or ""
        for k in usage:
            usage[k] += out.usage.get(k, 0)

    fails = check_case(case, final, lead, handoff, order)
    return {
        "id": case["id"],
        "passed": not fails,
        "fails": fails,
        "final_reply": final,
        "lead": lead,
        "handoff": handoff,
        "order": order,
        "avg_latency_s": round(sum(latencies) / len(latencies), 2),
        "usage": usage,
        "cost_usd": cost_usd(usage, model),
        "language_fixed": language_fixed,
        "confirmation_fixed": confirmation_fixed,
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
        "confirmation_guard_fired": sum(1 for r in results if r.get("confirmation_fixed")),
    }


def run(profile_path: str, cases_path: str, get_llm, model: str) -> dict:
    """Run every case in a throwaway database; returns the results document."""
    profile = load_profile(profile_path)
    cases = yaml.safe_load(Path(cases_path).read_text("utf-8"))
    with tempfile.TemporaryDirectory() as tmp:
        engine = db.make_engine(f"sqlite:///{Path(tmp) / 'eval.db'}")
        db.set_engine(engine)
        db.init_db()
        try:
            results = [run_case(get_llm, profile, case, model, i) for i, case in enumerate(cases)]
        finally:
            engine.dispose()
            db.set_engine(None)
    return {"model": model, "business_file": profile_path, "summary": summarize(results), "cases": results}


def main() -> None:
    from joop.config import get_settings
    from joop.runtime import Runtime

    settings = get_settings()
    if not settings.anthropic_api_key:
        sys.exit("ANTHROPIC_API_KEY is not set (environment or .env)")
    rt = Runtime(settings)
    arg = sys.argv[1] if len(sys.argv) > 1 else "business.example.yaml"
    if arg == "all" or arg in all_packs():
        names = [n for n, p in all_packs().items() if p.cases_file.exists()] if arg == "all" else [arg]
        for name in names:
            pack = all_packs()[name]
            report(run(str(pack.demo_file), str(pack.cases_file), rt.get_llm, settings.model), Path(f"eval/results_{name}.json"), settings.model)
        return
    profile_path = arg
    cases_path = sys.argv[2] if len(sys.argv) > 2 else "eval/cases.yaml"
    out = Path(sys.argv[3]) if len(sys.argv) > 3 else Path("eval/results.json")
    report(run(profile_path, cases_path, rt.get_llm, settings.model), out, settings.model)


def report(data: dict, out: Path, model: str) -> None:
    for r in data["cases"]:
        mark = "PASS" if r["passed"] else "FAIL"
        print(f"{mark} {r['id']:<34} {r['avg_latency_s']}s  {'; '.join(r['fails'])}")
    summary = data["summary"]
    print(f"\n{data['business_file']}: {summary['passed']}/{summary['cases']} passed, model {model}")
    print(f"Language guard rewrote replies in {summary['language_guard_fired']} case(s)")
    if summary["avg_cost_usd_per_conversation"] is not None:
        print(f"Average cost per conversation: ${summary['avg_cost_usd_per_conversation']:.6f}; "
              f"total ${summary['total_cost_usd']:.6f}")
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
    print(f"Saved to {out}")


if __name__ == "__main__":
    main()
