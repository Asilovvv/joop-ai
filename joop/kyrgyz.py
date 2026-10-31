"""Kyrgyz wording for the price list and the FAQ, drafted by the AI on the owner's request.

Evaluation runs 34-35 showed that the AI answers Kyrgyz customers better when a FAQ entry also has its
Kyrgyz wording, and runs 3-4 showed the same for service names. Owners rarely type these by hand, so the
panel offers one button: the AI fills the empty Kyrgyz fields in one call, and the owner checks them.
Filled fields are never overwritten; a suggestion that is not clean Kyrgyz Cyrillic is dropped.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from sqlmodel import Session, select

from .models import Business, Faq, Service
from .pricing import empty_usage

log = logging.getLogger(__name__)

MAX_ITEMS = 60  # one call; a longer list is filled by pressing the button again
MAX_LEN = 200

INSTRUCTION = """You translate short texts of a small business in Kyrgyzstan from Russian into Kyrgyz.
The input is a JSON array of strings: names of services or goods, and questions customers ask.
Return ONLY a JSON array of the same length, in the same order, each item the Kyrgyz translation of the
item at that position. Write natural Kyrgyz that a customer in Bishkek would use, in Kyrgyz Cyrillic
(letters ң, ө, ү are fine). No Kazakh letters such as і, ә, ғ, қ, ұ, һ. Keep numbers, units, sizes and
brand or product names written in Latin letters (iPhone, Wi-Fi, QR) exactly as they are. Output the array
once, with no explanations before or after it, no quotes around it and no markdown."""

_KAZAKH = re.compile("[іәғқұһІӘҒҚҰҺ]")
_LATIN_WORD = re.compile(r"[A-Za-z][A-Za-z\-]*")
_CYRILLIC = re.compile("[а-яёңөүА-ЯЁҢӨҮ]")


def _parse_list(text: str, size: int) -> list[Any] | None:
    """The last JSON array of `size` items in the answer: the model sometimes corrects itself
    ("Wait, here is the right output: [...]") after a first array."""
    found = None
    for match in re.finditer(r"\[[^\[\]]*\]", text or "", re.S):
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            continue
        if isinstance(data, list) and len(data) == size:
            found = data
    return found


def clean(source: str, suggestion: Any) -> str:
    """The suggestion if it looks like a usable Kyrgyz wording of `source`, else an empty string."""
    if not isinstance(suggestion, str):
        return ""
    text = " ".join(suggestion.split())
    if len(text) > 1 and text[0] in "\"'«" and text[-1] in "\"'»" and source.strip()[:1] not in "\"'«":
        text = text[1:-1].strip()  # quotes around the whole answer, not part of a name like «Лофт»
    if not text or len(text) > MAX_LEN or _KAZAKH.search(text) or not _CYRILLIC.search(text):
        return ""
    if text.lower() == source.strip().lower() and len(source.split()) > 3:
        return ""  # an untranslated sentence; short names (Лагман, Педикюр, ЭКГ) are the same in Kyrgyz
    allowed = {w.lower() for w in _LATIN_WORD.findall(source)}
    if any(w.lower() not in allowed for w in _LATIN_WORD.findall(text)):
        return ""  # Latin words the source did not have: not Kyrgyz Cyrillic
    return text


def suggest(llm: Any, texts: list[str], usage: dict | None = None, raw_answers: list | None = None) -> list[str] | None:
    """Kyrgyz wordings for `texts` ("" where a suggestion was unusable); None if both tries failed.

    A second try covers an answer that is not a JSON list of the right length. `raw_answers`, when given,
    collects the model's raw answers (for the evaluation report).
    """
    writer = getattr(llm, "write", None)
    if writer is None or not texts:
        return None
    usage = usage if usage is not None else empty_usage()
    for _ in range(2):
        raw = writer(INSTRUCTION, json.dumps(texts, ensure_ascii=False), usage)
        if raw_answers is not None:
            raw_answers.append(raw)
        data = _parse_list(raw or "", len(texts))
        if data is not None:
            return [clean(src, s) for src, s in zip(texts, data)]
        log.warning("Kyrgyz suggestions: unusable answer for %d items", len(texts))
    return None


@dataclass
class FillResult:
    filled: int  # fields that got a Kyrgyz wording
    skipped: int  # empty fields the AI could not fill cleanly
    left: int  # empty fields beyond this call's limit
    failed: bool = False


def empty_fields(session: Session, business: Business) -> list[Service | Faq]:
    services = session.exec(select(Service).where(Service.business_id == business.id, Service.name_ky == "").order_by(Service.sort, Service.id)).all()
    faqs = session.exec(select(Faq).where(Faq.business_id == business.id, Faq.question_ky == "").order_by(Faq.id)).all()
    return [*services, *faqs]


def fill_missing(session: Session, business: Business, llm: Any) -> FillResult:
    rows = empty_fields(session, business)
    batch, left = rows[:MAX_ITEMS], max(0, len(rows) - MAX_ITEMS)
    if not batch:
        return FillResult(0, 0, 0)
    texts = [r.name if isinstance(r, Service) else r.question for r in batch]
    try:
        out = suggest(llm, texts)
    except Exception:
        log.exception("Kyrgyz suggestions failed for %s", business.slug)
        out = None
    if out is None:
        return FillResult(0, 0, len(rows), failed=True)
    filled = 0
    for row, ky in zip(batch, out):
        if not ky:
            continue
        if isinstance(row, Service):
            row.name_ky = ky
        else:
            row.question_ky = ky
        session.add(row)
        filled += 1
    return FillResult(filled, len(batch) - filled, left)
