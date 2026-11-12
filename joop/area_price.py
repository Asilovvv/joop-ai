"""Prices per square metre (cleaning): the code multiplies, the model only repeats the result.

A pack switches it on with ``features: [area_price]``. When the customer has named an area in the chat, the
prompt gets a ready estimate for every service priced «за м²», not lower than the service's minimal order.
Without an area the model is told to ask for it instead of doing arithmetic itself.
"""

from __future__ import annotations

import re

from sqlmodel import Session, select

from .models import Conversation, Message, Service

LOOK_BACK = 6  # customer messages searched for an area
MIN_AREA, MAX_AREA = 10, 2000  # m²; anything else is a typo or not an area
_UNIT = r"(?:м\s?²|м2|m2|кв\.?\s?м\w*|квадрат\w*|кв\b\.?|чарчы\s+метр\w*)"
_AREA = re.compile(rf"(?<![\d.,])(\d{{2,4}})\s*{_UNIT}", re.IGNORECASE)
_RATE = re.compile(rf"(от\s+)?(\d[\d  ]*)\s*(?:сом\w*\s*)?(?:за|/)\s*(?:1\s*)?{_UNIT}", re.IGNORECASE)
_MINIMUM = re.compile(r"минимальн\w+\s+(?:заказ|сумма|стоимость)\D{0,12}(\d[\d  ]*)", re.IGNORECASE)


def _int(digits: str) -> int:
    return int(re.sub(r"\D", "", digits))


def _som(value: int) -> str:
    return f"{value:,} сом".replace(",", " ")


def area_in(texts: list[str]) -> int | None:
    """The area the customer named last, newest message first; None when there is none in a sane range."""
    for text in texts:
        found = [int(m.group(1)) for m in _AREA.finditer(text or "")]
        found = [a for a in found if MIN_AREA <= a <= MAX_AREA]
        if found:
            return found[-1]
    return None


def estimate(service: Service, area: int) -> tuple[int, bool, int] | None:
    """(total, «от», minimal order used or 0) for a service priced per m²; None for any other price."""
    rate = _RATE.search(service.price or "")
    if not rate:
        return None
    total = _int(rate.group(2)) * area
    minimum = _MINIMUM.search(service.note or "")
    floor = _int(minimum.group(1)) if minimum else 0
    return max(total, floor), bool(rate.group(1)), floor if floor > total else 0


def prompt_hint(session: Session, conv: Conversation, services: list[Service], text: str) -> str:
    priced = [s for s in services if _RATE.search(s.price or "")]
    if not priced:
        return ""
    texts = [text]
    if conv.id is not None:
        texts += list(session.exec(select(Message.text).where(Message.conversation_id == conv.id, Message.role == "customer")
                                   .order_by(Message.id.desc()).limit(LOOK_BACK)).all())
    area = area_in(texts)
    if area is None:
        return ("\nСтоимость по цене за м² сам не считай и не умножай. Спроси площадь в квадратных метрах: "
                "система посчитает предварительную стоимость по прайсу.")
    lines = ["", f"Расчёт по площади {area} м² (посчитано системой по прайсу):"]
    for service in priced:
        total, at_least, floor = estimate(service, area)
        line = f"- {service.name}: {'от ' if at_least else ''}{_som(total)}"
        lines.append(line + (f" (минимальный заказ {_som(floor)})" if floor else ""))
    lines.append("Называй только эти суммы и только как предварительную стоимость; сам не умножай и не округляй. "
                 "Точную сумму подтверждает сотрудник на месте.")
    return "\n".join(lines)
