"""A demo on the prospect's own price list, for the founder's first message.

The strategy's first-ten-customers move (docs: «Joop AI — стратегия с нуля»): the founder pastes a salon's price
list from its Instagram post, Joop builds a demo company from it (the same "fill from text" the panel has), runs
two customer questions through the real engine, and shows the dialogue on a phone-sized page the founder
screenshots into the first message. The prospect sees the AI answering with their own prices, in their own
words — not a slide. Nothing is sent by Joop: the founder sends the message himself.
"""

from __future__ import annotations

import secrets
from datetime import datetime, time, timedelta
from typing import Any

from sqlmodel import Session, select

from . import autofill, billing
from .agent.engine import handle_incoming
from .catalog import parse_price
from .channels.base import IncomingMessage
from .models import Business, Conversation, Faq, Message, Prospect, Service, Staff
from .niches import all_packs
from .presets import create_business
from .slots import generate_slots
from .timeutil import utc_to_local

PITCH_CHAT = "pitch"  # console conversation that holds the demo dialogue
QUESTIONS = {  # the two questions a prospect's customer asks most; the second needs free times to show booking
    "ru": ["Здравствуйте! Сколько стоит {service}?", "А можно завтра вечером? Айгерим, 0555 123 456"],
    "ky": ["Саламатсызбы! {service} канча турат?", "Эртең кечинде болобу? Айгерим, 0555 123 456"],
}
OUTREACH = {
    "ru": ("Здравствуйте! Я Бектур, делаю Joop AI — ИИ-администратор для бизнеса Бишкека.\n"
           "Взял ваш прайс из поста и показываю, как он ответил бы клиенту в 23:00 (скриншот).\n"
           "Он пишет по-русски и по-кыргызски, записывает только в свободное время, спорное передаёт вам.\n"
           "Сколько сообщений в Директ приходит после 19:00? Если больше пяти в день — подключу бесплатно на месяц "
           "и пришлю отчёт, сколько записей он сделал."),
    "ky": ("Саламатсызбы! Мен Бектурмун, Бишкек бизнеси үчүн Joop AI — ИИ-администратор жасап жатам.\n"
           "Постуңуздагы прайсты алып, кардарга саат 23:00дө кандай жооп берерин көрсөтөм (скриншот).\n"
           "Орусча жана кыргызча жазат, бош убакытка гана жазат, талаштуу суроолорду сизге өткөрөт.\n"
           "Кечки 19:00дөн кийин Директке канча билдирүү келет? Күнүнө бештен көп болсо — бир айга бекер кошуп, "
           "канча жазуу жасаганы боюнча отчёт жиберем."),
}


def build(session: Session, llm: Any, prospect: Prospect, source: str, trial_days: int, now_utc: datetime) -> tuple[Business | None, str]:
    """Make (or refill) the prospect's demo company from the pasted text. Returns (business, problem)."""
    proposal = autofill.propose(llm, source, [], [])
    if proposal is None:
        return None, "ИИ не смог разобрать текст. Проверьте баланс Anthropic и попробуйте снова."
    priced = [s for s in proposal.services if s.price]
    if not priced:
        return None, "В тексте не нашлось услуг с ценами. Вставьте пост с прайсом."
    niche = prospect.niche if prospect.niche in all_packs() else "beauty"
    if prospect.demo_business_id:
        b = session.get(Business, prospect.demo_business_id)
    else:
        b = None
    if b is None:
        slug = f"demo-{secrets.token_hex(3)}"
        b = create_business(session, slug=slug, name=prospect.name, password=secrets.token_urlsafe(9), niche=niche,
                            demo=False, now_utc=now_utc)
        billing.start_trial(session, b, trial_days, now_utc, "pitch", prospect.contact_name, prospect.phone)
        prospect.demo_business_id = b.id
    for row in session.exec(select(Service).where(Service.business_id == b.id)).all():
        session.delete(row)
    for row in session.exec(select(Faq).where(Faq.business_id == b.id)).all():
        session.delete(row)
    for i, item in enumerate(priced):
        session.add(Service(business_id=b.id, name=item.name, name_ky=item.name_ky, price=item.price,
                            price_value=parse_price(item.price), note=item.note, sort=i))
    for qa in proposal.faq:
        session.add(Faq(business_id=b.id, question=qa.question, answer=qa.answer))
    staff = session.exec(select(Staff).where(Staff.business_id == b.id)).first()
    if staff is None:
        staff = Staff(business_id=b.id, name="Мастер", role="", handles="")
        session.add(staff)
        session.flush()
    today = utc_to_local(now_utc, b.timezone).date()
    generate_slots(session, b, staff.id, today + timedelta(days=1), today + timedelta(days=7), time(10, 0), time(19, 0), 60)
    session.flush()
    return b, ""


def run_dialogue(session: Session, business: Business, get_llm: Any, lang: str, now_utc: datetime, base_url: str = "") -> list[Message]:
    """Ask the two questions with the first priced service's name; return the dialogue's messages."""
    conv = session.exec(select(Conversation).where(Conversation.business_id == business.id, Conversation.channel == "console",
                                                   Conversation.chat_id == PITCH_CHAT)).first()
    if conv is not None:
        for m in session.exec(select(Message).where(Message.conversation_id == conv.id)).all():
            session.delete(m)
        session.delete(conv)
        session.flush()
    first = session.exec(select(Service).where(Service.business_id == business.id).order_by(Service.sort)).first()
    service = (first.name_ky if lang == "ky" and first and first.name_ky else first.name if first else "услуга").lower()
    when = now_utc
    for i, q in enumerate(QUESTIONS.get(lang, QUESTIONS["ru"])):
        text = q.format(service=service)
        handle_incoming(session, business, IncomingMessage("console", PITCH_CHAT, "text", text, "Клиент", f"pitch:{secrets.token_hex(4)}"),
                        get_llm, when + timedelta(seconds=i * 40), base_url=base_url)
        session.flush()
    conv = session.exec(select(Conversation).where(Conversation.business_id == business.id, Conversation.channel == "console",
                                                   Conversation.chat_id == PITCH_CHAT)).first()
    return list(session.exec(select(Message).where(Message.conversation_id == conv.id).order_by(Message.id)).all()) if conv else []


def outreach(prospect: Prospect) -> str:
    return prospect.message.strip() or OUTREACH.get(prospect.language, OUTREACH["ru"])
