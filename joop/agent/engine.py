"""Reply engine: one incoming message in, one reply plus side effects out.

Side effects stay in the database session passed in (messages, bookings, leads). Sending the reply
and the admin notifications happens in ``dispatch.py``, after the caller commits.
"""

from __future__ import annotations

import hmac
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable

from sqlmodel import Session, select

from ..billing import access_ok
from ..catalog import CATALOG_PROMPT_LIMIT, select_relevant
from ..channels.base import IncomingMessage
from ..lang import claims_confirmation, drop_claim_sentences, fix_mixed_script, is_kyrgyz_message, looks_kyrgyz, use_kyrgyz_names
from ..models import Booking, Business, Conversation, Faq, Lead, Message, Order, OrderLine, Service, Slot, Staff
from ..niches import Pack, get_pack
from ..phone import normalize_phone
from ..pricing import cost_usd, empty_usage
from ..slots import claim_slot, free_slots, requested_time, seats_left, seats_needed
from ..timeutil import fmt_slot, is_off_hours, utc_to_local, utcnow
from .llm import AgentReply, LLMClient, response_schema
from .. import placement
from ..followups import capture_rating
from .. import memberships, waitlist
from .prompt import CHANNEL_LABELS, build_history, build_system_prompt

log = logging.getLogger(__name__)

HISTORY_LIMIT = 20
HISTORY_WINDOW = timedelta(hours=72)
STAFF_TAKEOVER_PAUSE = timedelta(hours=12)

# Fixed replies sent without the model: both languages, since we do not know which one the customer reads.
# The Kyrgyz lines should be checked by a native speaker.
TEXT_ONLY_REPLY = (
    "Азырынча текст билдирүүлөрдү гана түшүнөм. Сураныч, текст менен жазыңыз.\n"
    "Я пока понимаю только текстовые сообщения. Напишите, пожалуйста, текстом — и я сразу помогу с записью."
)
ERROR_REPLY = (
    "Кечиресиз, азыр жооп бере албай жатам. Администратор жакында жооп берет.\n"
    "Извините, сейчас не получается ответить. Я передал ваше сообщение администратору, с вами свяжутся."
)
ASK_CONTACTS_REPLY = (
    "Чтобы записать вас, напишите, пожалуйста, имя и номер телефона, например: Айбек, 0555 123 456."
)
DEFAULT_GREETING = (
    "Здравствуйте! Это администратор «{name}». Напишите, что беспокоит или на какую услугу хотите "
    "записаться, — подберу удобное время."
)


@dataclass
class Outcome:
    reply: str | None = None
    admin_notes: list[str] = field(default_factory=list)
    booking_id: int | None = None
    request_id: int | None = None  # booking request without a slot (Lead of kind "request")
    lead_id: int | None = None  # handoff, media or error lead
    order_id: int | None = None
    qualified_lead_id: int | None = None  # Lead of kind "lead"
    skipped: str = ""  # why nothing was sent, for logs and tests
    language_fixed: bool = False
    confirmation_fixed: bool = False  # the reply claimed a booking that was not made and was rewritten
    usage: dict = field(default_factory=empty_usage)
    cost_usd: float | None = None


