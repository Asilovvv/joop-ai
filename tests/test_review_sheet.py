import json

import pytest

from eval import review_sheet
from eval.review_sheet import COLUMNS, read_sheet, render, review_rows, score, write_sheet


def results(tmp_path, name="results_hotel.json", dry=False):
    doc = {"business_file": "/x/joop/niches/hotel/demo.yaml", "summary": {}, "cases": [
        {"id": "ky_price", "lang": "ky", "turns": ["Бөлмө канча турат?", "Эртеңге"], "final_reply": "Бөлмө 3000 сом.",
         "metrics": {"kyrgyz": True}},
        {"id": "ru_price", "lang": "", "turns": ["Сколько стоит номер?"], "final_reply": "3000 сом."},
        {"id": "ky_book", "lang": "ky", "turns": ["Жазылгым келет"], "final_reply": "Как вас зовут?",
         "metrics": {"kyrgyz": False}},
        {"id": "ky_old", "lang": "ky", "final_reply": "written before turns were kept"},
    ]}
    if dry:
        doc["dry_run"] = True
    path = tmp_path / name
    path.write_text(json.dumps(doc, ensure_ascii=False), "utf-8")
    return str(path)


def test_sheet_has_only_kyrgyz_cases_of_real_runs_and_opens_in_excel(tmp_path, capsys):
    rows = review_rows([results(tmp_path), results(tmp_path, "results_spa.json", dry=True)])
    assert [r[0] for r in rows] == ["ky_price", "ky_book"]  # Russian, dry-run and old cases are left out
    assert rows[0][1] == "hotel" and rows[0][2] == "Бөлмө канча турат?\nЭртеңге" and rows[0][4] == "да"
    assert rows[1][4] == "нет" and rows[1][5:] == [""] * 5
    assert "dry run" in capsys.readouterr().err

    out = tmp_path / "review.csv"
    write_sheet(rows, out)
    raw = out.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf") and raw.decode("utf-8-sig").split("\n", 1)[0].count(";") == len(COLUMNS) - 1
    back = read_sheet(out)
    assert back[0]["Сообщения клиента"] == "Бөлмө канча турат?\nЭртеңге"  # multi-line cells survive


def test_sample_is_fixed_and_keeps_the_order(tmp_path):
    many = {"business_file": "business.example.yaml", "summary": {}, "cases": [
        {"id": f"ky{i:02}", "lang": "ky", "turns": ["Салам"], "final_reply": "Саламатсызбы"} for i in range(30)
    ]}
    p = tmp_path / "results.json"
    p.write_text(json.dumps(many, ensure_ascii=False), "utf-8")
    a = [r[0] for r in review_rows([str(p)], sample=10)]
    assert len(a) == 10 and a == sorted(a) and a == [r[0] for r in review_rows([str(p)], sample=10)]


def test_score_reads_a_filled_sheet_resaved_with_commas(tmp_path):
    header = ",".join(COLUMNS)
    lines = [
        header,
        'a,hotel,"Салам",Саламатсызбы,да,да,5,4,,',
        'b,hotel,"Канча?","Сколько вам нужно?",да,нет,2,1,Канча керек?,по-русски',
        'c,hotel,"Качан?","Эртең",нет,да,4,5,,',
        'd,hotel,"Салам","Салам",да,,,,,',  # not rated yet
    ]
    path = tmp_path / "filled.csv"
    path.write_text("\n".join(lines) + "\n", "utf-8")
    s = score(read_sheet(path))
    assert s["rows"] == 4 and s["rated"] == 3
    assert s["kyrgyz_by_reviewer"] == 2 and s["kyrgyz_answered"] == 3
    assert s["correct_mean"] == pytest.approx(3.67) and s["correct_good"] == 2 and s["natural_mean"] == pytest.approx(3.33)
    assert s["agree"] == 1 and s["compared"] == 3
    assert s["auto_false_pass"] == ["b"] and s["auto_false_fail"] == ["c"]
    md = render(s)
    assert "| Automatic check agrees with reviewer | 1/3 (33.3%) |" in md and "`b`" in md
    tex = render(s, latex=True)
    assert "1/3 (33.3\\%)" in tex and tex.startswith("\\begin{tabular}")


def test_make_refuses_when_there_is_nothing_to_review(tmp_path):
    with pytest.raises(SystemExit, match="dry runs are skipped"):
        review_sheet.main(["make", results(tmp_path, dry=True), "--out", str(tmp_path / "x.csv")])
    review_sheet.main(["make", results(tmp_path), "--out", str(tmp_path / "ok.csv")])
    assert len(read_sheet(tmp_path / "ok.csv")) == 2


def test_texts_that_look_like_formulas_stay_text_and_score_needs_a_file(tmp_path):
    doc = {"business_file": "business.example.yaml", "summary": {}, "cases": [
        {"id": "ky1", "lang": "ky", "turns": ["+996 555 123 456"], "final_reply": "- Чистка — 2 500 сом"}]}
    p = tmp_path / "results.json"
    p.write_text(json.dumps(doc, ensure_ascii=False), "utf-8")
    row = review_rows([str(p)])[0]
    assert row[2] == "'+996 555 123 456" and row[3] == "'- Чистка — 2 500 сом"  # Excel shows them, does not run them
    with pytest.raises(SystemExit, match="Which file"):
        review_sheet.main(["score"])
    with pytest.raises(SystemExit, match="needs a value"):
        review_sheet.main(["make", str(p), "--sample"])
