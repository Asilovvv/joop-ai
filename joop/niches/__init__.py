"""Niche packs: what differs between a dental clinic, a restaurant or a real-estate agency.

Each pack is a folder with pack.yaml (labels, enabled outcomes, rules), demo.yaml (a fictional demo
business) and cases.yaml (evaluation dialogues). The core reads packs; it never checks niche names.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

PACKS_DIR = Path(__file__).parent
OUTCOMES = {"booking", "request", "order", "lead", "handoff"}
# Optional modules a pack switches on: level_test (joop/placement.py), group_classes (slots with several
# seats), memberships (passes and packages of visits, joop/memberships.py), jobs (order status for items
# left for work, joop/jobs.py).
FEATURES = {"level_test", "group_classes", "memberships", "jobs"}


@dataclass(frozen=True)
class Pack:
    name: str
    label: str  # shown in the panel: "Стоматологии"
    who: str  # genitive for the prompt: "стоматологической клиники"
    catalog_label: str = "Прайс"
    catalog_item: str = "услуга"
    resource_label: str = "Специалисты"
    resource_item: str = "специалист"
    outcomes: frozenset[str] = frozenset({"booking", "request", "handoff"})
    party_size: bool = False  # bookings carry a number of guests checked against resource capacity
    lead_fields: tuple[str, ...] = ()  # what to ask before a qualified lead
    order_modes: tuple[str, ...] = ("pickup", "delivery")
    rules: tuple[str, ...] = field(default_factory=tuple)
    features: frozenset[str] = frozenset()

    def has(self, outcome: str) -> bool:
        return outcome in self.outcomes

    def offers(self, feature: str) -> bool:
        return feature in self.features

    @property
    def dir(self) -> Path:
        return PACKS_DIR / self.name

    @property
    def demo_file(self) -> Path:
        return self.dir / "demo.yaml"

    @property
    def cases_file(self) -> Path:
        return self.dir / "cases.yaml"


def _load(name: str) -> Pack:
    data = yaml.safe_load((PACKS_DIR / name / "pack.yaml").read_text(encoding="utf-8")) or {}
    outcomes = frozenset(data.get("outcomes") or ["booking", "request", "handoff"])
    unknown = outcomes - OUTCOMES
    if unknown:
        raise ValueError(f"Pack {name}: unknown outcomes {sorted(unknown)}")
    features = frozenset(data.get("features") or [])
    if features - FEATURES:
        raise ValueError(f"Pack {name}: unknown features {sorted(features - FEATURES)}")
    return Pack(
        name=name,
        label=data["label"],
        who=data["who"],
        catalog_label=data.get("catalog_label", "Прайс"),
        catalog_item=data.get("catalog_item", "услуга"),
        resource_label=data.get("resource_label", "Специалисты"),
        resource_item=data.get("resource_item", "специалист"),
        outcomes=outcomes,
        party_size=bool(data.get("party_size", False)),
        lead_fields=tuple(data.get("lead_fields") or ()),
        order_modes=tuple(data.get("order_modes") or ("pickup", "delivery")),
        rules=tuple(data.get("rules") or ()),
        features=features,
    )


@lru_cache
def all_packs() -> dict[str, Pack]:
    names = sorted(p.parent.name for p in PACKS_DIR.glob("*/pack.yaml"))
    return {n: _load(n) for n in names}


def get_pack(name: str | None) -> Pack:
    packs = all_packs()
    return packs.get(name or "", packs["other"])
