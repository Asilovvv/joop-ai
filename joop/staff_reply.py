"""Staff answer a customer from the panel, through the channel the customer wrote in.

Before this, a customer handed to a person could be answered only by phone when they wrote in Telegram or in the
web chat: the bot's chat is not in the staff's own Telegram, and a website visitor has no address. Now:
- Telegram: the reply goes through the business's bot, any time;
- WhatsApp and Instagram: within 24 hours of the customer's last message (Meta's rule for messages a business
  starts); outside it staff call or write from their own app;
- web chat: the reply is kept and the chat page shows it (it asks for new staff messages while it is open,
  and on the next visit from the same browser).

A reply is stored in the dialogue as a staff message, so the AI sees it later; the AI stays quiet in this chat
for STAFF_TAKEOVER_PAUSE, as when staff answer from their own app, and the chat's open requests are closed.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from sqlmodel import Session, select

from .agent.engine import STAFF_TAKEOVER_PAUSE
from .followups import SERVICE_WINDOW
from .models import Business, Conversation, Lead, Message

if TYPE_CHECKING:
    from .runtime import Runtime

MAX_TEXT = 2000
WEB_KEEP = timedelta(days=7)  # staff replies a web chat page still shows to a returning visitor
CHANNEL_NAMES = {"telegram": "Telegram", "whatsapp": "WhatsApp", "instagram": "Instagram"}


def blocked(conv: Conversation, now_utc: datetime) -> str:
    """Why a reply cannot go to this chat now, in Russian; "" when it can."""
    if conv.channel == "web" or conv.channel == "telegram":
        return ""
    if conv.channel in ("whatsapp", "instagram"):
        if conv.last_customer_at and now_utc - conv.last_customer_at < SERVICE_WINDOW:
            return ""
        name = CHANNEL_NAMES[conv.channel]
        return (f"{name} разрешает писать клиенту только в течение суток после его последнего сообщения. "
                f"Позвоните клиенту или напишите ему из своего приложения {name}.")
    return "Из этого диалога ответить нельзя: это тестовый чат."


def send(session: Session, rt: "Runtime", business: Business, conv: Conversation, text: str,
         now_utc: datetime, author: str = "") -> tuple[bool, str]:
    """(sent, problem in Russian). Stores the reply, pauses the AI in this chat and closes its open requests."""
    text = (text or "").strip()[:MAX_TEXT]
    if not text:
        return False, "Напишите текст ответа."
    problem = blocked(conv, now_utc)
    if problem:
        return False, problem
    if conv.channel != "web":
        client = rt.channel_client(business, conv.channel)
        if client is None:
            return False, f"{CHANNEL_NAMES[conv.channel]} не подключён в разделе «Каналы»."
        if not client.send_text(conv.chat_id, text):
            return False, f"{CHANNEL_NAMES[conv.channel]} не принял сообщение. Попробуйте ещё раз или позвоните клиенту."
    session.add(Message(business_id=business.id, conversation_id=conv.id, role="staff", text=text, created_at=now_utc,
                        author=author[:80]))
    conv.last_message_at = now_utc
    conv.ai_paused_until = max(conv.ai_paused_until or now_utc, now_utc + STAFF_TAKEOVER_PAUSE)
    session.add(conv)
    for lead in session.exec(select(Lead).where(Lead.conversation_id == conv.id, Lead.status == "new")).all():
        lead.status, lead.closed_by = "done", author[:80]
        session.add(lead)
    return True, ""


def web_updates(session: Session, business: Business, chat_id: str, after: int, now_utc: datetime) -> list[Message]:
    """Staff replies to one web chat visitor newer than message id `after`."""
    conv = session.exec(select(Conversation).where(Conversation.business_id == business.id, Conversation.channel == "web",
                                                   Conversation.chat_id == chat_id)).first()
    if conv is None:
        return []
    return list(session.exec(select(Message).where(
        Message.conversation_id == conv.id, Message.role == "staff", Message.id > after,
        Message.created_at >= now_utc - WEB_KEEP,
    ).order_by(Message.id).limit(20)).all())
