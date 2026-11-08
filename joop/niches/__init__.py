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
OUTCOMES = {"booking", "request", "order", "lead", "handoff", "stay"}  # stay: dates of a room or hall, joop/stays.py
# A hotel books nights (check-in to check-out), a banquet hall books one date, car rental books days from pickup to return.
STAY_BY = {"night", "day", "rental"}
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
    stay_by: str = "night"
    jobs_delivered: bool = False  # jobs are made to order and delivered (furniture), not picked up (repair)
    lead_minutes: int = 60  # free times offered no sooner than this; a car wash takes «можно сейчас?» in 15 minutes

    def has(self, outcome: str) -> bool:
        return outcome in self.outcomes

    def offers(self, feature: str) -> bool:
        return feature in self.features

    @property
    def serves_tables(self) -> bool:
        """A cafe or restaurant: orders and bookings at tables, a QR code on every table."""
        return self.has("order") and self.has("booking") and self.party_size

    @property
    def orders_first(self) -> bool:
        """A shop (florist, wholesale, Instagram shop): orders are its results, not bookings or stays."""
        return self.has("order") and not self.has("booking") and not self.has("stay")

    @property
    def online_label(self) -> str:
        """The panel's name for the public price page (joop/web/menu.py)."""
        return "QR-меню" if self.serves_tables else "Каталог онлайн" if self.has("order") else "Прайс онлайн"

    @property
    def stay_noun(self) -> str:
        """What is booked, in «Брони …» and «броней … сделал ИИ»."""
        return {"day": "залов", "rental": "машин"}.get(self.stay_by, "номеров")

    @property
    def rental(self) -> bool:
        """Stays are rentals of a vehicle (car hire): days from pickup to return, no guests."""
        return self.stay_by == "rental"

    @property
    def by_day(self) -> bool:
        """Stays are single dates (a banquet hall, an event venue), not nights from check-in to check-out."""
        return self.stay_by == "day"

    def examples(self) -> tuple[str, str]:
        """A Russian and a Kyrgyz first message of this niche's customers, for the test chat's hint."""
        return _examples(self.name)

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
    stay_by = data.get("stay_by") or "night"
    if stay_by not in STAY_BY:
        raise ValueError(f"Pack {name}: stay_by must be one of {sorted(STAY_BY)}")
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
        stay_by=stay_by,
        jobs_delivered=bool(data.get("jobs_delivered", False)),
        lead_minutes=max(0, int(data.get("lead_minutes", 60))),
    )


DEFAULT_EXAMPLES = ("Сколько стоит консультация?", "Эртең жазылсам болобу?")


@lru_cache
def _examples(name: str) -> tuple[str, str]:
    """The first Russian and the first Kyrgyz turn of the pack's evaluation dialogues (cases.yaml)."""
    path = PACKS_DIR / name / "cases.yaml"
    cases = (yaml.safe_load(path.read_text(encoding="utf-8")) or []) if path.exists() else []
    ru = next((c["turns"][0] for c in cases if c.get("expect_lang") != "ky" and c.get("turns")), DEFAULT_EXAMPLES[0])
    ky = next((c["turns"][0] for c in cases if c.get("expect_lang") == "ky" and c.get("turns")), DEFAULT_EXAMPLES[1])
    return ru, ky


@lru_cache
def all_packs() -> dict[str, Pack]:
    names = sorted(p.parent.name for p in PACKS_DIR.glob("*/pack.yaml"))
    return {n: _load(n) for n in names}


def picker_packs() -> dict[str, Pack]:
    """The packs as people choose them: by Russian name, «Другой бизнес» last (all_packs() is by English key)."""
    packs = all_packs()
    return dict(sorted(packs.items(), key=lambda kv: (kv[0] == "other", kv[1].label.casefold())))


def get_pack(name: str | None) -> Pack:
    packs = all_packs()
    return packs.get(name or "", packs["other"])
