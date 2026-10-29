"""Catalog helpers shared by the panel, profile import and the engine."""

from __future__ import annotations

import re

_RANGE = re.compile(r"(^|\s)(от|до)(\s|$)|\d\s*[-–—]\s*\d", re.IGNORECASE)
_NUMBER = re.compile(r"\d[\d\s ]*")


def parse_price(text: str | None) -> int | None:
    """'3 000' -> 3000; '500 сом (демо-цена)' -> 500; 'от 3 500', '300–500', '' -> None.

    Only an exact single price can be used to compute an order total.
    """
    value = (text or "").strip()
    if not value or _RANGE.search(value):
        return None
    numbers = [n for n in (re.sub(r"\D", "", m) for m in _NUMBER.findall(value)) if n]
    return int(numbers[0]) if len(numbers) == 1 else None
