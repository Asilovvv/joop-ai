"""Database tables.

Times: ``*_at`` columns are naive UTC; ``Slot.start`` and ``Booking.start`` are naive local
time of the business. Every row belongs to one business (multi-tenant from day one).
"""

from __future__ import annotations

from typing import Optional

from pydantic import NaiveDatetime
from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

from .timeutil import utcnow


class Business(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    slug: str = Field(index=True, unique=True)
    name: str
    niche: str = "dental"
    description: str = ""
    tone: str = ""
    booking_policy: str = ""
    address: str = ""
    phone: str = ""
    hours_text: str = ""
    work_start: str = "09:00"
    work_end: str = "19:00"
    days_off: str = "7"  # ISO weekdays, comma separated: 1 = Monday ... 7 = Sunday
    timezone: str = "Asia/Bishkek"
    extra_rules: str = ""
    greeting: str = ""
    bot_enabled: bool = True
    reminder_hour: int = 18
    digest_hour: int = 8

    admin_password_hash: str = ""
    admin_link_code: str = ""
    admin_chat_ids: str = ""  # Telegram chat ids that receive notifications, comma separated

    telegram_bot_token: str = ""
    telegram_secret: str = ""
    wa_phone_number_id: str = Field(default="", index=True)
    wa_access_token: str = ""
    wa_reminder_template: str = ""
    wa_template_lang: str = "ru"
    ig_account_id: str = Field(default="", index=True)
    ig_access_token: str = ""
    ig_token_refreshed_at: Optional[NaiveDatetime] = None

    last_reminder_date: str = ""
    last_digest_date: str = ""
    created_at: NaiveDatetime = Field(default_factory=utcnow)


class Service(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    business_id: int = Field(foreign_key="business.id", index=True)
    name: str
    name_ky: str = ""  # Kyrgyz name, so the model does not translate service names on the fly
    price: str = ""  # free text, e.g. "от 3 500"
    price_value: Optional[int] = None  # exact price in som when the text is a single number; used for order totals
    note: str = ""
    category: str = ""
    available: bool = True  # False = stop list / sold out: the AI does not offer it
    sort: int = 0


class Staff(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    business_id: int = Field(foreign_key="business.id", index=True)
    name: str
    role: str = ""
    handles: str = ""  # what this person takes care of, used to pick the right specialist
    capacity: int = 0  # seats for a table, 0 = not relevant
    active: bool = True


class Faq(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    business_id: int = Field(foreign_key="business.id", index=True)
    question: str
    answer: str


class Slot(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    business_id: int = Field(foreign_key="business.id", index=True)
    staff_id: int = Field(foreign_key="staff.id", index=True)
    start: NaiveDatetime = Field(index=True)
    duration_min: int = 60
    status: str = "free"  # free | booked


class Conversation(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("business_id", "channel", "chat_id"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    business_id: int = Field(foreign_key="business.id", index=True)
    channel: str  # telegram | whatsapp | instagram
    chat_id: str
    display_name: str = ""
    customer_name: str = ""
    customer_phone: str = ""
    ai_paused_until: Optional[NaiveDatetime] = None
    last_customer_at: Optional[NaiveDatetime] = None
    last_message_at: NaiveDatetime = Field(default_factory=utcnow)
    created_at: NaiveDatetime = Field(default_factory=utcnow)


class Message(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    business_id: int = Field(foreign_key="business.id", index=True)
    conversation_id: int = Field(foreign_key="conversation.id", index=True)
    role: str  # customer | ai | staff
    text: str
    created_at: NaiveDatetime = Field(default_factory=utcnow, index=True)
    off_hours: bool = False
    external_id: str = Field(default="", index=True)
    # Claude usage for AI replies (thinking tokens count as output)
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    language_fixed: bool = False


class Booking(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    business_id: int = Field(foreign_key="business.id", index=True)
    slot_id: Optional[int] = Field(default=None, foreign_key="slot.id")
    conversation_id: Optional[int] = Field(default=None, foreign_key="conversation.id")
    staff_id: Optional[int] = Field(default=None, foreign_key="staff.id")
    staff_name: str = ""
    start: NaiveDatetime = Field(index=True)
    service: str = ""
    party_size: int = 0
    customer_name: str = ""
    customer_phone: str = ""
    channel: str = ""
    chat_id: str = ""
    status: str = "booked"  # booked | cancelled
    source: str = "ai"
    created_at: NaiveDatetime = Field(default_factory=utcnow)
    created_off_hours: bool = False
    reminder_status: str = ""  # "" | sent | manual | failed


class Lead(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    business_id: int = Field(foreign_key="business.id", index=True)
    conversation_id: Optional[int] = Field(default=None, foreign_key="conversation.id")
    kind: str = "handoff"  # handoff | request (booking without a slot) | lead (qualified) | media | error
    summary: str = ""
    details: str = ""  # qualification answers for kind="lead", e.g. "Бюджет: 60 000 $; Район: Джал"
    customer_name: str = ""
    customer_phone: str = ""
    channel: str = ""
    chat_id: str = ""
    status: str = "new"  # new | done
    created_at: NaiveDatetime = Field(default_factory=utcnow)
    off_hours: bool = False


class Order(SQLModel, table=True):
    """A cart the AI collected (cafe, wholesale). Totals are computed by code from catalog prices."""

    id: Optional[int] = Field(default=None, primary_key=True)
    business_id: int = Field(foreign_key="business.id", index=True)
    conversation_id: Optional[int] = Field(default=None, foreign_key="conversation.id")
    customer_name: str = ""
    customer_phone: str = ""
    mode: str = "pickup"  # pickup | delivery
    address: str = ""
    wanted_time: str = ""
    comment: str = ""
    total: Optional[int] = None  # None when some price is not exact ("от ...")
    status: str = "new"  # new | accepted | done | cancelled
    channel: str = ""
    chat_id: str = ""
    created_at: NaiveDatetime = Field(default_factory=utcnow)
    created_off_hours: bool = False


class OrderLine(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    order_id: int = Field(foreign_key="order.id", index=True)
    item_id: Optional[int] = Field(default=None, foreign_key="service.id")
    name: str
    quantity: int = 1
    unit_price: Optional[int] = None
    note: str = ""
