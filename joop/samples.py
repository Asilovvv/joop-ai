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
from .stats import TEST_CHANNEL


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


def _rows(session: Session, business: Business) -> tuple[list[Service], list[Staff], list[Faq]]:
    """The business's rows that are still exactly the example (none once the owner confirmed them)."""
    if business.example_ok:
        return [], [], []
    services, staff, faq = _example(business.niche)
    return (
        [r for r in session.exec(select(Service).where(Service.business_id == business.id).order_by(Service.sort, Service.id)).all()
         if (_t(r.name), _t(r.price)) in services],
        [r for r in session.exec(select(Staff).where(Staff.business_id == business.id, Staff.active == True)  # noqa: E712
                                 .order_by(Staff.id)).all()
         if (_t(r.name), _t(r.role), _t(r.handles)) in staff],
        [r for r in session.exec(select(Faq).where(Faq.business_id == business.id).order_by(Faq.id)).all()
         if (_t(r.question), _t(r.answer)) in faq],
    )


def left(session: Session, business: Business) -> Left:
    services, staff, faq = _rows(session, business)
    return Left(services=[r.name for r in services], staff=[r.name for r in staff], faq=[r.question for r in faq])


@dataclass(frozen=True)
class Hidden:
    """Example rows the AI does not use with real customers: no example price, person, free time or answer reaches
    them. Without a price list the prompt already says «цены уточняет администратор», without free times the AI
    takes a request for staff to confirm."""

    services: frozenset[int] = frozenset()
    staff: frozenset[int] = frozenset()
    faq: frozenset[int] = frozenset()

    def __bool__(self) -> bool:
        return bool(self.services or self.staff or self.faq)


def hidden_from_customers(session: Session, business: Business, channel: str) -> Hidden:
    """The panel's test chat and the site demo (channel "console") keep the example: there it is the point."""
    if channel == TEST_CHANNEL:
        return Hidden()
    services, staff, faq = _rows(session, business)
    return Hidden(frozenset(r.id for r in services), frozenset(r.id for r in staff), frozenset(r.id for r in faq))


def warning(found: Left) -> str:
    """One line for flashes: what is still the example."""
    parts = [f"{label}: {', '.join(names[:3])}{' и ещё ' + str(len(names) - 3) if len(names) > 3 else ''}"
             for label, names in (("прайс", found.services), ("сотрудники", found.staff), ("ответы", found.faq)) if names]
    return "Ещё из примера — " + "; ".join(parts) + ". ИИ говорит это клиентам как правду: замените на своё или удалите."
