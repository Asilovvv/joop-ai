"""The niche's example data that sign-up puts into a new business, so the test chat answers at once.

It is fictional: prices, masters, answers such as «бесплатная парковка у входа». While a row is still the example, the
AI tells real customers these things as fact, and the launch checklist must not count the section as done. A row is
the example while it is exactly as the pack wrote it (joop/niches/<niche>/demo.yaml): the same name and price, the same
name, role and what the person takes, the same question and answer. Any edit makes it the business's own; deleting it
removes it. When some of the business's real rows happen to equal the example, the owner confirms it once
(Business.example_ok) and nothing is flagged any more.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

from sqlmodel import Session, select

from .models import Business, Faq, Service, Staff
from .niches import get_pack
from .profile import ProfileError, load_profile


def _t(value) -> str:
    return " ".join(str(value or "").split())


@dataclass(frozen=True)
class Left:
    """Rows still equal to the sign-up example, by section."""

    services: list[str] = field(default_factory=list)
    staff: list[str] = field(default_factory=list)
    faq: list[str] = field(default_factory=list)

    @property
    def any(self) -> bool:
        return bool(self.services or self.staff or self.faq)


@lru_cache(maxsize=64)
def _example(niche: str) -> tuple[frozenset, frozenset, frozenset]:
    try:
        data = load_profile(get_pack(niche).demo_file)
    except (ProfileError, OSError, KeyError):
        return frozenset(), frozenset(), frozenset()
    services = frozenset((_t(x.get("name")), _t(x.get("price"))) for x in data.get("services") or [])
    staff = frozenset((_t(x.get("name")), _t(x.get("role")), _t(x.get("handles"))) for x in data.get("resources") or [])
    faq = frozenset((_t(x.get("q")), _t(x.get("a"))) for x in data.get("faq") or [])
    return services, staff, faq


def left(session: Session, business: Business) -> Left:
    if business.example_ok:
        return Left()
    services, staff, faq = _example(business.niche)
    return Left(
        services=[r.name for r in session.exec(select(Service).where(Service.business_id == business.id).order_by(Service.sort, Service.id)).all()
                  if (_t(r.name), _t(r.price)) in services],
        staff=[r.name for r in session.exec(select(Staff).where(Staff.business_id == business.id, Staff.active == True)  # noqa: E712
                                            .order_by(Staff.id)).all()
               if (_t(r.name), _t(r.role), _t(r.handles)) in staff],
        faq=[r.question for r in session.exec(select(Faq).where(Faq.business_id == business.id).order_by(Faq.id)).all()
             if (_t(r.question), _t(r.answer)) in faq],
    )


def warning(found: Left) -> str:
    """One line for flashes: what is still the example."""
    parts = [f"{label}: {', '.join(names[:3])}{' и ещё ' + str(len(names) - 3) if len(names) > 3 else ''}"
             for label, names in (("прайс", found.services), ("сотрудники", found.staff), ("ответы", found.faq)) if names]
    return "Ещё из примера — " + "; ".join(parts) + ". ИИ говорит это клиентам как правду: замените на своё или удалите."
