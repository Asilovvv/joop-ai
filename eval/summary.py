"""Print a Markdown summary of one or more eval result files (used in CI run summaries).

Usage:
    python -m eval.summary eval/results.json eval/results_dental.json
"""

from __future__ import annotations

import json
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
                failures.append(f"- `{c['id']}`: {'; '.join(c['fails'])}")
    out = "\n".join(lines)
    if failures:
        out += "\n\nFailed cases:\n" + "\n".join(failures)
    return out + "\n"


if __name__ == "__main__":
    print(render(sys.argv[1:]))
