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

from .models import Business, Faq, Job, PlacementTest, Service, Staff
from .niches import get_pack
from .profile import ProfileError, load_profile
from .stats import TEST_CHANNEL


def _t(value) -> str:
    return " ".join(str(value or "").split())


def _niche(business: Business) -> str:
    """The niche whose example sign-up added: switching the niche in settings must not turn the example into real data."""
    return business.example_niche or business.niche


@dataclass(frozen=True)
class Left:
    """Rows still equal to the sign-up example, by section."""

    services: list[str] = field(default_factory=list)
    staff: list[str] = field(default_factory=list)
    faq: list[str] = field(default_factory=list)
    tests: list[str] = field(default_factory=list)  # a school's demo level test (joop/placement.py)
    jobs: list[str] = field(default_factory=list)  # a repair shop's demo receipts (joop/jobs.py)

    @property
    def any(self) -> bool:
        return bool(self.services or self.staff or self.faq or self.tests or self.jobs)


def _staff_key(name: str, role: str, handles: str, capacity, group_size) -> tuple:
    """A person, room or hall is the example only while its seats and room count are the example's too:
    an owner who typed the real capacity of «Большой зал» has made it theirs."""
    return name, role, handles, int(capacity or 0), max(1, int(group_size or 0))


@lru_cache(maxsize=64)
def _example(niche: str) -> tuple[frozenset, frozenset, frozenset]:
    try:
        data = load_profile(get_pack(niche).demo_file)
    except (ProfileError, OSError, KeyError):
        return frozenset(), frozenset(), frozenset()
    services = frozenset((_t(x.get("name")), _t(x.get("price"))) for x in data.get("services") or [])
    staff = frozenset(_staff_key(_t(x.get("name")), _t(x.get("role")), _t(x.get("handles")), x.get("capacity"), x.get("group_size"))
                      for x in data.get("resources") or [])
    faq = frozenset((_t(x.get("q")), _t(x.get("a"))) for x in data.get("faq") or [])
    return services, staff, faq


@lru_cache(maxsize=64)
def _example_test(niche: str) -> tuple[str, frozenset[str]]:
    """The pack's demo level test: its title and question texts («Английский: тест на уровень (демо)», eight samples)."""
    try:
        test = load_profile(get_pack(niche).demo_file).get("placement_test") or {}
    except (ProfileError, OSError, KeyError):
        return "", frozenset()
    return _t(test.get("title")), frozenset(_t(q[1]) for q in test.get("questions") or [] if len(q) > 1)


def _tests(session: Session, business: Business) -> list[PlacementTest]:
    """Level tests still exactly the demo (its title and its questions): a real customer does not get a sample test.
    Renaming the test or changing its questions makes it the school's own; Business.example_ok lifts it too."""
    from .models import PlacementQuestion

    if business.example_ok:
        return []
    title, questions = _example_test(_niche(business))
    if not title:
        return []
    out = []
    for x in session.exec(select(PlacementTest).where(PlacementTest.business_id == business.id).order_by(PlacementTest.id)).all():
        if _t(x.title) != title:
            continue
        texts = frozenset(_t(q) for q in session.exec(select(PlacementQuestion.text).where(PlacementQuestion.test_id == x.id)).all())
        if texts == questions:
            out.append(x)
    return out


@lru_cache(maxsize=64)
def _example_jobs(niche: str) -> frozenset[tuple[str, str, str]]:
    """The pack's demo receipts (number, phone's last 9 digits, item): fictional customers with phone numbers."""
    try:
        data = load_profile(get_pack(niche).demo_file)
    except (ProfileError, OSError, KeyError):
        return frozenset()
    return frozenset((_t(x.get("number")), "".join(c for c in str(x.get("phone") or "") if c.isdigit())[-9:], _t(x.get("item")))
                     for x in data.get("jobs") or [])


