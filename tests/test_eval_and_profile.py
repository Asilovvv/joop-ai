import json
from pathlib import Path

from sqlmodel import select

from eval.run_eval import check_case, run, summarize
from eval.summary import render
from joop import db
from joop.agent.engine import ERROR_REPLY
from joop.agent.llm import AgentReply
from joop.models import Business, Faq, Service
from joop.profile import apply_profile, load_profile

from .conftest import FakeLLM

ROOT = Path(__file__).resolve().parent.parent
DENTAL = str(ROOT / "business.dental.example.yaml")


def test_profile_import(business):
    data = load_profile(DENTAL)
    with db.new_session() as s:
        b = s.get(Business, business.id)
        apply_profile(s, b, data)
        s.commit()
        services = s.exec(select(Service).where(Service.business_id == b.id).order_by(Service.sort)).all()
        assert services[0].name == "Консультация стоматолога" and services[0].name_ky == "Стоматологдун консультациясы"
        assert "длительность 20-30 минут" in services[0].note
        assert len(s.exec(select(Faq).where(Faq.business_id == b.id)).all()) == 4
        assert b.niche == "dental" and "103" in b.extra_rules and "перезванивает" in b.booking_policy


def test_check_case():
    assert check_case({"must_contain_any": ["500"]}, "Консультация стоит 500 сом.", False, False) == []
    fails = check_case(
        {"expect_lang": "ky", "expect_lead": True, "must_not_contain": ["принята"]},
        "**Заявка принята, ждём вас завтра в клинике**", False, False,
    )
    assert len(fails) == 4  # markdown, Russian, no lead, forbidden word
    assert check_case({}, ERROR_REPLY, False, False) == ["no answer: the bot sent the generic fallback"]


def test_eval_pipeline_with_scripted_model(tmp_path):
    cases = [
        {"id": "price", "turns": ["Сколько стоит консультация?"], "must_contain_any": ["500"]},
        {"id": "booking", "turns": ["Хочу на чистку", "Азамат, +996 700 123 456, в субботу в 11:00"], "expect_lead": True},
        {"id": "urgent", "turns": ["Опухла щека, температура 38"], "expect_handoff": True},
    ]
    cases_file = tmp_path / "cases.yaml"
    cases_file.write_text(json.dumps(cases, ensure_ascii=False), "utf-8")  # JSON is valid YAML
    llm = FakeLLM([
        AgentReply("Консультация стоит 500 сом."),
        AgentReply("Как вас зовут и ваш телефон?"),
        AgentReply("Спасибо! Администратор перезвонит и подтвердит время.",
                   booking={"slot_id": None, "name": "Азамат", "phone": "+996 700 123 456", "service": "чистка", "preferred_time": "суббота 11:00"}),
        AgentReply("Срочно позвоните в клинику, при угрозе жизни — 103.", handoff="Отёк и температура"),
    ])
    data = run(DENTAL, str(cases_file), lambda: llm, "claude-haiku-5-5")
    assert data["summary"]["passed"] == 3, data["cases"]
    assert data["cases"][1]["lead"] and data["cases"][2]["handoff"]
    # the profile reached the prompt: Kyrgyz names and medical rules
    assert "Тишти кесипкөй тазалоо" in llm.calls[0]["system"] and "103" in llm.calls[0]["system"]
    out = tmp_path / "results.json"
    out.write_text(json.dumps(data, ensure_ascii=False), "utf-8")
    table = render([str(out)])
    assert "| business.dental.example.yaml | 3/3 |" in table


def test_summarize():
    results = [
        {"passed": True, "avg_latency_s": 1.0, "usage": {"input_tokens": 10, "output_tokens": 2}, "cost_usd": 0.001},
        {"passed": False, "avg_latency_s": 3.0, "usage": {"input_tokens": 20, "output_tokens": 4}, "cost_usd": 0.003},
    ]
    s = summarize(results)
    assert s["passed"] == 1 and s["avg_latency_s"] == 2.0 and s["max_latency_s"] == 3.0
    assert s["input_tokens"] == 30 and s["avg_cost_usd_per_conversation"] == 0.002