def handle_incoming(
    session: Session,
    business: Business,
    incoming: IncomingMessage,
    get_llm: Callable[[], LLMClient],
    now_utc: datetime | None = None,
    base_url: str = "",
) -> Outcome:
    now = now_utc or utcnow()
    now_local = utc_to_local(now, business.timezone)
    off = is_off_hours(now_local, business.work_start, business.work_end, business.days_off)

    if incoming.external_id and _already_seen(session, business.id, incoming.external_id):
        return Outcome(skipped="duplicate")

    conv = _get_or_create_conversation(session, business, incoming, now)

    if incoming.kind == "echo":
        return _handle_echo(session, business, conv, incoming, now, off)

    text = (incoming.text or "").strip()
    stored = text
    if incoming.kind == "media":
        stored = f"[{incoming.media_label or 'вложение'}]" + (f" {text}" if text else "")
    _add_message(session, business, conv, "customer", stored, now, off, incoming.external_id)
    conv.last_customer_at = now
    if incoming.user_name and not conv.display_name:
        conv.display_name = incoming.user_name[:120]

    if incoming.kind == "command":
        handled = _handle_command(session, business, conv, incoming, text, now, off)
        if handled is not None:
            return handled

    if not business.bot_enabled:
        return Outcome(skipped="bot_disabled")
    if not access_ok(session, business.id, now):
        return Outcome(skipped="subscription")  # trial over or not paid: staff answer by hand
    if conv.ai_paused_until and conv.ai_paused_until > now:
        return Outcome(skipped="paused")

    if incoming.kind == "media":
        label = incoming.media_label or "вложение"
        lead = _add_lead(session, business, conv, "media", f"Клиент прислал: {label}. Нужно ответить вручную.", now, off)
        _add_message(session, business, conv, "ai", TEXT_ONLY_REPLY, now, off)
        return Outcome(reply=TEXT_ONLY_REPLY, admin_notes=[_lead_note(business, conv, lead, off)], lead_id=lead.id)

    if not text:
        return Outcome(skipped="empty")

    rated = capture_rating(session, business, conv, text, now, off)
    if rated is not None:  # "5" right after "оцените визит от 1 до 5"
        _add_message(session, business, conv, "ai", rated.reply, now, off)
        return Outcome(reply=rated.reply, admin_notes=[rated.admin_note] if rated.admin_note else [], lead_id=rated.lead_id)

    services = list(session.exec(select(Service).where(Service.business_id == business.id).order_by(Service.sort, Service.id)).all())
    services, catalog_hint = _catalog_for_prompt(session, conv, services, text)
    staff = session.exec(select(Staff).where(Staff.business_id == business.id).order_by(Staff.id)).all()
    faqs = session.exec(select(Faq).where(Faq.business_id == business.id).order_by(Faq.id)).all()
    slots = free_slots(session, business.id, now_local)
    system = build_system_prompt(
        business=business,
        services=services,
        staff=staff,
        faqs=faqs,
        slots=slots,
        now_local=now_local,
        conversation=conv,
        channel=incoming.channel,
        catalog_hint=catalog_hint,
        extra_facts=_requested_slot_hint(session, conv, slots, now_local, now)
        + placement.prompt_hint(session, business, conv, base_url)
        + (memberships.prompt_hint(session, business, conv, now_local) if pack_offers(business, "memberships") else ""),
    )
    history = _history(session, conv, now)

    try:
        llm = get_llm()
        pack = get_pack(business.niche)
        result: AgentReply = llm.respond(system, history, schema=response_schema(pack.outcomes))
    except Exception:
        log.exception("Model call failed for business %s", business.slug)
        lead = _add_lead(session, business, conv, "error", f"ИИ не смог ответить на сообщение: «{text[:300]}»", now, off)
        _add_message(session, business, conv, "ai", ERROR_REPLY, now, off)
        return Outcome(reply=ERROR_REPLY, admin_notes=[_lead_note(business, conv, lead, off)], lead_id=lead.id)

    outcome = Outcome(reply=result.reply, usage=dict(result.usage))
    # The model may only use outcomes the niche enables; anything else is ignored.
    if result.booking and not (pack.has("booking") or pack.has("request")):
        result.booking = None
    if result.booking and result.booking.get("slot_id") is not None and not pack.has("booking"):
        result.booking["slot_id"] = None
    if result.order and pack.has("order"):
        outcome.reply, order = _try_order(session, business, pack, conv, result.order, result.reply, now, off, incoming.channel)
        if order is not None:
            outcome.order_id = order.id
            outcome.admin_notes.append(_order_note(session, conv, order, off))
    if result.lead and pack.has("lead"):
        outcome.reply, qualified = _qualified_lead(session, business, conv, result.lead, outcome.reply, now, off)
        if qualified is not None:
            outcome.qualified_lead_id = qualified.id
            outcome.admin_notes.append(_lead_note(business, conv, qualified, off))
    if result.booking:
        if result.booking.get("slot_id") is None:
            outcome.reply, request = _booking_request(session, business, conv, result.booking, result.reply, now, off)
            if request is not None:
                outcome.request_id = request.id
                if waitlist.add_entry(session, business, conv, request, result.booking, now, text) is not None:
                    outcome.reply += waitlist.waiting_line(is_kyrgyz_message(text))
                outcome.admin_notes.append(_request_note(conv, request, off))
        else:
            outcome.reply, booking = _try_booking(
                session, business, conv, result.booking, result.reply, now, now_local, off, incoming.channel, pack
            )
            if booking is not None:
                outcome.booking_id = booking.id
                waitlist.mark_booked(session, conv.id)
                outcome.admin_notes.append(_booking_note(business, booking, off))
    if result.handoff:
        lead = _add_lead(session, business, conv, "handoff", result.handoff, now, off)
        outcome.lead_id = lead.id
        outcome.admin_notes.append(_lead_note(business, conv, lead, off))

    # Confirmation guard: the model sometimes says "вы записаны" / "кабыл алдым" while it is still asking
    # for a phone number or a time. Nothing was captured, so rewrite the reply once without the claim.
    captured = any(x is not None for x in (outcome.booking_id, outcome.request_id, outcome.order_id, outcome.qualified_lead_id))
    if outcome.reply and not captured and claims_confirmation(outcome.reply) and not _has_capture(session, conv):
        fixed = llm.remove_false_confirmation(outcome.reply, outcome.usage)
        if not fixed or claims_confirmation(fixed):
            fixed = drop_claim_sentences(fixed or "") or drop_claim_sentences(outcome.reply)
        if fixed and not claims_confirmation(fixed):
            outcome.reply = fixed
            outcome.confirmation_fixed = True

    # Language guard: a Kyrgyz message sometimes gets a Russian answer because the business data
    # is in Russian. Rewrite such a reply once; keep the draft if the rewrite is not Kyrgyz either.
    if outcome.reply and is_kyrgyz_message(text) and not looks_kyrgyz(outcome.reply):
        rewritten = llm.rewrite_in_kyrgyz(outcome.reply, outcome.usage)
        if rewritten and looks_kyrgyz(rewritten):
            outcome.reply = rewritten
            outcome.language_fixed = True
    # Cheap fixes without a model call: Latin look-alike letters inside Cyrillic words, and Russian
    # service names left in a Kyrgyz reply.
    if outcome.reply:
        outcome.reply = fix_mixed_script(outcome.reply)
        if is_kyrgyz_message(text) and looks_kyrgyz(outcome.reply):
            outcome.reply = use_kyrgyz_names(outcome.reply, {sv.name: sv.name_ky for sv in services if sv.name_ky})

    outcome.cost_usd = cost_usd(outcome.usage, getattr(llm, "model", ""))
    if outcome.reply:
        msg = _add_message(session, business, conv, "ai", outcome.reply, now, off)
        msg.input_tokens = outcome.usage.get("input_tokens", 0) + outcome.usage.get("cache_read_input_tokens", 0)
        msg.output_tokens = outcome.usage.get("output_tokens", 0)
        msg.cost_usd = outcome.cost_usd or 0.0
        msg.language_fixed = outcome.language_fixed
    return outcome