def _jobs(session: Session, business: Business) -> list[Job]:
    """Receipts still exactly the demo: a real customer whose phone happens to match must not hear «пальто готово»."""
    if business.example_ok:
        return []
    demo = _example_jobs(_niche(business))
    if not demo:
        return []
    return [j for j in session.exec(select(Job).where(Job.business_id == business.id).order_by(Job.id)).all()
            if (_t(j.number), j.phone_key, _t(j.item)) in demo]


def hours_are_example(business: Business) -> bool:
    """The opening hours sign-up copied from the example and nobody has changed or confirmed yet."""
    if business.example_ok or not business.hours_text:
        return False
    try:
        hours = _t(load_profile(get_pack(_niche(business)).demo_file).get("hours"))
    except (ProfileError, OSError, KeyError):
        return False
    return bool(hours) and _t(business.hours_text) == hours


def _rows(session: Session, business: Business) -> tuple[list[Service], list[Staff], list[Faq]]:
    """The business's rows that are still exactly the example (none once the owner confirmed them)."""
    if business.example_ok:
        return [], [], []
    services, staff, faq = _example(_niche(business))
    return (
        [r for r in session.exec(select(Service).where(Service.business_id == business.id).order_by(Service.sort, Service.id)).all()
         if (_t(r.name), _t(r.price)) in services],
        [r for r in session.exec(select(Staff).where(Staff.business_id == business.id, Staff.active == True)  # noqa: E712
                                 .order_by(Staff.id)).all()
         if _staff_key(_t(r.name), _t(r.role), _t(r.handles), r.capacity, r.group_size) in staff],
        [r for r in session.exec(select(Faq).where(Faq.business_id == business.id).order_by(Faq.id)).all()
         if (_t(r.question), _t(r.answer)) in faq],
    )


def example_staff_ids(session: Session, business: Business) -> set[int]:
    """Staff rows that are still the sign-up example: they are nobody, so they do not count as masters."""
    return {r.id for r in _rows(session, business)[1]}


def left(session: Session, business: Business) -> Left:
    services, staff, faq = _rows(session, business)
    return Left(services=[r.name for r in services], staff=[r.name for r in staff], faq=[r.question for r in faq],
                tests=[x.title for x in _tests(session, business)], jobs=[f"№{j.number}" for j in _jobs(session, business)])


@dataclass(frozen=True)
class Hidden:
    """Example rows the AI does not use with real customers: no example price, person, free time or answer reaches
    them. Without a price list the prompt already says «цены уточняет администратор», without free times the AI
    takes a request for staff to confirm."""

    services: frozenset[int] = frozenset()
    staff: frozenset[int] = frozenset()
    faq: frozenset[int] = frozenset()
    tests: frozenset[int] = frozenset()
    jobs: frozenset[int] = frozenset()
    hours: bool = False  # the opening hours are still the example's (hours_are_example)

    def __bool__(self) -> bool:
        return bool(self.services or self.staff or self.faq or self.tests or self.jobs or self.hours)


def hidden_from_customers(session: Session, business: Business, channel: str) -> Hidden:
    """The panel's test chat and the site demo (channel "console") keep the example: there it is the point."""
    if channel == TEST_CHANNEL:
        return Hidden()
    services, staff, faq = _rows(session, business)
    return Hidden(frozenset(r.id for r in services), frozenset(r.id for r in staff), frozenset(r.id for r in faq),
                  frozenset(x.id for x in _tests(session, business)), frozenset(j.id for j in _jobs(session, business)),
                  hours_are_example(business))


def warning(found: Left) -> str:
    """One line for flashes: what is still the example."""
    parts = [f"{label}: {', '.join(names[:3])}{' и ещё ' + str(len(names) - 3) if len(names) > 3 else ''}"
             for label, names in (("прайс", found.services), ("сотрудники", found.staff), ("ответы", found.faq),
                                  ("тест на уровень", found.tests), ("квитанции", found.jobs)) if names]
    return "Ещё из примера — " + "; ".join(parts) + ". Клиентам ИИ это не называет, пока вы не замените пример своими данными или не удалите его."
