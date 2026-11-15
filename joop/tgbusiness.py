"""Which Telegram Business connection the bot answers through.

Telegram lets any Premium user add a public bot as the chatbot of their own account. Messages from such a
connection reach our webhook like the owner's, so only one connection is answered: the one made by a Telegram
account already linked as the business's alerts chat (/admin code, joop/owner_commands.py). Its messages
then count; messages through any other connection are dropped in the engine (joop/agent/engine.py).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from sqlmodel import Session

from .channels.telegram import parse_connection
from .db import new_session
from .models import Business
from .owner_commands import is_admin_chat

if TYPE_CHECKING:
    from .runtime import Runtime

log = logging.getLogger(__name__)

CONNECTED = ("Готово: Joop отвечает клиентам в вашем личном Telegram. Когда вы пишете клиенту сами, "
             "ИИ в этом чате замолкает.")
NO_REPLY = ("Joop подключён к вашему личному Telegram, но не может отвечать: в настройках Telegram Business → "
            "Чат-боты разрешите боту отвечать на сообщения.")
NOT_LINKED = ("Этот Telegram ещё не связан с Joop. Сначала откройте в панели «Настройки» и отправьте сюда команду "
              "/admin с кодом, затем подключите бота в Telegram Business заново.")


def apply(session: Session, business: Business, conn: dict[str, Any]) -> str:
    """Record or drop the connection; the note for the account that made it ("" for none)."""
    if not conn["enabled"]:
        if business.telegram_business_connection == conn["id"]:
            business.telegram_business_connection = ""
            session.add(business)
        return ""
    if not is_admin_chat(business, "telegram", conn["user_chat_id"]):
        log.info("Telegram Business connection from an account not linked to business %s: ignored", business.id)
        return NOT_LINKED
    business.telegram_business_connection = conn["id"]
    session.add(business)
    return CONNECTED if conn["can_reply"] else NO_REPLY


def handle_update(rt: "Runtime", business_id: int, update: dict[str, Any]) -> bool:
    """True when the update was a business connection (handled here), False for anything else."""
    conn = parse_connection(update)
    if conn is None:
        return False
    with new_session() as session:
        business = session.get(Business, business_id)
        if business is None:
            return True
        note = apply(session, business, conn)
        session.commit()
        client = rt.telegram(business) if note else None
    if client:
        client.send_text(conn["user_chat_id"], note)
    return True