# --- helpers -----------------------------------------------------------------------------------


def _has_capture(session: Session, conv: Conversation) -> bool:
    """Did this conversation already produce a booking, request, lead or order (so "вы записаны" may be true)?"""
    if session.exec(select(Booking.id).where(Booking.conversation_id == conv.id, Booking.status == "booked")).first():
        return True
    if session.exec(select(Order.id).where(Order.conversation_id == conv.id)).first():
        return True
    return session.exec(select(Lead.id).where(Lead.conversation_id == conv.id, Lead.kind.in_(["request", "lead"]))).first() is not None


def _catalog_for_prompt(session: Session, conv: Conversation, services: list[Service], text: str) -> tuple[list[Service], str]:
    """Large catalogs: send only items relevant to the last customer messages, plus the category list."""
    available = [s for s in services if s.available]
    if len(available) <= CATALOG_PROMPT_LIMIT:
        return services, ""
    recent = session.exec(
        select(Message.text).where(Message.conversation_id == conv.id, Message.role == "customer").order_by(Message.id.desc()).limit(3)
    ).all()
    chosen = select_relevant(available, [text, *recent])
    categories = sorted({s.category for s in available if s.category})
    hint = (
        f"Показаны {len(chosen)} из {len(available)} позиций, подходящих к вопросу клиента."
        + (" Категории: " + ", ".join(categories) + "." if categories else "")
        + " Если нужной позиции нет в показанных, уточни у клиента название или категорию; не говори, что её нет."
    )
    return chosen, hint


