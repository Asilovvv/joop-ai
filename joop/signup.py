"""A new business signs itself up: on the site (/signup, joop/web/saas.py) or in the app (/api/mobile/signup).

One way for both, so a business made in the app is the one made on the site: the niche's sample price list and hours
(flagged as an example until changed: samples.py), no fake address, phone or terms that would reach real customers,
a trial, the referring partner.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime

from sqlmodel import Session

from . import billing, partners
from .models import Business
from .niches import all_packs
from .presets import SlugTaken, create_business

log = logging.getLogger(__name__)


class Refused(Exception):
    """The sign-up cannot be made; the message is for the person signing up."""


def register(session: Session, *, slug: str, name: str, niche: str, phone: str, password: str, trial_days: int,
             now: datetime, contact_name: str = "", source: str = "signup", ref: str = "") -> Business:
    """Create the business with its trial; the caller commits. `slug` comes from saas.unique_slug."""
    name, phone = name.strip()[:120], phone.strip()[:40]
    if len(name) < 2 or len(password) < 8 or len(re.sub(r"\D", "", phone)) < 9:
        raise Refused("Укажите название, телефон и пароль не короче 8 символов.")
    if niche not in all_packs():
        niche = "other"
    try:
        business = create_business(session, slug=slug, name=name, password=password, niche=niche, demo=True, now_utc=now)
    except SlugTaken:
        raise Refused("Не получилось создать компанию, попробуйте ещё раз.") from None
    # The demo profile brings a sample price list and hours (flagged until changed: samples.hours_are_example); its
    # address, phone and terms are fake and would reach real customers as fact, so they start empty.
    business.address = ""
    business.phone = phone
    business.description = business.booking_policy = ""
    business.min_order = business.delivery_fee = business.free_delivery_from = 0
    billing.start_trial(session, business, trial_days, now, source, contact_name.strip()[:120], phone)
    partner = partners.find_active(session, ref)
    if partner is not None:
        partners.attach(session, business.id, partner)
    session.add(business)
    log.info("New sign-up: %s (%s, %s)", business.slug, niche, source)
    return business
