"""Creating a business, with optional demo data from its niche pack."""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Session, select

from .models import Business
from .niches import get_pack
from .profile import apply_profile, load_profile
from .security import hash_password, new_link_code, new_secret


class SlugTaken(ValueError):
    pass


def create_business(
    session: Session,
    *,
    slug: str,
    name: str,
    password: str,
    niche: str = "dental",
    demo: bool = False,
    now_utc: datetime | None = None,
) -> Business:
    slug = slug.strip().lower()
    if session.exec(select(Business).where(Business.slug == slug)).first():
        raise SlugTaken(slug)
    business = Business(
        slug=slug,
        name=name.strip(),
        niche=niche,
        admin_password_hash=hash_password(password),
        admin_link_code=new_link_code(),
        telegram_secret=new_secret(),
    )
    session.add(business)
    session.flush()
    if demo:
        apply_profile(session, business, load_profile(get_pack(niche).demo_file), now_utc=now_utc)
        business.name = name.strip() or business.name
    return business
