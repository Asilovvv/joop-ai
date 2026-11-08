"""Native-speaker review of the Kyrgyz replies (thesis, Chapter 3, step 5).

    python -m eval.review_sheet make eval/results*.json [--sample N] [--out eval/kyrgyz_review.csv]
    python -m eval.review_sheet score eval/kyrgyz_review.csv [--latex]

`make` writes one row per Kyrgyz case (expect_lang: ky) of real runs: the customer's messages, the bot's
final reply and the automatic language check. The reviewer fills the last five columns. The file is
UTF-8 with a BOM and ";" between columns, so Excel with a Russian locale and Google Sheets open it as is.

`score` reads the filled file back (";" or "," — a re-saved file keeps working) and prints the review
metrics: mean correctness and naturalness (1-5) and how often the automatic check agrees with the reviewer.
Dry-run results are refused: their replies are scripted, not the agent's.
"""

from __future__ import annotations

import csv
import io
import json
import random
import sys
from pathlib import Path

from eval.summary import set_name

# Column headers are for the reviewer, so they are in Russian.
COLUMNS = [
    "id", "Набор", "Сообщения клиента", "Ответ бота", "Авто-проверка: кыргызский",
    "Ответ на кыргызском? (да/нет)", "Правильность 1-5", "Естественность 1-5", "Как сказать лучше", "Комментарий",
]
IS_KY, CORRECT, NATURAL = COLUMNS[5], COLUMNS[6], COLUMNS[7]
YES, NO = "да", "нет"


def review_rows(paths: list[str], sample: int | None = None, seed: int = 2026) -> list[list[str]]:
    rows: list[list[str]] = []
    for p in sorted(paths):
        path = Path(p)
        data = json.loads(path.read_text("utf-8"))
        if data.get("dry_run"):
            print(f"skipped {path.name}: a dry run has scripted replies, not the agent's", file=sys.stderr)
            continue
        name = set_name(data, path)
        for c in data.get("cases", []):
            if c.get("lang") != "ky" or "turns" not in c:
                continue
            auto = c.get("metrics", {}).get("kyrgyz")
            rows.append([
                c["id"], name, "\n".join(c["turns"]), c.get("final_reply", ""),
                "" if auto is None else (YES if auto else NO), "", "", "", "", "",
            ])
    if sample is not None and sample < len(rows):
        keep = sorted(random.Random(seed).sample(range(len(rows)), sample))  # fixed seed: the same sample every time
        rows = [rows[i] for i in keep]
    return rows


