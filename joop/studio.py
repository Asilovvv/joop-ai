"""Joop Studio: AI drafts a one-page website for a small business from what the owner wrote.

The model returns only text, as JSON with a fixed set of fields. Our own template renders it,
so the model never writes HTML and cannot inject scripts or links into a page we host.
"""

from __future__ import annotations

import json
import re
from typing import Any

KINDS = {"site": "Сайт-визитка", "slides": "Презентация", "menu": "Меню или прайс", "other": "Другое"}
STATUSES = {"new": "Новая", "draft": "Черновик готов", "sent": "Отправлено клиенту", "paid": "Оплачено",
            "done": "Сдано", "lost": "Отказ"}

SITE_WRITER = """You write the text of a one-page website for a small business in Kyrgyzstan.
Use ONLY facts from the owner's description: never invent prices, addresses, phone numbers, awards,
years in business, reviews or numbers. If a fact is missing, leave that field empty.
Language: {language}. Plain text, no markdown, no HTML, no emoji.
Return only JSON with exactly these keys:
{{"headline": "<= 60 chars, what the business offers",
 "subheadline": "<= 140 chars, why choose it, from the description",
 "services": [{{"name": "...", "price": "as written by the owner or empty", "note": "short or empty"}}],
 "about": "2-3 sentences from the description",
 "address": "", "hours": "", "phone": "", "instagram": "",
 "cta": "<= 30 chars, e.g. Записаться / Заказать"}}
At most 12 services."""

FIELDS = ("headline", "subheadline", "about", "address", "hours", "phone", "instagram", "cta")
LIMITS = {"headline": 80, "subheadline": 200, "about": 900, "address": 200, "hours": 200, "phone": 40,
          "instagram": 60, "cta": 40}


def _clean(value: Any, limit: int) -> str:
    text = re.sub(r"[<>]", "", str(value or "")).strip()  # the template escapes too; keep stored text plain
    return text[:limit]


def parse_site(text: str) -> dict | None:
    """Model output -> validated site content, or None when it is not usable."""
    match = re.search(r"\{.*\}", text or "", re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    site = {k: _clean(data.get(k), LIMITS[k]) for k in FIELDS}
    services = []
    for item in (data.get("services") or [])[:12]:
        if isinstance(item, dict) and _clean(item.get("name"), 80):
            services.append({"name": _clean(item.get("name"), 80), "price": _clean(item.get("price"), 40),
                             "note": _clean(item.get("note"), 160)})
    site["services"] = services
    site["instagram"] = site["instagram"].lstrip("@").split("/")[-1]
    if not site["headline"]:
        return None
    return site


def draft_site(llm: Any, business_name: str, niche_label: str, description: str, contact_phone: str,
               language: str = "Russian") -> dict | None:
    writer = getattr(llm, "write", None)
    if writer is None:
        return None
    from .pricing import empty_usage

    facts = f"Business: {business_name}\nType: {niche_label}\nContact phone: {contact_phone}\nOwner's description:\n{description}"
    return parse_site(writer(SITE_WRITER.format(language=language), facts, empty_usage()) or "")


def phone_digits(phone: str) -> str:
    digits = re.sub(r"\D", "", phone or "")
    if digits.startswith("0") and len(digits) == 10:
        digits = "996" + digits[1:]
    return digits
