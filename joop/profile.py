"""Business profiles in YAML: a quick way to load a client's price list, FAQ and rules.

Format (see business.dental.example.yaml): name, description, address, hours, phone, services
[{name, name_ky, price, duration, note}], faq [{q, a}], booking_policy, tone, rules [...].
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from sqlmodel import Session, select

from datetime import datetime, timedelta

from .catalog import parse_price
from .models import Business, Faq, Service, Staff
from .niches import all_packs
from .slots import generate_slots
from .timeutil import local_now, parse_hhmm


class ProfileError(ValueError):
    pass


def load_profile(path: str | Path) -> dict[str, Any]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict) or not str(data.get("name") or "").strip():
        raise ProfileError("Business profile must have a 'name'")
    return data


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def apply_profile(
    session: Session, business: Business, data: dict[str, Any], replace: bool = True, now_utc: datetime | None = None
) -> None:
    """Copy a profile into a business. With replace=True the old price list and FAQ are removed.

    Optional keys: `resources` (staff, tables, agents; added when no active one has the same name) and
    `slots` ({days, start, end, step}) to generate free time for every resource from tomorrow on.
    `placement_test` ({title, minutes, scale, questions: [[section, text, [options], right option number]]})
    adds a level test (training centres) when the business has none with that title.
    """
    business.name = _text(data.get("name")) or business.name
    if _text(data.get("niche")) in all_packs():
        business.niche = _text(data.get("niche"))
    business.description = _text(data.get("description"))
    business.address = _text(data.get("address"))
    business.phone = _text(data.get("phone"))
    business.hours_text = _text(data.get("hours"))
    business.booking_policy = _text(data.get("booking_policy"))
    business.tone = _text(data.get("tone"))
    for key in ("min_order", "delivery_fee", "free_delivery_from"):
        if key in data:
            setattr(business, key, int(data.get(key) or 0))
    rules = data.get("rules") or []
    business.extra_rules = "\n".join(f"- {_text(r)}" for r in rules if _text(r))
    session.add(business)

    if replace:
        for row in session.exec(select(Service).where(Service.business_id == business.id)).all():
            session.delete(row)
        for row in session.exec(select(Faq).where(Faq.business_id == business.id)).all():
            session.delete(row)
    for i, item in enumerate(data.get("services") or []):
        name = _text(item.get("name"))
        if not name:
            continue
        notes = [x for x in (_text(item.get("duration")) and f"длительность {_text(item.get('duration'))}", _text(item.get("note"))) if x]
        price = _text(item.get("price"))
        session.add(
            Service(
                business_id=business.id,
                name=name,
                name_ky=_text(item.get("name_ky")),
                price=price,
                price_value=parse_price(price),
                note="; ".join(notes),
                category=_text(item.get("category")),
                available=bool(item.get("available", True)),
                sort=i,
            )
        )
    for item in data.get("faq") or []:
        q, a = _text(item.get("q")), _text(item.get("a"))
        if q and a:
            session.add(Faq(business_id=business.id, question=q, answer=a))

    if "work_start" in data or "work_end" in data or "days_off" in data:
        business.work_start = _text(data.get("work_start")) or business.work_start
        business.work_end = _text(data.get("work_end")) or business.work_end
        business.days_off = ",".join(str(d) for d in data.get("days_off") or []) if "days_off" in data else business.days_off
        session.add(business)

    existing = {m.name for m in session.exec(select(Staff).where(Staff.business_id == business.id, Staff.active == True)).all()}  # noqa: E712
    for item in data.get("resources") or []:
        name = _text(item.get("name"))
        if name and name not in existing:
            session.add(
                Staff(
                    business_id=business.id,
                    name=name,
                    role=_text(item.get("role")),
                    handles=_text(item.get("handles")),
                    capacity=int(item.get("capacity") or 0),
                    group_size=int(item.get("group_size") or 0),
                )
            )
            existing.add(name)
    session.flush()

    plan = data.get("slots")
    if isinstance(plan, dict):
        start = parse_hhmm(_text(plan.get("start")) or business.work_start)
        end = parse_hhmm(_text(plan.get("end")) or business.work_end)
        step = int(plan.get("step") or 60)
        days = int(plan.get("days") or 7)
        today = local_now(business.timezone, now_utc).date()
        for member in session.exec(select(Staff).where(Staff.business_id == business.id, Staff.active == True)).all():  # noqa: E712
            generate_slots(session, business, member.id, today + timedelta(days=1), today + timedelta(days=days), start, end, step)

    test = data.get("placement_test")
    if isinstance(test, dict) and _text(test.get("title")):
        from . import placement
        from .models import PlacementTest

        title = _text(test.get("title"))
        if not session.exec(select(PlacementTest).where(PlacementTest.business_id == business.id, PlacementTest.title == title)).first():
            t = PlacementTest(business_id=business.id, code=placement.new_code(), title=title,
                              scale_text=str(test.get("scale") or "").strip(), minutes=int(test.get("minutes") or 0))
            session.add(t)
            session.flush()
            questions = [{"section": _text(q[0]), "text": _text(q[1]), "options": [_text(o) for o in q[2]], "correct": int(q[3]) - 1}
                         for q in test.get("questions") or []]
            placement.replace_questions(session, t, questions)

    for item in data.get("jobs") or []:  # demo order statuses (repair, dry cleaning, car service)
        from .memberships import phone_key
        from .models import Job

        number = _text(item.get("number"))
        if number and not session.exec(select(Job).where(Job.business_id == business.id, Job.number == number)).first():
            days = item.get("ready_in_days")
            session.add(Job(business_id=business.id, number=number, customer_name=_text(item.get("name")),
                            customer_phone=_text(item.get("phone")), phone_key=phone_key(_text(item.get("phone"))),
                            item=_text(item.get("item")), status=_text(item.get("status")) or "accepted",
                            price=_text(item.get("price")), note=_text(item.get("note")),
                            ready_by=(local_now(business.timezone, now_utc).date() + timedelta(days=int(days))) if days else None))
