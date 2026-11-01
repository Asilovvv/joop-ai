"""The price list and the FAQ drafted by the AI from text the owner already has.

Owners keep their prices in an Instagram post, a WhatsApp message or a page of their website; typing them
into the panel one by one is the slowest part of the setup. The owner pastes that text, the AI proposes
services and questions in one call, and the code keeps only what the text supports:

- a price is kept only if every number in it is written in the pasted text (otherwise the item stays,
  without a price, marked for the owner to fill);
- a service whose name has no word from the text, and a FAQ answer with a number the text does not have,
  are dropped;
- names already in the price list and questions already in the FAQ are shown as duplicates, unticked.

Nothing is saved until the owner checks the preview, edits it if needed and presses "Добавить".
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from .kyrgyz import clean as clean_kyrgyz
from .pricing import empty_usage

log = logging.getLogger(__name__)

MAX_SOURCE = 6000  # characters of pasted text in one call
MAX_SERVICES = 80
MAX_FAQ = 30

INSTRUCTION = """You read text that the owner of a small business in Kyrgyzstan pasted: a price list, an Instagram
post, a WhatsApp message or a page of their website, in Russian, Kyrgyz or both. Extract ONLY what the text states.
Return ONLY one JSON object, no markdown and no explanations:
{"services": [{"name": "...", "name_ky": "...", "price": "...", "note": "..."}],
 "faq": [{"question": "...", "answer": "..."}]}
services: every service or product with a price or offered by the business. "name" in Russian as written in the
text; "name_ky" only when the text itself gives the Kyrgyz name, else "". "price" exactly as written, for example
"1 500", "от 3 000", "300–500"; "" when the text gives no price. "note": duration or a short condition from the
text, else "".
faq: facts a customer may ask about and the text states: address, working hours, parking, payment methods,
delivery, guarantee, booking rules. "question" is a short customer question in Russian, "answer" uses only the
text's facts and numbers.
Never invent services, prices, hours or other facts. If the text has none, return empty arrays."""

_NUM = re.compile(r"\d(?:[\d\s  .,]*\d)?")
_WORD = re.compile(r"[a-zа-яёңөүәіқғұһ]{3,}", re.I)


def _numbers(text: str) -> set[str]:
    """Numbers as digit strings: "1 500", "1500" and "1.500" are the same number."""
    return {re.sub(r"\D", "", m) for m in _NUM.findall(text or "")}


def _source_numbers(text: str) -> set[str]:
    """Every way the pasted text can be read: "500 700" is two prices or one, "1 500" is 1500 or 1 and 500."""
    out: set[str] = set()
    for run in _NUM.findall(text or ""):
        parts = re.findall(r"\d+", run)
        out.update(parts)
        for i in range(len(parts)):
            merged = parts[i]
            for nxt in parts[i + 1:]:
                if len(nxt) != 3:
                    break
                merged += nxt
                out.add(merged)
    return out


def _fold(text: str) -> str:
    return (text or "").lower().replace("ё", "е")


def _numbers_ok(text: str, source_numbers: set[str]) -> bool:
    return _numbers(text) <= source_numbers


def _word_ok(text: str, source: str) -> bool:
    """At least one word of the name is in the source (by its first four letters: forms change endings)."""
    words = _WORD.findall(_fold(text))
    return not words or any(w[:4] in source for w in words)


def _all_words_ok(text: str, source: str) -> bool:
    """Every word is in the source: for a Kyrgyz name, which must be copied from the text, not translated."""
    return all(w[:4] in source for w in _WORD.findall(_fold(text)))


@dataclass
class Item:
    name: str
    name_ky: str = ""
    price: str = ""
    note: str = ""
    duplicate: bool = False
    price_dropped: bool = False  # the AI gave a price the text does not have: the owner fills it in


@dataclass
class QA:
    question: str
    answer: str
    duplicate: bool = False


@dataclass
class Proposal:
    services: list[Item] = field(default_factory=list)
    faq: list[QA] = field(default_factory=list)
    dropped: int = 0  # proposals removed because the text does not support them

    @property
    def empty(self) -> bool:
        return not self.services and not self.faq


def _s(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit] if isinstance(value, (str, int, float)) else ""


def parse(raw: str | None) -> dict | None:
    text = (raw or "").strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def check(data: dict, source: str, existing_names: list[str], existing_questions: list[str]) -> Proposal:
    """Keep what the pasted text supports; mark duplicates of what the business already has."""
    folded, nums = _fold(source), _source_numbers(source)
    have = {_fold(n).strip() for n in existing_names}
    asked = {_fold(q).strip() for q in existing_questions}
    out, seen = Proposal(), set()
    for row in (data.get("services") or [])[:MAX_SERVICES * 2]:
        if not isinstance(row, dict):
            continue
        name = _s(row.get("name"), 120)
        if not name or not re.search(r"[^\W\d_]", name) or not _word_ok(name, folded):
            out.dropped += 1
            continue
        key = _fold(name)
        if key in seen:
            continue
        seen.add(key)
        price, note = _s(row.get("price"), 40), _s(row.get("note"), 200)
        item = Item(name=name, note=note if _numbers_ok(note, nums) else "", duplicate=key in have)
        if price and not _numbers_ok(price, nums):
            item.price_dropped = True
        else:
            item.price = price
        ky = clean_kyrgyz(name, row.get("name_ky"))
        item.name_ky = ky if ky and _all_words_ok(ky, folded) else ""
        out.services.append(item)
        if len(out.services) >= MAX_SERVICES:
            break
    questions = set()
    for row in (data.get("faq") or [])[:MAX_FAQ * 2]:
        if not isinstance(row, dict):
            continue
        q, a = _s(row.get("question"), 200), _s(row.get("answer"), 500)
        if not q or not a or not _numbers_ok(a, nums):
            out.dropped += 1
            continue
        if _fold(q) in questions:
            continue
        questions.add(_fold(q))
        out.faq.append(QA(question=q, answer=a, duplicate=_fold(q).strip() in asked))
        if len(out.faq) >= MAX_FAQ:
            break
    return out


def propose(llm: Any, source: str, existing_names: list[str], existing_questions: list[str],
            usage: dict | None = None) -> Proposal | None:
    """One model call (a second one if the answer is not JSON); None when the AI did not answer."""
    writer = getattr(llm, "write", None)
    source = (source or "").strip()[:MAX_SOURCE]
    if writer is None or not source:
        return None
    usage = usage if usage is not None else empty_usage()
    for _ in range(2):
        data = parse(writer(INSTRUCTION, source, usage))
        if data is not None:
            return check(data, source, existing_names, existing_questions)
        log.warning("Autofill: the answer was not a JSON object")
    return None
