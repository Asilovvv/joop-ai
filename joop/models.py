"""Database tables.

Times: ``*_at`` columns are naive UTC; ``Slot.start`` and ``Booking.start`` are naive local
time of the business. Every row belongs to one business (multi-tenant from day one).
"""

from __future__ import annotations

from datetime import date as date_type
from typing import Optional

from pydantic import NaiveDatetime
from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

from .crypto import EncryptedString
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
    # Orders (cafes, wholesale), in som. 0 = not set.
    min_order: int = 0
    delivery_fee: int = 0
    free_delivery_from: int = 0

    admin_password_hash: str = ""
    admin_link_code: str = ""
    admin_chat_ids: str = ""  # Telegram chat ids that receive notifications, comma separated

    telegram_bot_token: str = Field(default="", sa_type=EncryptedString)  # encrypted at rest (joop/crypto.py)
    telegram_secret: str = ""
    wa_phone_number_id: str = Field(default="", index=True)
    wa_access_token: str = Field(default="", sa_type=EncryptedString)  # encrypted at rest (joop/crypto.py)
    wa_reminder_template: str = ""
    wa_template_lang: str = "ru"
    ig_account_id: str = Field(default="", index=True)
    ig_access_token: str = Field(default="", sa_type=EncryptedString)  # encrypted at rest (joop/crypto.py)
    ig_token_refreshed_at: Optional[NaiveDatetime] = None

    # After-visit follow-ups (joop/followups.py): ask for a rating, invite back when it is time again
    review_requests: bool = False
    review_url: str = ""  # 2GIS / Google Maps page where happy customers leave a review
    return_invites: bool = False
    intake_questions: str = ""  # asked right after a booking, one per line (joop/intake.py)
    loyalty_every: int = 0  # every N-th visit gets loyalty_reward (0 = off)
    loyalty_reward: str = ""

    # Public menu / price list /m/<slug> with QR codes (joop/web/menu.py)
    menu_enabled: bool = False
    menu_chat_url: str = ""  # where "Заказать" leads: t.me / wa.me / instagram link

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
    repeat_days: int = 0  # invite the customer back this many days after the visit (0 = never)


