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
    assert check_case({"expect_lang": "en"}, "A consultation costs 500 som (Консультация).", False, False) == []
    assert check_case({"expect_lang": "en"}, "Консультация стоит 500 сом.", False, False) == ["reply is not in English"]
    assert check_case({"expect_lang": "zh"}, "咨询费用为500索姆。", False, False) == []
    assert check_case({"expect_lang": "zh"}, "Consultation is 500 som.", False, False) == ["reply is not in Chinese"]


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
