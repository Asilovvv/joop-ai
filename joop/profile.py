"""Business profiles in YAML: a quick way to load a client's price list, FAQ and rules.

Format (see business.dental.example.yaml): name, description, address, hours, phone, services
[{name, name_ky, price, duration, note}], faq [{q, a}], booking_policy, tone, rules [...].
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from sqlmodel import Session, select

from .models import Business, Faq, Service


NICHES = {"dental", "beauty", "auto", "education", "other"}


class ProfileError(ValueError):
    pass


def load_profile(path: str | Path) -> dict[str, Any]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict) or not str(data.get("name") or "").strip():
        raise ProfileError("Business profile must have a 'name'")
    return data


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def apply_profile(session: Session, business: Business, data: dict[str, Any], replace: bool = True) -> None:
    """Copy a profile into a business. With replace=True the old price list and FAQ are removed."""
    business.name = _text(data.get("name")) or business.name
    if _text(data.get("niche")) in NICHES:
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
        session.add(
            Service(
                business_id=business.id,
                name=name,
                name_ky=_text(item.get("name_ky")),
                price=_text(item.get("price")),
                note="; ".join(notes),
                sort=i,
            )
        )
    for item in data.get("faq") or []:
        q, a = _text(item.get("q")), _text(item.get("a"))
        if q and a:
            session.add(Faq(business_id=business.id, question=q, answer=a))