def write_sheet(rows: list[list[str]], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(COLUMNS)
        w.writerows(rows)


def read_sheet(path: Path) -> list[dict[str, str]]:
    text = path.read_text("utf-8-sig")
    first = text.split("\n", 1)[0]
    delimiter = ";" if first.count(";") >= first.count(",") else ","
    return list(csv.DictReader(io.StringIO(text), delimiter=delimiter))


def _yes_no(value: str) -> bool | None:
    v = value.strip().lower()
    if v in {"да", "yes", "ооба", "1", "+"}:
        return True
    if v in {"нет", "no", "жок", "0", "-"}:
        return False
    return None


def _grade(value: str) -> int | None:
    v = value.strip()
    return int(v) if v in {"1", "2", "3", "4", "5"} else None


def score(rows: list[dict[str, str]]) -> dict:
    """Review metrics over the rows the reviewer filled in; a row counts if it has any answer."""
    rated = [r for r in rows if any((r.get(k) or "").strip() for k in (IS_KY, CORRECT, NATURAL))]
    human = [(r, _yes_no(r.get(IS_KY) or "")) for r in rated]
    correct = [g for r in rated if (g := _grade(r.get(CORRECT) or "")) is not None]
    natural = [g for r in rated if (g := _grade(r.get(NATURAL) or "")) is not None]
    pairs = [(_yes_no(r.get(COLUMNS[4]) or ""), h) for r, h in human]
    pairs = [(a, h) for a, h in pairs if a is not None and h is not None]
    return {
        "rows": len(rows),
        "rated": len(rated),
        "kyrgyz_by_reviewer": sum(1 for _, h in human if h),
        "kyrgyz_answered": sum(1 for _, h in human if h is not None),
        "correct_mean": round(sum(correct) / len(correct), 2) if correct else None,
        "correct_good": sum(1 for g in correct if g >= 4),
        "correct_n": len(correct),
        "natural_mean": round(sum(natural) / len(natural), 2) if natural else None,
        "natural_good": sum(1 for g in natural if g >= 4),
        "natural_n": len(natural),
        "agree": sum(1 for a, h in pairs if a == h),
        "compared": len(pairs),
        # the automatic check passed a reply the reviewer says is not Kyrgyz: the costly kind of miss
        "auto_false_pass": [r["id"] for r, h in human if h is False and _yes_no(r.get(COLUMNS[4]) or "") is True],
        "auto_false_fail": [r["id"] for r, h in human if h is True and _yes_no(r.get(COLUMNS[4]) or "") is False],
    }


def _pct(k: int, n: int) -> str:
    return f"{k}/{n} ({100 * k / n:.1f}%)" if n else "—"


def render(s: dict, latex: bool = False) -> str:
    items = [
        ("Replies rated", f"{s['rated']} of {s['rows']}"),
        ("Reply is in Kyrgyz (reviewer)", _pct(s["kyrgyz_by_reviewer"], s["kyrgyz_answered"])),
        ("Correctness, mean of 1-5", str(s["correct_mean"]) if s["correct_mean"] is not None else "—"),
        ("Correctness 4 or 5", _pct(s["correct_good"], s["correct_n"])),
        ("Naturalness, mean of 1-5", str(s["natural_mean"]) if s["natural_mean"] is not None else "—"),
        ("Naturalness 4 or 5", _pct(s["natural_good"], s["natural_n"])),
        ("Automatic check agrees with reviewer", _pct(s["agree"], s["compared"])),
        ("Automatic check passed a non-Kyrgyz reply", str(len(s["auto_false_pass"]))),
        ("Automatic check failed a Kyrgyz reply", str(len(s["auto_false_fail"]))),
    ]
    if latex:
        body = [f"{k} & {v.replace('%', chr(92) + '%').replace('—', '---')} \\\\" for k, v in items]
        return "\n".join(["\\begin{tabular}{|l|r|}", "\\hline", "\\textbf{Measure} & \\textbf{Value} \\\\", "\\hline",
                          *body, "\\hline", "\\end{tabular}"]) + "\n"
    out = ["| Measure | Value |", "| --- | --- |", *[f"| {k} | {v} |" for k, v in items]]
    for label, ids in (("passed a non-Kyrgyz reply", s["auto_false_pass"]), ("failed a Kyrgyz reply", s["auto_false_fail"])):
        if ids:
            out.append(f"\nAutomatic check {label}: " + ", ".join(f"`{i}`" for i in ids))
    return "\n".join(out) + "\n"


def main(argv: list[str]) -> None:
    if not argv or argv[0] not in {"make", "score"}:
        sys.exit(__doc__)
    cmd, rest = argv[0], argv[1:]

    def option(name: str) -> str | None:
        if name in rest:
            i = rest.index(name)
            value = rest[i + 1]
            del rest[i:i + 2]
            return value
        return None

    if cmd == "make":
        out = Path(option("--out") or "eval/kyrgyz_review.csv")
        sample = option("--sample")
        rows = review_rows(rest, int(sample) if sample else None)
        if not rows:
            sys.exit("No Kyrgyz cases with replies: run the evaluation with the model first (dry runs are skipped).")
        write_sheet(rows, out)
        print(f"{len(rows)} replies to review saved to {out}")
    else:
        latex = "--latex" in rest
        files = [a for a in rest if a != "--latex"]
        print(render(score(read_sheet(Path(files[0]))), latex), end="")


if __name__ == "__main__":
    main(sys.argv[1:])
