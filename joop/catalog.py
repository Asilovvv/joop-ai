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


CATALOG_PROMPT_LIMIT = 80  # above this, the prompt gets only items relevant to the conversation
RELEVANT_LIMIT = 40
_WORD = re.compile(r"[a-zа-яёңөү0-9]{3,}", re.IGNORECASE)


def _stems(text: str) -> set[str]:
    return {w.lower()[:5] for w in _WORD.findall(text or "")}


def select_relevant(items: list, texts: list[str], limit: int = RELEVANT_LIMIT) -> list:
    """Pick catalog items that share word stems with the recent customer messages.

    A cheap keyword match, no model call. Items keep their catalog order; when nothing matches, the
    first `limit` items are returned so the model still sees typical positions.
    """
    wanted = set().union(*(_stems(t) for t in texts)) if texts else set()
    scored = []
    for index, item in enumerate(items):
        words = _stems(" ".join(filter(None, [item.name, item.name_ky, item.category, item.note])))
        score = len(words & wanted)
        if score:
            scored.append((-score, index, item))
    if not scored:
        return list(items[:limit])
    best = sorted(scored)[:limit]
    return [item for _, _, item in sorted(best, key=lambda x: x[1])]
