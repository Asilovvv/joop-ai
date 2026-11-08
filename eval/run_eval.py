"""Run a scripted evaluation set against the real model and print metrics.

Usage (needs ANTHROPIC_API_KEY in the environment or .env):
    python -m eval.run_eval [business.example.yaml] [eval/cases.yaml] [eval/results.json]
    python -m eval.run_eval restaurant          # a niche pack: its demo.yaml and cases.yaml
    python -m eval.run_eval all                 # every niche pack
    python -m eval.run_eval all --dry-run       # no model, no key: checks that every case runs end to end

A dry run answers every turn with one neutral scripted reply. It checks the plumbing (profiles, cases, prompt
building, metrics) and writes to eval/dryrun/; its numbers say nothing about the agent and are marked as such.

Every case is a fresh conversation with a business loaded from the YAML profile. Profiles without
`slots` take bookings as requests; pack demos have slots generated from the current time.
Writes the results file used in the thesis and by the CI summary (eval/summary.py).
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import tempfile
import time
from pathlib import Path

import yaml
from sqlmodel import select

from joop import db
from joop.agent.engine import ERROR_REPLY, handle_incoming
from joop.agent.llm import AgentReply
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


# Per-metric checks for the thesis table. Each case counts only towards the metrics its expectations cover.
METRICS = {
    "facts": "No invented facts",  # must_not_contain / must_not_match: a forbidden fact or claim is absent
    "answer": "Correct answer",  # must_contain_any: the expected fact is in the reply
    "action": "Action accuracy",  # expect_lead / expect_order: saved exactly when expected
    "handoff": "Hand-off accuracy",  # expect_handoff: handed to a person exactly when expected
    "kyrgyz": "Kyrgyz reply",  # expect_lang ky: the reply is not in Russian
}


def case_metrics(case: dict, final_text: str, lead_saved: bool, handoff: bool, order_saved: bool = False) -> dict[str, bool]:
    """{metric: passed} for the metrics this case covers; the same rules as check_case.

    No answer (the fallback after a failed model call, or nothing) fails every metric the case covers: the bilingual
    fallback names no forbidden fact and looks Kyrgyz, but it is not a pass."""
    low = final_text.lower()
    m: dict[str, bool] = {}
    no_answer = not final_text.strip() or final_text.strip() == ERROR_REPLY
    if case.get("must_not_contain") or case.get("must_not_match"):
        m["facts"] = not any(s.lower() in low for s in case.get("must_not_contain", [])) and not any(
            re.search(p, final_text, re.IGNORECASE) for p in case.get("must_not_match", [])
        )
    if case.get("must_contain_any"):
        m["answer"] = any(s.lower() in low for s in case["must_contain_any"])
    got = {"expect_lead": lead_saved, "expect_order": order_saved}
    if any(k in case for k in got):
        m["action"] = all(bool(case[k]) == v for k, v in got.items() if k in case)
    if "expect_handoff" in case:
        m["handoff"] = bool(case["expect_handoff"]) == handoff
    if case.get("expect_lang") == "ky":
        m["kyrgyz"] = looks_kyrgyz(final_text) or not looks_russian(final_text)
    return {k: False for k in m} if no_answer else m


class DryRunLLM:
    """No model: every turn gets one neutral reply, so a run checks the pipeline, not the agent."""

    model = "dry-run"
    REPLY = "Здравствуйте! Уточню у администратора и отвечу вам."
    REPLY_KY = "Саламатсызбы! Администратордон тактап, сизге жооп берем."

    def respond(self, system: str, messages: list[dict], schema: dict | None = None) -> AgentReply:
        return AgentReply(self.REPLY)

    def rewrite_in_kyrgyz(self, text: str, usage: dict) -> str | None:
        return self.REPLY_KY

    def remove_false_confirmation(self, text: str, usage: dict) -> str | None:
        return None

    def write(self, instruction: str, text: str, usage: dict) -> str | None:
        return None


def api_error(record: logging.LogRecord) -> str:
    """'LLMError: Claude API call failed: RateLimitError — <the API's message>' for a failed model call.
    Error messages from the API carry no key, so they are safe to store with the results."""
    if not record.exc_info:
        return record.getMessage()
    exc = record.exc_info[1]
    text = f"{type(exc).__name__}: {exc}"
    cause = getattr(exc, "__cause__", None)
    if cause is not None:
        text += f" — {type(cause).__name__}: {str(cause)[:300]}"
    return text


class _Collect(logging.Handler):
    """Collects warnings and errors logged during one case (failed model calls among them)."""

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.items: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        text = api_error(record)
        if text not in self.items:
            self.items.append(text)


def preflight(get_llm) -> str | None:
    """One tiny model call before a run: None if the model answers, else why not."""
    try:
        get_llm().respond("Reply with the JSON {\"reply\": \"ok\"}.", [{"role": "user", "content": "ping"}])
    except Exception as exc:  # report the reason and stop instead of filling a run with fallbacks
        cause = getattr(exc, "__cause__", None)
        return f"{type(exc).__name__}: {exc}" + (f" — {type(cause).__name__}: {str(cause)[:300]}" if cause else "")
    return None


def run_case(get_llm, profile: dict, case: dict, model: str, index: int) -> dict:
    """One case = one new business and one conversation.

    'lead' = a booking, a booking request or a qualified lead; 'order' = an order with checked lines.
    """
    with db.new_session() as s:
        business = create_business(
            s, slug=f"eval{index}", name=profile["name"], password="eval-only-password", niche=profile.get("niche", "other")
        )
        apply_profile(s, business, profile)
        business.example_ok = True  # the profile is this test business's real data, not the sign-up example (joop/samples.py)
        s.commit()
        business_id = business.id

    lead = handoff = order = language_fixed = confirmation_fixed = False
    final = ""
    latencies: list[float] = []
    usage = empty_usage()
    collect = _Collect()
    logging.getLogger("joop").addHandler(collect)
    try:
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
    finally:
        logging.getLogger("joop").removeHandler(collect)

    fails = check_case(case, final, lead, handoff, order)
    return {
        "id": case["id"],
        "turns": list(case["turns"]),  # for the native-speaker review sheet (eval/review_sheet.py)
        "lang": case.get("expect_lang", ""),
        "passed": not fails,
        "fails": fails,
        "metrics": case_metrics(case, final, lead, handoff, order),
        "fallback": final.strip() == ERROR_REPLY,
        **({"errors": collect.items[:3]} if collect.items else {}),
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
        "fallbacks": sum(1 for r in results if r.get("fallback")),
        "metrics": {
            k: {"cases": len(v), "passed": sum(v)}
            for k in METRICS
            if (v := [r["metrics"][k] for r in results if k in r.get("metrics", {})])
        },
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

    dry = "--dry-run" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--dry-run"]
    if dry:
        get_llm, model, out_dir = DryRunLLM, DryRunLLM.model, Path("eval/dryrun")
        out_dir.mkdir(parents=True, exist_ok=True)
    else:
        settings = get_settings()
        if not settings.anthropic_api_key:
            sys.exit("ANTHROPIC_API_KEY is not set (environment or .env); without a key use --dry-run")
        rt = Runtime(settings)
        problem = preflight(rt.get_llm)
        if problem:
            prefix = "::error::" if os.environ.get("GITHUB_ACTIONS") else ""  # an annotation readable through the API
            sys.exit(f"{prefix}The model {settings.model} does not answer, so the run is skipped: {problem}")
        get_llm, model, out_dir = rt.get_llm, settings.model, Path("eval")

    def go(profile_path: str, cases_path: str, out: Path) -> None:
        if dry and out.resolve().parent != out_dir.resolve():  # scripted replies must never replace real results
            sys.exit(f"A dry run writes only to {out_dir}/, not to {out}")
        data = run(profile_path, cases_path, get_llm, model)
        if dry:
            data["dry_run"] = True
        report(data, out, model)

    arg = args[0] if args else "business.example.yaml"
    if arg == "all" or arg in all_packs():
        names = [n for n, p in all_packs().items() if p.cases_file.exists()] if arg == "all" else [arg]
        if arg == "all" and dry:  # the two general sets too, so a dry run covers every case
            go("business.example.yaml", "eval/cases.yaml", out_dir / "results.json")
            go("business.dental.example.yaml", "eval/cases_dental.yaml", out_dir / "results_dental_profile.json")
        for name in names:
            pack = all_packs()[name]
            go(str(pack.demo_file), str(pack.cases_file), out_dir / f"results_{name}.json")
        return
    cases_path = args[1] if len(args) > 1 else "eval/cases.yaml"
    out = Path(args[2]) if len(args) > 2 else out_dir / "results.json"
    go(arg, cases_path, out)


def report(data: dict, out: Path, model: str) -> None:
    if data.get("dry_run"):
        print("DRY RUN: scripted replies, no model. The numbers below check the pipeline, not the agent.")
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
