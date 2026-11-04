"""The owner's numbers by a command in the staff Telegram chat.

Owners look at the phone, not at a web panel. In the chat that already gets the bookings (linked with /admin),
/today gives the morning summary right now, /week the last seven days, /gaps the free times ahead and how many
regulars are due. Everything is counted by code from the database — no model, no made-up numbers — and only for
chats on the business's admin list; anybody else gets the usual customer treatment. The staff chat is not a
customer conversation, so these commands leave no messages behind.
"""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Session

from .models import Business

COMMANDS = ("/today", "/week", "/gaps", "/help")
HELP = ("Команды для владельца:\n/today — сводка на сегодня: записи, кто не подтвердил, свободные окна\n"
        "/week — последние 7 дней в цифрах\n/gaps — свободные окна на неделю и кого пора пригласить\n"
        "Остальное — в панели: записи, диалоги, прайс.")


def is_admin_chat(business: Business, channel: str, chat_id: str) -> bool:
    return channel == "telegram" and chat_id in [x.strip() for x in (business.admin_chat_ids or "").split(",") if x.strip()]


def answer(session: Session, business: Business, text: str, now_utc: datetime) -> str | None:
    """The reply to an owner's command, or None when the text is not one."""
    command = (text or "").split(" ", 1)[0].split("@", 1)[0].lower()
    if command not in COMMANDS:
        return None
    from . import gaps, scheduler
    from .timeutil import utc_to_local

    if command == "/help":
        return HELP
    now_local = utc_to_local(now_utc, business.timezone)
    if command == "/today":
        text_ = scheduler.digest_text(session, business, now_utc) or f"Сводка «{business.name}» на {now_local:%d.%m}: за сутки никто не писал, записей на сегодня нет."
        days = gaps.week(session, business, now_local)
        free_today = next((d.free for d in days if d.date.date() == now_local.date()), 0)
        free_week = sum(d.free for d in days)
        return text_ + f"\nСвободных окон: сегодня {free_today}, на 7 дней {free_week}."
    if command == "/week":
        weekly = scheduler.weekly_report_text(session, business, now_utc)
        if weekly:
            return weekly.replace(f"Итоги недели «{business.name}»: ИИ-администратор", f"За 7 дней «{business.name}»: ИИ-администратор", 1)
        return f"За 7 дней «{business.name}»: клиенты не писали."
    days = gaps.week(session, business, now_local)
    rows = gaps.candidates(session, business, now_local)
    lines = [f"Свободных окон на 7 дней: {sum(d.free for d in days)} из {sum(d.total for d in days)}."]
    lines += [f"{d.date:%d.%m}: свободно {d.free} из {d.total}" for d in days]
    reachable = sum(1 for c in rows if c.reachable)
    lines.append(f"Пора пригласить: {len(rows)}, из них можно написать сейчас: {reachable}. Отправить — в панели, раздел «Пустые окна».")
    return "\n".join(lines)