def _already_seen(session: Session, business_id: int, external_id: str) -> bool:
    found = session.exec(
        select(Message.id).where(Message.business_id == business_id, Message.external_id == external_id)
    ).first()
    return found is not None


def _get_or_create_conversation(session: Session, business: Business, incoming: IncomingMessage, now: datetime) -> Conversation:
    conv = session.exec(
        select(Conversation).where(
            Conversation.business_id == business.id,
            Conversation.channel == incoming.channel,
            Conversation.chat_id == incoming.chat_id,
        )
    ).first()
    if conv is None:
        conv = Conversation(
            business_id=business.id,
            channel=incoming.channel,
            chat_id=incoming.chat_id,
            display_name=(incoming.user_name or "")[:120],
            created_at=now,
            last_message_at=now,
        )
        session.add(conv)
        session.flush()
    return conv


def _add_message(
    session: Session,
    business: Business,
    conv: Conversation,
    role: str,
    text: str,
    now: datetime,
    off: bool,
    external_id: str = "",
) -> Message:
    msg = Message(
        business_id=business.id,
        conversation_id=conv.id,
        role=role,
        text=text,
        created_at=now,
        off_hours=off,
        external_id=external_id or "",
    )
    session.add(msg)
    conv.last_message_at = now
    session.add(conv)
    return msg


def _add_lead(session: Session, business: Business, conv: Conversation, kind: str, summary: str, now: datetime, off: bool) -> Lead:
    lead = Lead(
        business_id=business.id,
        conversation_id=conv.id,
        kind=kind,
        summary=summary[:1000],
        customer_name=conv.customer_name or conv.display_name,
        customer_phone=conv.customer_phone,
        channel=conv.channel,
        chat_id=conv.chat_id,
        created_at=now,
        off_hours=off,
    )
    session.add(lead)
    session.flush()
    return lead


def _history(session: Session, conv: Conversation, now: datetime) -> list[dict]:
    rows = session.exec(
        select(Message)
        .where(Message.conversation_id == conv.id, Message.created_at >= now - HISTORY_WINDOW)
        .order_by(Message.id.desc())
        .limit(HISTORY_LIMIT)
    ).all()
    return build_history(list(reversed(rows)))


def _norm(text: str) -> str:
    return " ".join((text or "").split()).casefold()


def _is_own_text(echo: str, sent: list[str]) -> bool:
    """Does an echo match one of our replies? Channels may cut long texts, so a long echo may be a prefix."""
    e = _norm(echo).rstrip("…").strip()
    if not e:
        return False
    for t in sent:
        t = _norm(t)
        if e == t or (len(e) >= 20 and t.startswith(e)):
            return True
    return False


def _handle_echo(
    session: Session, business: Business, conv: Conversation, incoming: IncomingMessage, now: datetime, off: bool
) -> Outcome:
    """A message the business sent from its own app. Ours -> ignore; typed by staff -> pause the AI."""
    text = (incoming.text or "").strip()
    recent_ai = session.exec(
        select(Message.text)
        .where(Message.conversation_id == conv.id, Message.role == "ai")
        .order_by(Message.id.desc())
        .limit(5)
    ).all()
    if _is_own_text(text, list(recent_ai)):
        return Outcome(skipped="own_echo")
    _add_message(session, business, conv, "staff", text or "[сообщение администратора]", now, off, incoming.external_id)
    conv.ai_paused_until = now + STAFF_TAKEOVER_PAUSE
    session.add(conv)
    return Outcome(skipped="staff_reply")


def _handle_command(
    session: Session, business: Business, conv: Conversation, incoming: IncomingMessage, text: str, now: datetime, off: bool
) -> Outcome | None:
    command, _, argument = text.partition(" ")
    command = command.split("@", 1)[0].lower()
    if command == "/start":
        reply = (business.greeting or DEFAULT_GREETING).format(name=business.name)
        _add_message(session, business, conv, "ai", reply, now, off)
        return Outcome(reply=reply)
    if command == "/admin":
        code = argument.strip()
        if incoming.channel == "telegram" and code and business.admin_link_code and hmac.compare_digest(code, business.admin_link_code):
            ids = [x for x in business.admin_chat_ids.split(",") if x.strip()]
            if incoming.chat_id not in ids:
                ids.append(incoming.chat_id)
            business.admin_chat_ids = ",".join(ids)
            session.add(business)
            return Outcome(reply="Готово. Сюда будут приходить уведомления о новых записях и заявках.")
        return Outcome(reply="Код не подошёл. Код есть в панели управления: «Настройки» → «Уведомления в Telegram».")
    return None  # other slash-texts are answered like normal messages