class Staff(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    business_id: int = Field(foreign_key="business.id", index=True)
    name: str
    role: str = ""
    handles: str = ""  # what this person takes care of, used to pick the right specialist
    capacity: int = 0  # seats for a table, 0 = not relevant
    group_size: int = 0  # group class: how many people one slot takes (0 or 1 = one booking per slot)
    active: bool = True


class Faq(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    business_id: int = Field(foreign_key="business.id", index=True)
    question: str
    question_ky: str = ""  # the same question in Kyrgyz: helps the AI match Kyrgyz customers' wording
    answer: str
    source_lead_id: Optional[int] = None  # the handoff this entry answers (joop/faq_gaps.py), so it leaves the list


class Slot(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    business_id: int = Field(foreign_key="business.id", index=True)
    staff_id: int = Field(foreign_key="staff.id", index=True)
    start: NaiveDatetime = Field(index=True)
    duration_min: int = 60
    status: str = "free"  # free | booked (full or closed by staff)
    seats: int = 1  # bookings this slot takes: 1, or the group size for group classes
    taken: int = 0  # seats already booked


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
    review_status: str = ""  # "" | asked | rated | skipped
    review_asked_at: Optional[NaiveDatetime] = None
    rating: Optional[int] = None  # 1-5 from the customer after the visit
    return_status: str = ""  # "" | sent | manual: invitation to come again
    intake_status: str = ""  # "" | asked | answered
    intake_answers: str = ""
    loyalty_visit: int = 0  # this was the customer's N-th visit and earned the reward


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
    total: Optional[int] = None  # items + delivery; None when some price is not exact ("от ...")
    delivery_fee: int = 0
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


# --- SaaS: self-serve sign-up, billing and the founder's sales pipeline --------------------------


class Subscription(SQLModel, table=True):
    """One per business that signed up by itself or was created from the owner console.
    A business without a row (created from the command line) is never blocked."""

    id: Optional[int] = Field(default=None, primary_key=True)
    business_id: int = Field(foreign_key="business.id", unique=True, index=True)
    status: str = "trial"  # trial | active | suspended
    price_som: int = 0  # monthly price agreed with this business; 0 = the default price from settings
    trial_ends_at: Optional[NaiveDatetime] = None
    paid_until: Optional[NaiveDatetime] = None
    contact_name: str = ""
    contact_phone: str = ""
    source: str = "signup"  # signup | owner | prospect
    note: str = ""  # the founder's private note
    created_at: NaiveDatetime = Field(default_factory=utcnow)


class Payment(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    business_id: int = Field(foreign_key="business.id", index=True)
    amount_som: int
    method: str = "manual"  # manual | freedompay
    status: str = "pending"  # pending | paid | failed
    period_days: int = 30
    provider_payment_id: str = Field(default="", index=True)
    created_at: NaiveDatetime = Field(default_factory=utcnow)
    paid_at: Optional[NaiveDatetime] = None


class Prospect(SQLModel, table=True):
    """A business the founder wants to sell to. Not tenant data: only the owner console sees it."""

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    niche: str = "other"
    city: str = "Бишкек"
    contact_name: str = ""
    phone: str = ""
    instagram: str = ""
    notes: str = ""
    language: str = "ru"  # ru | ky: language of the first message
    status: str = "new"  # new | contacted | replied | demo | trial | paid | lost
    message: str = ""  # AI draft of the first message; the founder edits and sends it himself
    demo_business_id: Optional[int] = Field(default=None, foreign_key="business.id")
    next_step_at: Optional[NaiveDatetime] = None
    created_at: NaiveDatetime = Field(default_factory=utcnow)
    updated_at: NaiveDatetime = Field(default_factory=utcnow)


class Partner(SQLModel, table=True):
    """Someone who brings businesses (an SMM specialist, an agency) and earns a share of their payments."""

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    phone: str = ""
    code: str = Field(index=True, unique=True)  # public: goes into the sign-up link ?ref=code
    secret: str = Field(index=True, unique=True)  # private: the partner's own stats page /partner/<secret>
    percent: int = 20  # share of every payment by a referred business
    active: bool = True
    created_at: NaiveDatetime = Field(default_factory=utcnow)


class Referral(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    business_id: int = Field(foreign_key="business.id", unique=True, index=True)
    partner_id: int = Field(foreign_key="partner.id", index=True)
    created_at: NaiveDatetime = Field(default_factory=utcnow)


class PartnerPayout(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    partner_id: int = Field(foreign_key="partner.id", index=True)
    amount_som: int
    note: str = ""
    created_at: NaiveDatetime = Field(default_factory=utcnow)


class StudioRequest(SQLModel, table=True):
    """A business asks Joop Studio for a website, slides or a menu; AI drafts it, the founder checks and delivers."""

    id: Optional[int] = Field(default=None, primary_key=True)
    kind: str = "site"  # site | slides | menu | other
    business_name: str
    contact_name: str = ""
    phone: str = ""
    niche: str = "other"
    description: str = ""  # what the customer wrote: services, prices, address, wishes
    status: str = "new"  # new | draft | sent | paid | done | lost
    price_som: int = 0
    content_json: str = ""  # AI draft of the site's text, as JSON; rendered by our own template
    public_slug: Optional[str] = Field(default=None, index=True, unique=True)
    published: bool = False
    source: str = "form"  # form | prospect
    business_id: Optional[int] = Field(default=None, foreign_key="business.id")  # Joop AI company made from this order
    created_at: NaiveDatetime = Field(default_factory=utcnow)
    updated_at: NaiveDatetime = Field(default_factory=utcnow)


class PlacementTest(SQLModel, table=True):
    """A training centre's level test. Questions come from the school; answers are graded by code."""

    id: Optional[int] = Field(default=None, primary_key=True)
    business_id: int = Field(foreign_key="business.id", index=True)
    code: str = Field(index=True, unique=True)  # public link /test/<code>
    title: str
    scale_text: str = ""  # one band per line: "0-10 A1"
    minutes: int = 20  # time limit, 0 = none
    active: bool = True
    created_at: NaiveDatetime = Field(default_factory=utcnow)


class PlacementQuestion(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    business_id: int = Field(foreign_key="business.id", index=True)
    test_id: int = Field(foreign_key="placementtest.id", index=True)
    section: str = ""
    text: str
    options_json: str = "[]"  # list of answer options
    correct: int = 0  # index of the right option
    sort: int = 0


class PlacementAttempt(SQLModel, table=True):
    """One person's test. 'invited' = the AI gave a personal link in a chat; the result goes back to that chat."""

    id: Optional[int] = Field(default=None, primary_key=True)
    business_id: int = Field(foreign_key="business.id", index=True)
    test_id: int = Field(foreign_key="placementtest.id", index=True)
    token: str = Field(index=True, unique=True)  # personal link /t/<token>
    conversation_id: Optional[int] = Field(default=None, foreign_key="conversation.id", index=True)
    status: str = "invited"  # invited | started | finished
    name: str = ""
    phone: str = ""
    consent: bool = False
    answers_json: str = ""
    sections_json: str = ""  # {"Грамматика": [right, total], ...}
    score: int = 0
    max_score: int = 0
    level: str = ""
    late: bool = False  # submitted after the time limit
    result_sent: bool = False  # the result reached the customer's chat
    started_at: Optional[NaiveDatetime] = None
    finished_at: Optional[NaiveDatetime] = None
    created_at: NaiveDatetime = Field(default_factory=utcnow)


class WaitlistEntry(SQLModel, table=True):
    """A customer who wanted a time that was not free. Told first when a slot on that day frees up."""

    id: Optional[int] = Field(default=None, primary_key=True)
    business_id: int = Field(foreign_key="business.id", index=True)
    conversation_id: Optional[int] = Field(default=None, foreign_key="conversation.id")
    lead_id: Optional[int] = Field(default=None, foreign_key="lead.id")
    day: Optional[date_type] = None  # the day the customer wanted; None = any day soon
    service: str = ""
    customer_name: str = ""
    customer_phone: str = ""
    channel: str = ""
    chat_id: str = ""
    status: str = "waiting"  # waiting | notified | booked | cancelled
    notified_at: Optional[NaiveDatetime] = None
    created_at: NaiveDatetime = Field(default_factory=utcnow, index=True)


class Membership(SQLModel, table=True):
    """A pass or a package of visits ("10 занятий", "5 массажей") that staff sold to a customer."""

    id: Optional[int] = Field(default=None, primary_key=True)
    business_id: int = Field(foreign_key="business.id", index=True)
    customer_name: str = ""
    phone_key: str = Field(default="", index=True)  # last 9 digits of the phone, to match chats
    customer_phone: str = ""
    title: str
    visits_total: int = 0  # 0 = unlimited for the period
    visits_used: int = 0
    valid_until: Optional[date_type] = None
    active: bool = True
    created_at: NaiveDatetime = Field(default_factory=utcnow)


class Job(SQLModel, table=True):
    """An item left for work: dry cleaning, a phone repair, tailoring, a car at the service station.
    The customer asks "готово?" in a chat and the AI answers from here."""

    id: Optional[int] = Field(default=None, primary_key=True)
    business_id: int = Field(foreign_key="business.id", index=True)
    number: str = Field(index=True)  # receipt number the customer was given
    customer_name: str = ""
    customer_phone: str = ""
    phone_key: str = Field(default="", index=True)  # last 9 digits
    item: str  # what was left and what to do: "Пальто, химчистка"
    status: str = "accepted"  # accepted | in_progress | ready | issued | cancelled
    price: str = ""
    ready_by: Optional[date_type] = None
    note: str = ""  # shown to the customer, e.g. "ждём запчасть"
    conversation_id: Optional[int] = Field(default=None, foreign_key="conversation.id")
    ready_notified: bool = False
    created_at: NaiveDatetime = Field(default_factory=utcnow)
    updated_at: NaiveDatetime = Field(default_factory=utcnow)


class Stay(SQLModel, table=True):
    """A hotel booking for nights [check_in, check_out) in one room of a room type (a Staff row whose
    group_size is the number of such rooms and capacity the guests per room)."""

    id: Optional[int] = Field(default=None, primary_key=True)
    business_id: int = Field(foreign_key="business.id", index=True)
    staff_id: int = Field(foreign_key="staff.id", index=True)
    room_name: str = ""
    check_in: date_type = Field(index=True)
    check_out: date_type
    guests: int = 1
    customer_name: str = ""
    customer_phone: str = ""
    conversation_id: Optional[int] = Field(default=None, foreign_key="conversation.id")
    channel: str = ""
    chat_id: str = ""
    status: str = "booked"  # booked | cancelled
    source: str = "ai"
    created_off_hours: bool = False
    created_at: NaiveDatetime = Field(default_factory=utcnow)


class RoomNight(SQLModel, table=True):
    """One room unit taken for one night. The unique key makes double booking impossible."""

    __table_args__ = (UniqueConstraint("staff_id", "night", "unit"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    business_id: int = Field(foreign_key="business.id", index=True)
    staff_id: int = Field(foreign_key="staff.id", index=True)
    stay_id: int = Field(foreign_key="stay.id", index=True)
    night: date_type = Field(index=True)
    unit: int = 0
