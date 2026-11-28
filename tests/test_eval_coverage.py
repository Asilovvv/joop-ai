"""eval/coverage.py: which of today's dialogues the real model has ever answered, and stored runs by language.

The numbers a README or a slide quotes come from this tool. On 28 November 2026 a count by hand said 269 dialogues
had never run: it took the October results of the base dental set (stored as …_results_dental.json before the dental
pack existed) for the pack's, and the right number was 255.
"""

import json
from pathlib import Path

import pytest
import yaml

from eval import coverage
from joop.agent.engine import ERROR_REPLY


def case(case_id, passed=True, reply="Чистка стоит 2500 сом.", **more):
    return {"id": case_id, "passed": passed, "final_reply": reply, "avg_latency_s": 1.0, **more}


@pytest.fixture
def root(tmp_path) -> Path:
    """A small product: two packs, the base set and the base dental set."""
    sets = {
        "joop/niches/dental/cases.yaml": [{"id": "price"}, {"id": "price_ky", "expect_lang": "ky"}, {"id": "new_case"}],
        "joop/niches/water/cases.yaml": [{"id": "order"}, {"id": "order_ky", "expect_lang": "ky"}],
        "eval/cases.yaml": {"cases": [{"id": "hello"}, {"id": "hello_ky", "expect_lang": "ky"}]},
        "eval/cases_dental.yaml": [{"id": "old_price"}, {"id": "old_price_ky", "expect_lang": "ky"}],
    }
    for name, cases in sets.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(cases, allow_unicode=True), encoding="utf-8")
    return tmp_path


