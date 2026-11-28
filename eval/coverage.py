"""Which of today's scripted dialogues the real model has ever answered, and how stored runs went by language.

    git fetch origin eval-results
    git worktree add ../eval-results origin/eval-results         # the result files live on that branch, under runs/
    python -m eval.coverage ../eval-results/runs                 # today's dialogues: answered at least once, never run
    python -m eval.coverage ../eval-results/runs --runs 30-35    # and these runs: passed by language, guards, cost

The numbers a README or a slide quotes come from here, so that nobody counts them by hand: on 28 November 2026 a
count by hand said 269 dialogues had never run; it had missed that the base dental set ran in October under an older
file name, and the right number was 255.

A dialogue is a set and an id. The sets are every niche pack (joop/niches/<pack>/cases.yaml), "base" (eval/cases.yaml)
and "dental_base" (eval/cases_dental.yaml). A result file's name says its run and its set: …_run33_results_auto.json is
the auto pack, …_results.json the base set, …_results_dental_profile.json the base dental set; …_r2.json is a repeat
(…_results_r2.json: of the base set). Before the dental pack existed, …_results_dental.json held the base dental set:
the file's `business_file` says which of the two it holds (the pack's demo.yaml or business.dental.example.yaml).
A file of a set that does not exist today (…_results_kyfill.json: another tool's) is left out.

A dialogue has run when a result file of a real run (not a dry run) holds a case of its set with its id and an answer
that is not the fallback reply. A dialogue edited since still counts: a result keeps the answer, not the question. Its
language is today's `expect_lang`; a case of an old run whose dialogue no longer exists is "gone" and stays out of the
split by language.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from joop.agent.engine import ERROR_REPLY

ROOT = Path(__file__).resolve().parents[1]
NAME = re.compile(r"^(?P<day>\d{4}-\d{2}-\d{2})T\d{4}Z_run(?P<run>\d+)_results"
                  r"(?:_(?!r\d+\.json$)(?P<tail>.+?))?(?:_r(?P<repeat>\d+))?\.json$")  # …_results_r2.json: the base set
DENTAL = ("dental", "dental_base")  # the two sets a file named …_results_dental.json may hold


def _cases(path: Path) -> list[dict]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data["cases"] if isinstance(data, dict) else data


def dialogues(root: Path = ROOT) -> dict[tuple[str, str], str]:
    """Today's dialogues: (set, id) -> "ky" or ""."""
    found: dict[tuple[str, str], str] = {}
    sets = {path.parent.name: path for path in sorted((root / "joop" / "niches").glob("*/cases.yaml"))}
    sets["base"], sets["dental_base"] = root / "eval" / "cases.yaml", root / "eval" / "cases_dental.yaml"
    for name, path in sets.items():
        if not path.exists():
            continue
        for case in _cases(path):
            if (name, case["id"]) in found:
                raise ValueError(f"{path}: the id {case['id']!r} is used twice")
            found[(name, case["id"])] = "ky" if case.get("expect_lang") == "ky" else ""
    return found


@dataclass
class Result:
    run: int
    day: str
    tail: str  # "" for the base set, else what follows _results_ in the file's name
    data: dict

    def names(self) -> tuple[str, ...]:
        """The sets this file's cases may belong to."""
        if self.tail == "dental_profile":
            return ("dental_base",)
        if self.tail == "dental":
            source = str(self.data.get("business_file", ""))
            if "niches/dental/" in source:
                return ("dental",)
            if "business.dental" in source:
                return ("dental_base",)
            return DENTAL  # no word of it in the file: the set that has the case's id
        return (self.tail or "base",)

    def set_of(self, case_id: str, today: dict[tuple[str, str], str]) -> str | None:
        """The set this file's case belongs to, or None when today has no such dialogue."""
        return next((name for name in self.names() if (name, case_id) in today), None)


def read_runs(folder: Path) -> list[Result]:
    """Every result file of a real run in `folder`, in the order of their names. Dry runs and files that are not a
    run's results are left out."""
    found = []
    for path in sorted(folder.glob("*.json")):
        match = NAME.match(path.name)
        if not match:
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or "cases" not in data or data.get("dry_run"):
            continue
        found.append(Result(int(match["run"]), match["day"], match["tail"] or "", data))
    return found


def answered(case: dict) -> bool:
    """The model itself answered: the dialogue's last reply is neither empty nor the fallback customers get."""
    return not case.get("fallback") and (case.get("final_reply") or "").strip() not in ("", ERROR_REPLY.strip())


@dataclass
class Coverage:
    today: dict[tuple[str, str], str]
    ran: set[tuple[str, str]] = field(default_factory=set)

    @property
    def never(self) -> set[tuple[str, str]]:
        return set(self.today) - self.ran

    def kyrgyz(self, dialogues_: set[tuple[str, str]]) -> int:
        return sum(1 for d in dialogues_ if self.today[d] == "ky")


def coverage(today: dict[tuple[str, str], str], results: list[Result]) -> Coverage:
    found = Coverage(today)
    for result in results:
        for case in result.data["cases"]:
            name = result.set_of(case["id"], today)
            if name and answered(case):
                found.ran.add((name, case["id"]))
    return found