def test_failed_model_calls_are_recorded_and_preflight_stops_a_dead_run(tmp_path):
    import json

    from eval.run_eval import preflight
    from joop.agent.llm import LLMError

    from .conftest import FakeLLM

    class CreditError(Exception):
        pass

    def broken():
        try:
            raise CreditError("Your credit balance is too low")
        except CreditError as exc:
            raise LLMError("Claude API call failed: CreditError") from exc

    cases_file = tmp_path / "cases.yaml"
    cases_file.write_text(json.dumps([{"id": "price", "turns": ["Сколько стоит чистка?"]}], ensure_ascii=False), "utf-8")
    llm = FakeLLM([lambda system, messages: broken()])
    data = run(DENTAL, str(cases_file), lambda: llm, "claude-haiku-5-5")
    case = data["cases"][0]
    assert not case["passed"] and "credit balance is too low" in case["errors"][0]
    assert "credit balance is too low" in render_results(data)

    dead = FakeLLM([lambda system, messages: broken()])
    assert "credit balance is too low" in preflight(lambda: dead)
    assert preflight(lambda: FakeLLM()) is None


def render_results(data) -> str:
    import json
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "results.json"
        p.write_text(json.dumps(data, ensure_ascii=False), "utf-8")
        return render([str(p)])


def test_case_metrics_follow_the_same_rules_as_check_case():
    from eval.run_eval import case_metrics

    case = {
        "must_not_contain": ["бесплатно"], "must_contain_any": ["500"], "expect_lead": True,
        "expect_handoff": False, "expect_lang": "ky",
    }
    assert case_metrics(case, "Консультация 500 сом.", True, False) == {
        "facts": True, "answer": True, "action": True, "handoff": True, "kyrgyz": True,
    }
    bad = case_metrics(case, "Консультация бесплатно, это совсем не дорого и мы вас ждём", False, True)
    assert bad == {"facts": False, "answer": False, "action": False, "handoff": False, "kyrgyz": False}
    assert len(check_case(case, "Консультация бесплатно, это совсем не дорого и мы вас ждём", False, True)) == 5
    # a case counts only towards the metrics it checks; orders and leads both decide action accuracy
    assert case_metrics({"expect_order": True}, "Готово", False, False, order_saved=True) == {"action": True}
    assert case_metrics({"expect_order": True, "expect_lead": False}, "Готово", True, False, order_saved=True) == {"action": False}
    assert case_metrics({"must_not_match": [r"запис\w* на \d"]}, "Записала на 15:00", False, False) == {"facts": False}
    assert case_metrics({}, "Здравствуйте", False, False) == {}


def test_summarize_counts_each_metric_over_the_cases_that_check_it():
    base = {"avg_latency_s": 1.0, "usage": {}, "cost_usd": None}
    results = [
        {**base, "passed": True, "metrics": {"facts": True, "kyrgyz": True}},
        {**base, "passed": False, "metrics": {"facts": False}, "fallback": True},
        {**base, "passed": True},  # results written before per-metric checks existed
    ]
    s = summarize(results)
    assert s["metrics"] == {"facts": {"cases": 2, "passed": 1}, "kyrgyz": {"cases": 1, "passed": 1}}
    assert s["fallbacks"] == 1 and s["avg_cost_usd_per_conversation"] is None


def test_dry_run_needs_no_key_and_marks_its_results(tmp_path, monkeypatch):
    import sys

    from eval import run_eval

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(sys, "argv", ["run_eval", "restaurant", "--dry-run"])
    run_eval.main()
    out = tmp_path / "eval" / "dryrun" / "results_restaurant.json"
    data = json.loads(out.read_text("utf-8"))
    cases = yaml_cases(ROOT / "joop" / "niches" / "restaurant" / "cases.yaml")
    assert data["dry_run"] is True and data["model"] == "dry-run"
    assert [c["id"] for c in data["cases"]] == [c["id"] for c in cases]  # every case ran
    assert all(not c.get("errors") for c in data["cases"]), [c.get("errors") for c in data["cases"]]
    assert not (tmp_path / "eval" / "results_restaurant.json").exists()  # real results are never overwritten


