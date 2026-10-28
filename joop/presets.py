"""Creating a business, with optional demo data for a dental clinic."""

from __future__ import annotations

from datetime import datetime, time, timedelta

from sqlmodel import Session, select

from .models import Business, Faq, Service, Staff
from .security import hash_password, new_link_code, new_secret
from .slots import generate_slots
from .timeutil import local_now

# Demo content for a fictional clinic. Replace it with the real price list in the panel.
DENTAL_SERVICES = [
    ("Консультация и осмотр", "500", ""),
    ("Лечение кариеса (пломба)", "от 3 500", ""),
    ("Лечение каналов, 1 канал", "от 4 000", ""),
    ("Профессиональная чистка", "3 000", "ультразвук и Air Flow"),
    ("Удаление зуба простое", "2 000", ""),
    ("Удаление зуба мудрости", "от 5 000", ""),
    ("Имплант под ключ (имплант и коронка)", "от 65 000", "точная цена после снимка"),
    ("Коронка металлокерамика", "12 000", ""),
    ("Детский приём", "от 1 500", "с 3 лет"),
]
DENTAL_STAFF = [
    ("Айгерим Садыкова", "терапевт", "боль, кариес, пломбы, лечение каналов"),
    ("Нурлан Абдыкадыров", "хирург-имплантолог", "удаление зубов, импланты"),
    ("Элина Ким", "гигиенист, детский врач", "профессиональная чистка, дети"),
]
DENTAL_FAQ = [
    ("Есть ли парковка?", "Да, бесплатная парковка во дворе."),
    ("Как оплатить?", "Наличными, картой или по QR."),
    ("Принимаете детей?", "Да, с 3 лет, детский врач Элина Ким."),
]


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
        hours_text="Пн–Сб 09:00–19:00, воскресенье — выходной",
        admin_password_hash=hash_password(password),
        admin_link_code=new_link_code(),
        telegram_secret=new_secret(),
    )
    session.add(business)
    session.flush()
    if demo:
        _add_dental_demo(session, business, now_utc)
    return business


def _add_dental_demo(session: Session, business: Business, now_utc: datetime | None) -> None:
    business.address = "Бишкек, ул. Токтогула 120 (демо-адрес)"
    business.phone = "+996 555 000 000"
    for i, (service, price, note) in enumerate(DENTAL_SERVICES):
        session.add(Service(business_id=business.id, name=service, price=price, note=note, sort=i))
    for question, answer in DENTAL_FAQ:
        session.add(Faq(business_id=business.id, question=question, answer=answer))
    staff_rows = []
    for staff_name, role, handles in DENTAL_STAFF:
        member = Staff(business_id=business.id, name=staff_name, role=role, handles=handles)
        session.add(member)
        staff_rows.append(member)
    session.flush()
    today = local_now(business.timezone, now_utc).date()
    for member in staff_rows:
        generate_slots(
            session,
            business,
            member.id,
            today + timedelta(days=1),
            today + timedelta(days=7),
            time(9, 0),
            time(18, 0),
            60,
        )