@dataclass
class Row:
    """One run, or several together: passed / all, split by today's language of each dialogue."""
    label: str
    day: str = ""
    kyrgyz: list[int] = field(default_factory=lambda: [0, 0])  # passed, all
    other: list[int] = field(default_factory=lambda: [0, 0])
    gone: list[int] = field(default_factory=lambda: [0, 0])  # dialogues that no longer exist: language unknown
    confirmation_fixed: int = 0
    language_fixed: int = 0
    cost: float = 0.0
    seconds: list[float] = field(default_factory=list)

    @property
    def all(self) -> list[int]:
        return [self.kyrgyz[0] + self.other[0] + self.gone[0], self.kyrgyz[1] + self.other[1] + self.gone[1]]

    def add(self, other: "Row") -> None:
        for mine, theirs in ((self.kyrgyz, other.kyrgyz), (self.other, other.other), (self.gone, other.gone)):
            mine[0] += theirs[0]
            mine[1] += theirs[1]
        self.confirmation_fixed += other.confirmation_fixed
        self.language_fixed += other.language_fixed
        self.cost += other.cost
        self.seconds += other.seconds


def run_rows(today: dict[tuple[str, str], str], results: list[Result], wanted: set[int]) -> list[Row]:
    """A row for each wanted run that has results, in order, and one more for all of them together when there are
    several."""
    rows: dict[int, Row] = {}
    sets = {name for name, _id in today}
    for result in results:
        if result.run not in wanted or not any(name in sets for name in result.names()):
            continue  # another run, or a file of no set of today's (another tool's)
        row = rows.setdefault(result.run, Row(str(result.run), result.day))
        row.cost += float(result.data.get("summary", {}).get("total_cost_usd") or 0)
        for case in result.data["cases"]:
            name = result.set_of(case["id"], today)
            cell = row.gone if name is None else row.kyrgyz if today[(name, case["id"])] == "ky" else row.other
            cell[0] += bool(case.get("passed"))
            cell[1] += 1
            row.confirmation_fixed += bool(case.get("confirmation_fixed"))
            row.language_fixed += bool(case.get("language_fixed"))
            if case.get("avg_latency_s") is not None:
                row.seconds.append(float(case["avg_latency_s"]))
    ordered = [rows[run] for run in sorted(rows)]
    if len(ordered) > 1:
        total = Row(f"{ordered[0].label}–{ordered[-1].label}" if len(wanted) == len(ordered) and len(wanted) == max(wanted) - min(wanted) + 1
                    else "together")
        for row in ordered:
            total.add(row)
        ordered.append(total)
    return ordered


def _share(cell: list[int]) -> str:
    passed, everything = cell
    return f"{passed}/{everything} ({passed / everything * 100:.1f}%)" if everything else "—"


def render_coverage(found: Coverage) -> str:
    today, never = found.today, found.never
    by_set = Counter(name for name, _id in never)
    lines = [f"Today: {len(today)} dialogues in {len({name for name, _id in today})} sets, {sum(1 for lang in today.values() if lang == 'ky')} of them in Kyrgyz.",
             f"Answered by the real model at least once: {len(found.ran)} ({found.kyrgyz(found.ran)} in Kyrgyz).",
             f"Never run on the real model: {len(never)} ({found.kyrgyz(never)} in Kyrgyz)."]
    if never:
        lines.append("Never run, by set: " + ", ".join(f"{name} {n}" for name, n in sorted(by_set.items())) + ".")
    return "\n".join(lines)


def render_runs(rows: list[Row]) -> str:
    lines = ["| Run | Day | Passed | Kyrgyz | Others | Confirmation fixed | Language fixed | Cost, USD | Avg reply, s |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for row in rows:
        seconds = f"{sum(row.seconds) / len(row.seconds):.2f}" if row.seconds else "—"
        gone = f"; {row.gone[1]} gone" if row.gone[1] else ""
        lines.append(f"| {row.label} | {row.day} | {_share(row.all)} | {_share(row.kyrgyz)} | {_share(row.other)}{gone} | "
                     f"{row.confirmation_fixed} | {row.language_fixed} | {row.cost:.3f} | {seconds} |")
    return "\n".join(lines)


def runs_wanted(text: str) -> set[int]:
    """«33», «30-35», «30-33,35»."""
    wanted: set[int] = set()
    for part in text.replace(" ", "").split(","):
        if not part:
            continue
        first, _dash, last = part.partition("-")
        wanted |= set(range(int(first), int(last or first) + 1))
    return wanted


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Which of today's dialogues the real model has ever answered; stored runs by language.")
    parser.add_argument("folder", help="the folder with the result files: runs/ of the eval-results branch")
    parser.add_argument("--runs", default="", help="runs to show by language, e.g. 33 or 30-35")
    args = parser.parse_args(argv)
    folder = Path(args.folder)
    results = read_runs(folder)
    if not results:
        print(f"No result files of a real run in {folder}", file=sys.stderr)
        return 1
    today = dialogues()
    print(render_coverage(coverage(today, results)))
    if args.runs:
        rows = run_rows(today, results, runs_wanted(args.runs))
        print()
        print(render_runs(rows) if rows else f"No results of runs {args.runs} in {folder}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
