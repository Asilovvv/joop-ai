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
