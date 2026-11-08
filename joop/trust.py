"""Two habits that keep a business's customers trusting the AI, both done by code.

1. The AI says it is an AI, once, calmly: the first reply in a new conversation starts with one line naming the
   business and the fact that an AI assistant answers and a person is one message away. Disclosure at first contact
   is required in the EU from August 2026 and in several US states, and a field test on a UK service company found
   it cut complaints without cutting bookings (see docs/strategy, "Правила доверия"). The line is added by code
   after the model's reply, so the prompt and the evaluation are unchanged.

2. Week one review: for a business's first seven days with real customers, the morning summary carries up to
   three of yesterday's dialogues (customer line, AI line, link) and asks the owner to check them. Vendors in this
   market say most churn happens in the first 90 days and that owners who see the first real conversations stay;
   the number is theirs and unverified, but reading the first 50 dialogues together is cheap and catches wrong
   answers while the price list is still fresh.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from sqlmodel import Session, select

from .models import Business, Conversation, Message
from .stats import real_conversation

REAL_CHANNELS = ("telegram", "whatsapp", "instagram", "web")
# Where the first reply is the first contact. Telegram greets on /start (DEFAULT_GREETING says it is an AI) and the
# web chat page says so in its header, so only WhatsApp and Instagram need the line in the reply itself.
INTRO_CHANNELS = ("whatsapp", "instagram")
WEEK_ONE = timedelta(days=7)
REVIEW_PER_DAY = 3
EXCERPT = 140


_GREETING = re.compile(r"^(здравствуйте|добрый день|добрый вечер|доброе утро|саламатсызбы|салам|кутман күн|привет)[!,.]*\s*", re.I)


def with_intro(business: Business, reply: str, kyrgyz: bool) -> str:
    """The first reply to a new customer, opened by one calm line that says an AI answers. The model usually
    greets too; that greeting is dropped so the customer is not greeted twice."""
    body = _GREETING.sub("", reply.strip(), count=1)
    body = body[:1].upper() + body[1:] if body else reply.strip()
    if kyrgyz:
        head = f"Саламатсызбы! Мен «{business.name}» ИИ-жардамчысымын: дароо жооп берем, керек болсо администраторду чакырам."
    else:
        head = f"Здравствуйте! Я ИИ-помощник «{business.name}»: отвечаю сразу, а если нужно — позову администратора."
    return f"{head}\n\n{body}"


def first_contact(session: Session, conv: Conversation) -> bool:
    """True when the AI has not answered in this conversation yet (the reply about to be sent is the first)."""
    return session.exec(select(Message.id).where(Message.conversation_id == conv.id, Message.role == "ai")).first() is None


def first_live_at(session: Session, business: Business) -> datetime | None:
    """When the first real customer (not the panel's test chat, not the demo on the site) wrote."""
    return session.exec(select(Message.created_at).join(Conversation, Conversation.id == Message.conversation_id).where(
        Message.business_id == business.id, Message.role == "customer", Conversation.channel.in_(REAL_CHANNELS),
        real_conversation(),  # not the owner trying their own bot either
    ).order_by(Message.id)).first()


def _cut(text: str) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= EXCERPT else text[:EXCERPT - 1] + "…"


def week_one_review(session: Session, business: Business, now_utc: datetime, base_url: str = "") -> str | None:
    """Up to three of the last day's dialogues for the owner to check, during the first week with real customers."""
    started = first_live_at(session, business)
    if started is None or now_utc - started > WEEK_ONE:
        return None
    since = now_utc - timedelta(hours=24)
    convs = session.exec(select(Conversation).where(
        Conversation.business_id == business.id, Conversation.channel.in_(REAL_CHANNELS), real_conversation(), Conversation.last_message_at >= since,
    ).order_by(Conversation.last_message_at.desc()).limit(REVIEW_PER_DAY * 3)).all()
    items = []
    for conv in convs:
        pair = _last_pair(session, conv, since)
        if pair is None:
            continue
        who = conv.customer_name or conv.display_name or "Клиент"
        link = f"{base_url.rstrip('/')}/panel/conversations/{conv.id}" if base_url else f"«Диалоги» → {who}"
        items.append(f"— {who}: «{_cut(pair[0])}»\n   ИИ: «{_cut(pair[1])}»\n   {link}")
        if len(items) == REVIEW_PER_DAY:
            break
    if not items:
        return None
    day = (now_utc - started).days + 1
    return (f"Первая неделя с ИИ, день {day}. Проверьте, пожалуйста, вчерашние ответы — так ИИ быстрее станет своим:\n"
            + "\n".join(items)
            + "\nЕсли ответ не тот — впишите правильный в «Вопросы» или правило в «Настройках», и ИИ будет отвечать так.")


def _last_pair(session: Session, conv: Conversation, since: datetime) -> tuple[str, str] | None:
    rows = session.exec(select(Message).where(Message.conversation_id == conv.id, Message.created_at >= since)
                        .order_by(Message.id.desc()).limit(10)).all()
    customer = ai = None
    for m in rows:  # newest first: the last AI answer, then the customer line right before it
        if ai is None and m.role == "ai":
            ai = m.text
        elif ai is not None and m.role == "customer":
            customer = m.text
            break
    return (customer, ai) if customer and ai else None