def store(folder: Path, name: str, cases: list[dict], **more) -> None:
    folder.mkdir(exist_ok=True)
    data = {"model": "claude-haiku-5-5", "summary": {"total_cost_usd": 0.01 * len(cases)}, "cases": cases, **more}
    (folder / name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_todays_dialogues_are_read_with_their_language(root):
    today = coverage.dialogues(root)
    assert len(today) == 9 and today[("dental", "price_ky")] == "ky" and today[("base", "hello")] == ""
    assert {name for name, _id in today} == {"dental", "water", "base", "dental_base"}
    (root / "joop/niches/water/cases.yaml").write_text(yaml.safe_dump([{"id": "order"}, {"id": "order"}]), encoding="utf-8")
    with pytest.raises(ValueError, match="used twice"):
        coverage.dialogues(root)


def test_a_dialogue_has_run_when_the_model_itself_answered_it(root, tmp_path):
    runs = tmp_path / "runs"
    store(runs, "2026-10-29T0919Z_run2_results.json", [case("hello"), case("hello_ky", passed=False)])  # a failed check is still an answer
    # before the dental pack existed this name held the base dental set
    store(runs, "2026-10-29T0919Z_run2_results_dental.json", [case("old_price"), case("old_price_ky")])
    store(runs, "2026-10-31T1032Z_run33_results_dental.json", [case("price"), case("price_ky"), case("removed_since")])
    store(runs, "2026-10-31T1303Z_run35_results_water_r1.json", [case("order", reply=ERROR_REPLY)])  # the fallback is not an answer
    store(runs, "2026-10-31T1310Z_run36_results_water.json", [case("order", reply="Сейчас не могу", fallback=True)])  # nor one marked so
    store(runs, "2026-10-31T1303Z_run35_results_water_r2.json", [case("order_ky", reply="")])
    store(runs, "2026-11-20T0900Z_run41_results_water.json", [case("order"), case("order_ky")], dry_run=True)  # scripted replies
    store(runs, "2026-10-30T0400Z_run20_results_kyfill.json", [case("order")])  # another tool's file
    (runs / "notes.json").write_text("[]", encoding="utf-8")

    found = coverage.coverage(coverage.dialogues(root), coverage.read_runs(runs))
    assert found.ran == {("base", "hello"), ("base", "hello_ky"), ("dental_base", "old_price"), ("dental_base", "old_price_ky"),
                         ("dental", "price"), ("dental", "price_ky")}
    assert found.never == {("dental", "new_case"), ("water", "order"), ("water", "order_ky")}
    assert found.kyrgyz(found.ran) == 3 and found.kyrgyz(found.never) == 1
    text = coverage.render_coverage(found)
    assert "Today: 9 dialogues in 4 sets, 4 of them in Kyrgyz." in text
    assert "Answered by the real model at least once: 6 (3 in Kyrgyz)." in text
    assert "Never run on the real model: 3 (1 in Kyrgyz)." in text and "Never run, by set: dental 1, water 2." in text


def test_the_base_dental_set_under_its_later_name(root, tmp_path):
    runs = tmp_path / "runs"
    store(runs, "2026-10-31T1500Z_run39_results_dental_profile.json", [case("old_price"), case("price")])
    found = coverage.coverage(coverage.dialogues(root), coverage.read_runs(runs))
    assert found.ran == {("dental_base", "old_price")}  # «price» is the pack's id: this file is not the pack's


def test_runs_are_split_by_todays_language(root, tmp_path):
    runs = tmp_path / "runs"
    store(runs, "2026-10-31T1019Z_run32_results_dental.json", [case("price"), case("price_ky", passed=False, language_fixed=True)])
    store(runs, "2026-10-31T1032Z_run33_results.json", [case("hello", confirmation_fixed=True), case("hello_ky")])
    store(runs, "2026-10-31T1032Z_run33_results_dental.json",
          [case("price", avg_latency_s=3.0), case("price_ky"), case("removed_since", passed=False)])
    store(runs, "2026-10-31T1303Z_run35_results_water.json", [case("order")])
    today, results = coverage.dialogues(root), coverage.read_runs(runs)

    rows = coverage.run_rows(today, results, coverage.runs_wanted("32-33"))
    assert [row.label for row in rows] == ["32", "33", "32–33"]
    first, second, both = rows
    assert (first.kyrgyz, first.other, first.language_fixed, first.day) == ([0, 1], [1, 1], 1, "2026-10-31")
    assert (second.kyrgyz, second.other, second.gone, second.confirmation_fixed) == ([2, 2], [2, 2], [0, 1], 1)
    assert second.all == [4, 5] and round(second.cost, 2) == 0.05 and second.seconds == [1.0, 1.0, 3.0, 1.0, 1.0]
    assert (both.kyrgyz, both.other, both.all) == ([2, 3], [3, 3], [5, 7])
    table = coverage.render_runs(rows)
    assert "| 33 | 2026-10-31 | 4/5 (80.0%) | 2/2 (100.0%) | 2/2 (100.0%); 1 gone | 1 | 0 | 0.050 | 1.40 |" in table
    assert "| 32–33 |  | 5/7 (71.4%) | 2/3 (66.7%) | 3/3 (100.0%); 1 gone | 1 | 1 | 0.070 | 1.29 |" in table

    assert [row.label for row in coverage.run_rows(today, results, coverage.runs_wanted("33"))] == ["33"]  # one run: no total
    assert [row.label for row in coverage.run_rows(today, results, coverage.runs_wanted("32,35"))] == ["32", "35", "together"]
    assert coverage.run_rows(today, results, coverage.runs_wanted("40")) == []
    assert coverage.runs_wanted("30-33, 35") == {30, 31, 32, 33, 35}


def test_the_command_prints_both_and_fails_on_an_empty_folder(root, tmp_path, capsys, monkeypatch):
    runs = tmp_path / "runs"
    runs.mkdir()
    assert coverage.main([str(runs)]) == 1 and "No result files" in capsys.readouterr().err
    store(runs, "2026-10-31T1032Z_run33_results.json", [case("hello"), case("hello_ky")])
    monkeypatch.setattr(coverage, "ROOT", root)
    monkeypatch.setattr(coverage.dialogues, "__defaults__", (root,))
    assert coverage.main([str(runs), "--runs", "33"]) == 0
    printed = capsys.readouterr().out
    assert "Answered by the real model at least once: 2 (1 in Kyrgyz)." in printed and "| 33 | 2026-10-31 | 2/2 (100.0%)" in printed


def test_the_products_own_dialogues_have_one_id_each():
    today = coverage.dialogues()  # raises when a set uses an id twice: such a dialogue could not be told apart in results
    packs = {path.parent.name for path in (coverage.ROOT / "joop" / "niches").glob("*/cases.yaml")}
    assert {name for name, _id in today} == packs | {"base", "dental_base"}
    assert all(lang in ("", "ky") for lang in today.values()) and sum(1 for lang in today.values() if lang == "ky") > 100


def test_a_repeat_of_the_base_set(root, tmp_path):
    """Review of #321–#327: …_results_r2.json was read as a set named "r2" and left out."""
    runs = tmp_path / "runs"
    store(runs, "2026-10-31T1303Z_run35_results_r2.json", [case("hello")])
    store(runs, "2026-10-31T1303Z_run35_results_water_r2.json", [case("order")])
    found = coverage.coverage(coverage.dialogues(root), coverage.read_runs(runs))
    assert found.ran == {("base", "hello"), ("water", "order")}


def test_the_file_says_which_dental_set_it_holds(root, tmp_path):
    """Review of #321–#327: with an id in both dental sets, a result of the base dental set was the pack's."""
    for name in ("joop/niches/dental/cases.yaml", "eval/cases_dental.yaml"):
        path = root / name
        path.write_text(yaml.safe_dump(yaml.safe_load(path.read_text(encoding="utf-8")) + [{"id": "shared"}]), encoding="utf-8")
    runs = tmp_path / "runs"
    store(runs, "2026-10-29T0919Z_run2_results_dental.json", [case("shared")], business_file="business.dental.example.yaml")
    found = coverage.coverage(coverage.dialogues(root), coverage.read_runs(runs))
    assert found.ran == {("dental_base", "shared")}
    store(runs, "2026-10-31T1032Z_run33_results_dental.json", [case("shared")],
          business_file="/home/runner/work/joop-ai/joop-ai/joop/niches/dental/demo.yaml")
    found = coverage.coverage(coverage.dialogues(root), coverage.read_runs(runs))
    assert found.ran == {("dental_base", "shared"), ("dental", "shared")}


def test_another_tools_files_are_not_runs(root, tmp_path):
    """Review of #321–#327: the Kyrgyz-phrase tool's files entered the rows as dialogues that no longer exist."""
    runs = tmp_path / "runs"
    store(runs, "2026-11-01T0400Z_run37_results_kyfill.json", [case("auto:0"), case("auto:1")], business_file="kyrgyz_fill")
    store(runs, "2026-11-01T0400Z_run37_results_water.json", [case("order")])
    rows = coverage.run_rows(coverage.dialogues(root), coverage.read_runs(runs), coverage.runs_wanted("37"))
    assert len(rows) == 1 and rows[0].all == [1, 1] and rows[0].gone == [0, 0] and round(rows[0].cost, 2) == 0.01

