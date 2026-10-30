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
          "instagram": 60, "cta": 40, "booking_url": 200}
# The site's main button may lead only to a messenger chat, never to an arbitrary site.
BOOKING_URL = re.compile(r"^https://(t\.me|wa\.me|instagram\.com|ig\.me)/[A-Za-z0-9_./?=-]{1,150}$")


def clean_booking_url(value: str) -> str:
    value = (value or "").strip()
    return value if BOOKING_URL.match(value) else ""


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


def business_from_site(session, request, site: dict, password: str, now, trial_days: int):
    """Create a Joop AI company from a studio order: services, prices and contacts come from the site draft."""
    from . import billing
    from .catalog import parse_price
    from .models import Service
    from .presets import create_business
    from .web.saas import unique_slug

    b = create_business(session, slug=unique_slug(session, request.business_name), name=request.business_name,
                        password=password, niche=request.niche, demo=False, now_utc=now)
    b.phone = site.get("phone") or request.phone
    b.address = site.get("address", "")
    b.hours_text = site.get("hours", "")
    b.description = site.get("about", "")
    for i, item in enumerate(site.get("services", [])):
        session.add(Service(business_id=b.id, name=item["name"], price=item.get("price", ""),
                            price_value=parse_price(item.get("price")), note=item.get("note", ""), sort=i))
    session.add(b)
    billing.start_trial(session, b, days=trial_days, now=now, source="studio", contact_name=request.contact_name,
                        contact_phone=request.phone)
    request.business_id = b.id
    return b