def pack_offers(business: Business, feature: str) -> bool:
    return get_pack(business.niche).offers(feature)


def _requested_slot_hint(
    session: Session, conv: Conversation, slots: list[tuple[Slot, Staff]], now_local: datetime, now: datetime
) -> str:
    """Point the model at the slot the customer already named ("завтра в 18:00"), so it books it instead of
    asking "подтверждаете?" again or offering other times."""
    if not slots:
        return ""
    texts = session.exec(
        select(Message.text)
        .where(Message.conversation_id == conv.id, Message.role == "customer", Message.created_at >= now - HISTORY_WINDOW)
        .order_by(Message.id.desc())
        .limit(4)
    ).all()
    wanted = next((t for t in (requested_time(x, now_local.date()) for x in texts) if t), None)
    if wanted is None:
        return ""
    matches = [(slot, m) for slot, m in slots if slot.start == wanted]
    if not matches:
        return (f"\nКлиент назвал время {fmt_slot(wanted)}, но такого свободного окна нет: предложи ближайшие окна из "
                "списка или прими заявку на это время.")
    options = "; ".join(f"окно {slot.id} — {m.name}" for slot, m in matches[:4])
    return (f"\nКлиент сам назвал время {fmt_slot(wanted)}, и оно свободно ({options}). Это и есть выбор клиента: "
            "не переспрашивай «подтверждаете?» и не предлагай другое время. Как только есть имя и телефон, "
            "сразу заполни booking с этим slot_id.")


def _alternatives(
    session: Session, business: Business, now_local: datetime, staff_id: int | None, min_capacity: int = 0,
    min_seats: int = 1,
) -> list[str]:
    rows = free_slots(session, business.id, now_local, staff_id=staff_id, limit=50) if staff_id else []
    rows = [(slot, m) for slot, m in rows if seats_left(slot) >= min_seats][:3]
    if not rows:
        rows = [(slot, m) for slot, m in free_slots(session, business.id, now_local, limit=200) if seats_left(slot) >= min_seats]
    if min_capacity:
        rows = [(slot, m) for slot, m in rows if not m.capacity or m.capacity >= min_capacity]
    return [f"{fmt_slot(slot.start)} ({member.name})" for slot, member in rows[:3]]


def _try_booking(
    session: Session,
    business: Business,
    conv: Conversation,
    data: dict,
    reply: str,
    now: datetime,
    now_local: datetime,
    off: bool,
    channel: str,
    pack: Pack | None = None,
) -> tuple[str, Booking | None]:
    name = (data.get("name") or "").strip()[:120]
    phone = normalize_phone(data.get("phone"))
    if not name or not phone:
        return ASK_CONTACTS_REPLY, None

    slot_id = data.get("slot_id")
    slot = session.get(Slot, slot_id) if slot_id else None
    member = session.get(Staff, slot.staff_id) if slot else None
    usable = (
        slot is not None
        and slot.business_id == business.id
        and slot.status == "free"
        and slot.start > now_local
        and member is not None
        and member.active
    )
    party = int(data.get("party_size") or 0)
    if usable and pack is not None and pack.party_size:
        if party <= 0:
            return "Сколько будет гостей? Подберу стол нужного размера.", None
        if member.capacity and party > member.capacity:
            options = _alternatives(session, business, now_local, None, min_capacity=party)
            text = f"Этот стол рассчитан на {member.capacity} гостей."
            text += (" Подойдут: " + "; ".join(options) + ". Какое время удобно?") if options else " Оставьте телефон — администратор подберёт стол."
            return text, None
    if usable and slot.seats > 1 and seats_needed(slot, party) > seats_left(slot):
        left = seats_left(slot)
        options = _alternatives(session, business, now_local, slot.staff_id, min_seats=seats_needed(slot, party))
        text = f"На это занятие осталось мест: {left}."
        text += (" Есть места: " + "; ".join(options) + ". Какое время удобно?") if options else " Оставьте телефон — администратор подберёт время."
        return text, None
    if not usable or not claim_slot(session, slot.id, seats_needed(slot, party)):
        options = _alternatives(session, business, now_local, slot.staff_id if slot else None)
        if options:
            text = "Извините, это время уже занято. Свободно: " + "; ".join(options) + ". Какое удобно?"
        else:
            text = "Извините, это время уже занято. Оставьте удобное время — администратор перезвонит и подберёт запись."
        return text, None

    booking = Booking(
        business_id=business.id,
        slot_id=slot.id,
        conversation_id=conv.id,
        staff_id=member.id,
        staff_name=member.name,
        start=slot.start,
        service=(data.get("service") or "").strip()[:200],
        party_size=max(0, party),
        customer_name=name,
        customer_phone=phone,
        channel=channel,
        chat_id=conv.chat_id,
        created_at=now,
        created_off_hours=off,
    )
    session.add(booking)
    conv.customer_name = name
    conv.customer_phone = phone
    session.add(conv)
    session.flush()
    return reply, booking


