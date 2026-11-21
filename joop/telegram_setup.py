"""Connecting a business's own Telegram bot by its BotFather token: from the panel's launch checklist and «Каналы»
(joop/web/saas.py) and from the owner's app (/api/mobile/setup/telegram). The only way a bot token gets saved: it is
checked with Telegram first, so an unchecked token never shows as connected."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlmodel import Session, select

from . import samples
from .channels.telegram import bot_id
from .dispatch import alerts_other_bot
from .models import Business

TOKEN = re.compile(r"\d{5,}:[A-Za-z0-9_-]{30,}")


@dataclass
class Connected:
    ok: bool  # the token is saved (the bot may still lack its webhook: see notes)
    username: str = ""
    notes: list[tuple[str, str]] = field(default_factory=list)  # (text, "ok" | "error") in the order to show


def connect(session: Session, rt, settings, business: Business, token: str) -> Connected:
    """Check the token, save it and point the bot's webhook here. Commits on success."""
    token = token.strip()
    if not TOKEN.fullmatch(token):
        return Connected(False, notes=[("Это не похоже на токен бота. Скопируйте его целиком из сообщения @BotFather.", "error")])
    others = session.exec(select(Business).where(Business.id != business.id, Business.telegram_bot_token != "")).all()
    if any(o.telegram_bot_token == token for o in others):  # tokens are encrypted: compare after decryption
        return Connected(False, notes=[("Этот бот уже подключён к другой компании.", "error")])
    if business.admin_chat_ids and not business.admin_bot and business.telegram_bot_token:
        business.admin_bot = bot_id(business.telegram_bot_token)  # linked before 0063: through the bot being replaced
    business.telegram_bot_token = token
    client = rt.telegram(business)
    me = client.get_me() if client else None
    if not me:  # checked before saving: a wrong token must not show as "connected"
        session.rollback()
        return Connected(False, notes=[("Telegram не принял токен — бот не подключён. Проверьте токен у @BotFather и "
                                        "вставьте его целиком.", "error")])
    username = str(me.get("username") or "")
    business.telegram_bot_username = username
    session.add(business)
    session.commit()
    relink = alerts_other_bot(business)  # the alert chats were linked through the previous bot
    if not settings.public_base_url.startswith("https://"):
        return Connected(True, username, [(f"Токен бота @{username} сохранён. Чтобы бот отвечал, серверу нужен адрес https "
                                           "(PUBLIC_BASE_URL).", "error")])
    if not client.set_webhook(f"{settings.public_base_url}/webhooks/telegram/{business.slug}", business.telegram_secret):
        return Connected(True, username, [("Не удалось подключить бота. Попробуйте ещё раз через минуту.", "error")])
    notes = [(f"Бот @{username} подключён. Напишите ему — ИИ ответит.", "ok")]
    if relink:
        notes.append(("Чаты для уведомлений были привязаны через прежнего бота — новый писать в них не может. "
                      "Привяжите их заново в «Настройках» → «Уведомления в Telegram».", "error"))
    found = samples.left(session, session.get(Business, business.id))  # the bot now answers real customers
    if found.any:
        notes.append((samples.warning(found), "error"))
    return Connected(True, username, notes)
