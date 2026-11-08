"""Print a Markdown summary of one or more eval result files (used in CI run summaries).

Usage:
    python -m eval.summary eval/results.json eval/results_dental.json
    python -m eval.summary --thesis eval/results*.json           # per-metric table for the thesis (Markdown)
    python -m eval.summary --thesis --latex eval/results*.json   # the same table as a LaTeX tabular
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def render(paths: list[str]) -> str:
    lines = [
        "| Set | Passed | Avg / max reply, s | Avg cost per conversation, USD | Language guard fired |",
        "| --- | --- | --- | --- | --- |",
    ]
    failures = []
    for p in paths:
        path = Path(p)
        if not path.exists():
            lines.append(f"| {path.name} | no results | | | |")
            continue
        data = json.loads(path.read_text("utf-8"))
        s = data["summary"]
        cost = s.get("avg_cost_usd_per_conversation")
        lines.append(
            f"| {Path(data.get('business_file', path.name)).name} | {s['passed']}/{s['cases']} "
            f"| {s['avg_latency_s']} / {s['max_latency_s']} "
            f"| {cost if cost is not None else 'unknown'} | {s.get('language_guard_fired', 0)} |"
        )
        for c in data["cases"]:
            if not c["passed"]:
                why = f" ({c['errors'][0]})" if c.get("errors") else ""
                failures.append(f"- `{c['id']}`: {'; '.join(c['fails'])}{why}")
    out = "\n".join(lines)
    if failures:
        out += "\n\nFailed cases:\n" + "\n".join(failures)
    return out + "\n"


THESIS_METRICS = ("facts", "answer", "action", "handoff", "kyrgyz")
THESIS_HEADER = ("Set", "Cases", "Passed", "Invented facts", "Correct answer", "Action accuracy",
                 "Hand-off accuracy", "Kyrgyz reply", "Cost per conversation, USD")


def set_name(data: dict, path: Path) -> str:
    """A pack's results are named after the pack (joop/niches/<pack>/demo.yaml), others after the profile file."""
    f = Path(data.get("business_file", path.name))
    name = f.parent.name if f.name == "demo.yaml" else f.stem
    repeat = re.search(r"_r(\d+)$", path.stem)  # repeated runs of one pack: results_<pack>_r<N>.json
    return f"{name} (run {repeat.group(1)})" if repeat else name


def _share(passed: int, n: int, invert: bool = False) -> str:
    if not n:
        return "—"
    k = n - passed if invert else passed
    return f"{k}/{n} ({100 * k / n:.1f}%)"


def thesis_rows(paths: list[str]) -> tuple[list[list[str]], bool]:
    """Rows of the thesis table (one per result file, then Total) and whether any file is a dry run.

    "Invented facts" counts the cases whose reply contains a forbidden fact (lower is better); the other
    metrics count the cases that met the expectation. A case counts only towards the metrics it checks."""
    rows, dry = [], False
    total = {"cases": 0, "passed": 0, "cost": 0.0, "costed": 0, **{k: [0, 0] for k in THESIS_METRICS}}
    for p in sorted(paths):
        path = Path(p)
        if not path.exists():
            continue
        data = json.loads(path.read_text("utf-8"))
        s = data["summary"]
        if "metrics" not in s:  # older results and the Kyrgyz suggestions check have no per-metric counts
            continue
        dry = dry or bool(data.get("dry_run"))
        m = s.get("metrics", {})
        row = [set_name(data, path), str(s["cases"]), _share(s["passed"], s["cases"])]
        for k in THESIS_METRICS:
            got = m.get(k, {"cases": 0, "passed": 0})
            row.append(_share(got["passed"], got["cases"], invert=k == "facts"))
            total[k][0] += got["passed"]
            total[k][1] += got["cases"]
        cost = s.get("avg_cost_usd_per_conversation")
        row.append(f"{cost:.4f}" if cost is not None else "—")
        if s.get("total_cost_usd") is not None:
            total["cost"] += s["total_cost_usd"]
            total["costed"] += s["cases"]
        total["cases"] += s["cases"]
        total["passed"] += s["passed"]
        rows.append(row)
    if rows:
        row = ["Total", str(total["cases"]), _share(total["passed"], total["cases"])]
        row += [_share(total[k][0], total[k][1], invert=k == "facts") for k in THESIS_METRICS]
        row.append(f"{total['cost'] / total['costed']:.4f}" if total["costed"] else "—")
        rows.append(row)
    return rows, dry


DRY_NOTE = "DRY RUN: scripted replies without a model; these numbers check the pipeline and are not results."


def thesis_markdown(paths: list[str]) -> str:
    rows, dry = thesis_rows(paths)
    lines = ["| " + " | ".join(THESIS_HEADER) + " |", "|" + " --- |" * len(THESIS_HEADER)]
    lines += ["| " + " | ".join(r) + " |" for r in rows]
    return (f"**{DRY_NOTE}**\n\n" if dry else "") + "\n".join(lines) + "\n"


def _tex(s: str) -> str:
    return s.replace("\\", "\\textbackslash{}").replace("_", "\\_").replace("%", "\\%").replace("&", "\\&").replace("—", "---")


def thesis_latex(paths: list[str]) -> str:
    rows, dry = thesis_rows(paths)
    out = [f"% {DRY_NOTE}"] if dry else []
    out += ["\\resizebox{\\textwidth}{!}{%", "\\begin{tabular}{|l|r|r|r|r|r|r|r|r|}", "\\hline",
            " & ".join(f"\\textbf{{{_tex(h)}}}" for h in THESIS_HEADER) + " \\\\", "\\hline"]
    for r in rows:
        cells = [_tex(c) for c in r]
        if r[0] == "Total":
            out.append("\\hline")
            cells = [f"\\textbf{{{c}}}" for c in cells]
        out.append(" & ".join(cells) + " \\\\")
    out += ["\\hline", "\\end{tabular}}"]
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    args = sys.argv[1:]
    files = [a for a in args if not a.startswith("--")]
    if "--thesis" in args:
        print(thesis_latex(files) if "--latex" in args else thesis_markdown(files), end="")
    else:
        print(render(files))