def _booking_request(
    session: Session, business: Business, conv: Conversation, data: dict, reply: str, now: datetime, off: bool
) -> tuple[str, Lead | None]:
    """The customer wants an appointment but no slot was chosen: staff call back to confirm the time."""
    name = (data.get("name") or "").strip()[:120]
    phone = normalize_phone(data.get("phone"))
    if not name or not phone:
        return ASK_CONTACTS_REPLY, None
    conv.customer_name, conv.customer_phone = name, phone
    session.add(conv)
    service = (data.get("service") or "").strip()[:200] or "запись"
    when = (data.get("preferred_time") or "").strip()[:200]
    summary = f"Заявка на запись: {service}" + (f", удобное время: {when}" if when else "") + ". Перезвоните и подтвердите время."
    return reply, _add_lead(session, business, conv, "request", summary, now, off)


MAX_QUANTITY = 50
ASK_ORDER_CONTACTS = "Чтобы оформить заказ, напишите, пожалуйста, имя и номер телефона."


def _try_order(
    session: Session, business: Business, pack: Pack, conv: Conversation, data: dict, reply: str,
    now: datetime, off: bool, channel: str,
) -> tuple[str, Order | None]:
    """Check every line against the catalog and compute the total in code; the model never sets prices."""
    name = (data.get("name") or "").strip()[:120]
    phone = normalize_phone(data.get("phone"))
    if not name or not phone:
        return ASK_ORDER_CONTACTS, None
    mode = data.get("mode") if data.get("mode") in pack.order_modes else pack.order_modes[0]
    address = (data.get("address") or "").strip()[:300]
    if mode == "delivery" and not address:
        return "Напишите, пожалуйста, адрес доставки.", None

    lines: list[tuple[Service, int, str]] = []
    problems: list[str] = []
    for line in data.get("lines") or []:
        item = session.get(Service, line.get("item_id")) if line.get("item_id") else None
        qty = int(line.get("quantity") or 0)
        if item is None or item.business_id != business.id:
            problems.append("одной позиции нет в списке")
        elif not item.available:
            problems.append(f"«{item.name}» сейчас нет в наличии")
        elif not 1 <= qty <= MAX_QUANTITY:
            problems.append(f"количество «{item.name}» должно быть от 1 до {MAX_QUANTITY}")
        else:
            lines.append((item, qty, (line.get("note") or "").strip()[:200]))
    if problems or not lines:
        detail = "; ".join(dict.fromkeys(problems)) or "в заказе нет позиций"
        return f"Не получилось оформить заказ: {detail}. Выберите, пожалуйста, из списка.", None

    items_total = None if any(item.price_value is None for item, _, _ in lines) else sum(item.price_value * q for item, q, _ in lines)
    if items_total is not None and business.min_order and items_total < business.min_order:
        return (
            f"Минимальная сумма заказа — {_som(business.min_order)}, сейчас в заказе на {_som(items_total)}. "
            "Хотите что-нибудь добавить?"
        ), None
    fee = 0
    if mode == "delivery" and business.delivery_fee:
        free = business.free_delivery_from and items_total is not None and items_total >= business.free_delivery_from
        fee = 0 if free else business.delivery_fee
    total = None if items_total is None else items_total + fee
    order = Order(
        business_id=business.id, conversation_id=conv.id, customer_name=name, customer_phone=phone, mode=mode,
        address=address, wanted_time=(data.get("time") or "").strip()[:100], comment=(data.get("comment") or "").strip()[:300],
        total=total, delivery_fee=fee, channel=channel, chat_id=conv.chat_id, created_at=now, created_off_hours=off,
    )
    session.add(order)
    session.flush()
    for item, qty, note in lines:
        session.add(OrderLine(order_id=order.id, item_id=item.id, name=item.name, quantity=qty, unit_price=item.price_value, note=note))
    conv.customer_name, conv.customer_phone = name, phone
    session.add(conv)
    session.flush()
    if total is None:
        summary = "Точную сумму подтвердит администратор."
    elif fee:
        summary = f"Сумма заказа: {_som(total)}, включая доставку {_som(fee)}."
    else:
        summary = f"Сумма заказа: {_som(total)}."
    return f"{reply}\n{summary}", order


