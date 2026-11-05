"""What the model would receive in the evaluation, without calling the model.

Runs every evaluation dialogue (all niche packs with cases) with a stand-in model that always answers
«Здравствуйте! Чем помочь?» and a frozen clock, and writes a hash of every system prompt. Two runs on
the same code give the same file. Run it on main and on a branch and compare:

    python -m eval.prompt_hashes /tmp/main.json          # on main
    python -m eval.prompt_hashes /tmp/branch.json        # on the branch
    python -m eval.prompt_hashes --compare /tmp/main.json /tmp/branch.json

«identical» means the branch cannot change what the evaluation measures (the model gets the same
input); any other answer lists the dialogues whose prompt changed, which then need a real run.
Only the first reply of each turn is fake, so later turns are the same dialogue on both sides.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime

from joop import timeutil
from joop.agent.llm import AgentReply

FROZEN = datetime(2026, 11, 4, 6, 0)  # a Wednesday, 12:00 in Bishkek: working hours, slots tomorrow
_TOKEN = re.compile(r"/t/[0-9a-f]+")  # per-dialogue random links (level tests) are not a prompt change


class _Recorder:
    model = "claude-haiku-5-5"

    def __init__(self) -> None:
        self.systems: list[str] = []

    def respond(self, system, messages, schema=None):
        self.systems.append(_TOKEN.sub("/t/TOKEN", system))
        return AgentReply("Здравствуйте! Чем помочь?")

    def rewrite_in_kyrgyz(self, text, usage):
        return None

    def remove_false_confirmation(self, text, usage):
        return None


def hashes() -> dict[str, list[str]]:
    from joop.niches import all_packs

    from . import run_eval

    timeutil.clock = lambda: FROZEN
    out: dict[str, list[str]] = {}
    for name, pack in sorted(all_packs().items()):
        if not pack.cases_file.exists():
            continue
        rec = _Recorder()
        run_eval.run(str(pack.demo_file), str(pack.cases_file), lambda: rec, rec.model)
        out[name] = [hashlib.sha256(x.encode()).hexdigest()[:16] for x in rec.systems]
    return out


def compare(a: dict[str, list[str]], b: dict[str, list[str]]) -> list[str]:
    changed = []
    for pack in sorted(set(a) | set(b)):
        x, y = a.get(pack, []), b.get(pack, [])
        if len(x) != len(y):
            changed.append(f"{pack}: {len(x)} prompts → {len(y)}")
        else:
            diff = [i for i, (p, q) in enumerate(zip(x, y)) if p != q]
            if diff:
                changed.append(f"{pack}: {len(diff)} of {len(x)} prompts changed")
    return changed


def main() -> None:
    if sys.argv[1:2] == ["--compare"]:
        a, b = (json.loads(open(p, encoding="utf-8").read()) for p in sys.argv[2:4])
        changed = compare(a, b)
        total = sum(len(v) for v in a.values())
        print(f"identical: all {total} prompts" if not changed else "\n".join(changed))
        sys.exit(1 if changed else 0)
    result = hashes()
    with open(sys.argv[1], "w", encoding="utf-8") as f:
        json.dump(result, f, indent=0)
    print(f"{sum(len(v) for v in result.values())} prompts in {len(result)} packs → {sys.argv[1]}")


if __name__ == "__main__":
    main()