def yaml_cases(path):
    import yaml

    return yaml.safe_load(Path(path).read_text("utf-8"))


def test_thesis_table_marks_dry_runs_and_totals_the_sets(tmp_path):
    from eval.summary import thesis_latex, thesis_markdown

    def write(name, business_file, metrics, cost, dry=False):
        cases = 4
        doc = {"business_file": business_file, "summary": {
            "cases": cases, "passed": 3, "metrics": metrics, "avg_cost_usd_per_conversation": cost,
            "total_cost_usd": cost * cases if cost is not None else None,
        }, "cases": []}
        if dry:
            doc["dry_run"] = True
        path = tmp_path / name
        path.write_text(json.dumps(doc), "utf-8")
        return str(path)

    a = write("results_hotel.json", "/x/joop/niches/hotel/demo.yaml",
              {"facts": {"cases": 4, "passed": 3}, "kyrgyz": {"cases": 2, "passed": 2}}, 0.002)
    b = write("results.json", "business.example.yaml", {"facts": {"cases": 2, "passed": 2}}, 0.004)
    table = thesis_markdown([a, b])
    assert "DRY RUN" not in table
    assert "| hotel | 4 | 3/4 (75.0%) | 1/4 (25.0%) |" in table  # invented facts = the cases that failed
    assert "| business.example | 4 | 3/4 (75.0%) | 0/2 (0.0%) | — |" in table
    assert "| Total | 8 | 6/8 (75.0%) | 1/6 (16.7%) | — | — | — | 2/2 (100.0%) | 0 | 0.0030 |" in table

    d = write("results_spa.json", "/x/joop/niches/spa/demo.yaml", {}, None, dry=True)
    assert "DRY RUN" in thesis_markdown([a, d])
    tex = thesis_latex([write("results_dental_profile.json", "business.dental.example.yaml", {}, None, dry=True)])
    assert tex.startswith("% DRY RUN") and "business.dental.example & 4 & 3/4 (75.0\\%) & --- &" in tex
    assert "\\begin{tabular}" in tex and "\\textbf{Total}" in tex
    assert "\\multicolumn{10}{|l|}{\\textbf{DRY RUN" in tex  # visible in the PDF, not only a comment


def test_thesis_table_skips_files_without_metrics_and_labels_repeats(tmp_path):
    from eval.summary import thesis_markdown

    old = tmp_path / "results_kyfill.json"
    old.write_text(json.dumps({"business_file": "kyrgyz_fill (one call per pack)", "summary": {"cases": 3, "passed": 3}}), "utf-8")
    rep = tmp_path / "results_hotel_r2.json"
    rep.write_text(json.dumps({"business_file": "/x/joop/niches/hotel/demo.yaml", "summary": {
        "cases": 2, "passed": 2, "metrics": {}}, "cases": []}), "utf-8")
    table = thesis_markdown([str(old), str(rep)])
    assert "kyrgyz_fill" not in table and "| hotel (run 2) | 2 | 2/2 (100.0%) |" in table


def test_no_answer_fails_every_metric_the_case_checks():
    """The bilingual fallback names no forbidden fact and looks Kyrgyz; a failed model call must still not count as a pass."""
    from eval.run_eval import case_metrics

    case = {"must_not_contain": ["бесплатно"], "expect_handoff": False, "expect_lang": "ky"}
    assert case_metrics(case, ERROR_REPLY, False, False) == {"facts": False, "handoff": False, "kyrgyz": False}
    assert case_metrics(case, "  ", False, False) == {"facts": False, "handoff": False, "kyrgyz": False}


def test_dry_run_refuses_to_write_over_real_results(tmp_path, monkeypatch):
    import sys

    import pytest

    from eval import run_eval

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["run_eval", DENTAL, str(ROOT / "eval" / "cases_dental.yaml"), "eval/results.json", "--dry-run"])
    with pytest.raises(SystemExit, match="dry run writes only to eval/dryrun"):
        run_eval.main()
    assert not (tmp_path / "eval" / "results.json").exists()