def _som(value: int) -> str:
    return f"{value:,} сом".replace(",", " ")


def _order_note(session: Session, conv: Conversation, order: Order, off: bool) -> str:
    when = " (в нерабочее время)" if off else ""
    rows = session.exec(select(OrderLine).where(OrderLine.order_id == order.id).order_by(OrderLine.id)).all()
    items = [f"{r.quantity} × {r.name}" + (f" ({r.note})" if r.note else "") for r in rows]
    how = f"доставка: {order.address}" if order.mode == "delivery" else "самовывоз"
    total = _som(order.total) if order.total is not None else "сумму уточнить"
    if order.delivery_fee:
        total += f" (доставка {_som(order.delivery_fee)})"
    lines = [f"Новый заказ #{order.id}{when}", f"{order.customer_name}, {order.customer_phone}", *items,
             f"Итого: {total}; {how}" + (f"; к {order.wanted_time}" if order.wanted_time else "")]
    if order.comment:
        lines.append(f"Комментарий: {order.comment}")
    lines.append(f"Канал: {CHANNEL_LABELS.get(conv.channel, conv.channel)}")
    return "\n".join(lines)


def _qualified_lead(
    session: Session, business: Business, conv: Conversation, data: dict, reply: str, now: datetime, off: bool
) -> tuple[str, Lead | None]:
    name = (data.get("name") or "").strip()[:120]
    phone = normalize_phone(data.get("phone"))
    if not name or not phone:
        return ASK_CONTACTS_REPLY, None
    conv.customer_name, conv.customer_phone = name, phone
    session.add(conv)
    lead = _add_lead(session, business, conv, "lead", "Заявка на подбор / консультацию. Свяжитесь с клиентом.", now, off)
    lead.details = (data.get("details") or "").strip()[:1000]
    session.add(lead)
    return reply, lead


def _request_note(conv: Conversation, lead: Lead, off: bool) -> str:
    when = " (в нерабочее время)" if off else ""
    return "\n".join(
        [
            f"Новая заявка на запись{when}",
            f"{lead.customer_name}, {lead.customer_phone}",
            lead.summary,
            f"Канал: {CHANNEL_LABELS.get(conv.channel, conv.channel)}",
        ]
    )


def _booking_note(business: Business, booking: Booking, off: bool) -> str:
    when = " (в нерабочее время)" if off else ""
    lines = [
        f"Новая запись через ИИ{when}",
        f"{booking.customer_name}, {booking.customer_phone}",
        f"{booking.service or 'приём'} — {fmt_slot(booking.start)}, {booking.staff_name}",
        f"Канал: {CHANNEL_LABELS.get(booking.channel, booking.channel)}",
    ]
    return "\n".join(lines)


def _lead_note(business: Business, conv: Conversation, lead: Lead, off: bool) -> str:
    when = " (в нерабочее время)" if off else ""
    who = ", ".join(x for x in [lead.customer_name, lead.customer_phone] if x) or "имя не указано"
    lines = [
        ("Новый лид" if lead.kind == "lead" else "Заявка администратору") + when,
        lead.summary,
        *([lead.details] if lead.details else []),
        f"Клиент: {who}",
        f"Канал: {CHANNEL_LABELS.get(conv.channel, conv.channel)}",
    ]
    return "\n".join(lines)
