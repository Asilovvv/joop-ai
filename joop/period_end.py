"""The owner hears that the AI is about to stop before it stops, and staff see the customers who write after.

Before this, a trial or a paid month ran out in silence: the morning summary said nothing, the AI went quiet three
days later (billing.GRACE_DAYS), and a customer writing in Telegram or the site chat was seen by nobody, since those
chats are read only by the bot. Now:
- the morning summary carries one line at each step: three days left, the last day, the waiting days, the stop; each
  is said once for the period it is about (Subscription.end_told), and a payment starts the count again;
- after the stop, every message from a chat only the bot reads goes to staff as a note, with the reason and the link
  to pay (`stopped_note`), like the messages of a chat where staff answer by hand.

A cancelled subscription gets none of this: cancelling promises no reminders to pay (billing.cancel). The free plan
never ends; a suspended business was stopped by the founder on purpose.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlmodel import Session

from . import billing, free_plan
from .lang import plural
from .models import Business, Conversation, Subscription
from .timeutil import utc_to_local

STAGES = ("soon", "last", "waiting", "stopped")
WARN_DAYS = 3  # «осталось три дня»: enough to pay by transfer, which the founder confirms by hand
TOLD_STOP_FOR = timedelta(days=7)  # a business that stopped long ago (before this existed) is not told today


def _period(sub: Subscription, now: datetime) -> tuple[str, datetime, billing.State] | None:
    """The step this subscription is at and the end it is about, or None when there is nothing to say."""
    if sub.status == "suspended" or sub.plan == "free" or sub.cancelled_at is not None:
        return None
    st = billing.state(sub, now)
    if st.code == "active":
        end = sub.paid_until
    elif st.code == "trial":
        end = sub.trial_ends_at
    elif st.code in ("grace", "expired"):
        end = sub.paid_until or sub.trial_ends_at
    else:
        return None
    if end is None:
        return None
    if st.code in ("active", "trial"):
        if st.days_left > WARN_DAYS:
            return None
        return ("last" if st.days_left <= 1 else "soon"), end, st
    if st.code == "grace":
        return "waiting", end, st
    if now - (end + timedelta(days=billing.GRACE_DAYS)) > TOLD_STOP_FOR:
        return None
    return "stopped", end, st


def _pay_line(session: Session, business: Business, sub: Subscription, base_url: str, price_som: int) -> str:
    link = f"{base_url.rstrip('/')}/panel/billing" if base_url else "панель → «Оплата»"
    price = billing.price_for(sub, price_som)
    som = f"{price:,}".replace(",", " ")
    line = f"Оплатить ({som} сом в месяц): {link}" if price else f"Оплатить: {link}"
    if free_plan.eligible(session, business.id):
        line += "\nУ вас один мастер — можно перейти на бесплатный тариф, там же."
    return line


def _what(sub: Subscription) -> str:
    return "Оплаченный период" if sub.paid_until else "Пробный период"


def notice(session: Session, business: Business, now: datetime, base_url: str = "", price_som: int = 0) -> str | None:
    """The line for the morning summary, once per step and period; marks it said. None: nothing to say today."""
    sub = billing.get_subscription(session, business.id)
    found = _period(sub, now) if sub else None
    if found is None:
        return None
    stage, end, st = found
    key = f"{end:%Y-%m-%dT%H:%M}"
    told_end, _, told_stage = (sub.end_told or "").partition("/")
    if told_end == key and told_stage in STAGES and STAGES.index(told_stage) >= STAGES.index(stage):
        return None
    local_end = utc_to_local(end, business.timezone)
    stop = utc_to_local(end + timedelta(days=billing.GRACE_DAYS), business.timezone)
    what = _what(sub)
    if stage in ("soon", "last"):
        head = (f"{what} «{business.name}» заканчивается {local_end:%d.%m} в {local_end:%H:%M} — "
                f"осталось {st.days_left} {plural(st.days_left, 'день', 'дня', 'дней')}. "
                f"Без оплаты ИИ ответит клиентам ещё {billing.GRACE_DAYS} {plural(billing.GRACE_DAYS, 'день', 'дня', 'дней')}, "
                f"а {stop:%d.%m} остановится.")
    elif stage == "waiting":
        head = (f"{what} «{business.name}» закончился {local_end:%d.%m}. ИИ отвечает клиентам до {stop:%d.%m} "
                f"{stop:%H:%M}, потом остановится: клиенты в Telegram и в чате на сайте останутся без ответа.")
    else:
        head = (f"ИИ-администратор «{business.name}» остановлен {stop:%d.%m}: {what.lower()} закончился. "
                "Клиентам никто не отвечает сам; их сообщения из Telegram и с сайта будут приходить сюда, "
                "ответьте им из панели. Оплатите — и ИИ сразу снова отвечает.")
    sub.end_told = f"{key}/{stage}"
    session.add(sub)
    return head + "\n" + _pay_line(session, business, sub, base_url, price_som)


def why_stopped(session: Session, business: Business, now: datetime) -> str:
    """Why the AI did not answer, in a few words, for a note to staff."""
    sub = billing.get_subscription(session, business.id)
    if sub is None:
        return "ИИ не отвечает"
    if sub.status == "suspended":
        return "ИИ не отвечает: доступ приостановлен, напишите нам"
    if sub.plan == "free":
        return "ИИ не отвечает: бесплатный тариф — для одного мастера, а их сейчас больше"
    if sub.cancelled_at is not None:
        return "ИИ не отвечает: подписка отменена"
    return f"ИИ не отвечает: {_what(sub).lower()} закончился и не оплачен"


def stopped_note(session: Session, business: Business, conv: Conversation, text: str, now: datetime,
                 base_url: str = "") -> str:
    """A customer wrote in a chat only the bot reads while the AI is stopped for payment: staff see it here."""
    who = conv.customer_name or conv.display_name or "Клиент"
    where = {"telegram": "Telegram", "web": "чат на сайте"}.get(conv.channel, conv.channel)
    body = text if len(text) <= 300 else text[:299] + "…"
    base = base_url.rstrip("/")
    answer = f"{base}/panel/conversations/{conv.id}" if base else "панель → «Диалоги»"
    pay = f"{base}/panel/billing" if base else "панель → «Оплата»"
    return f"{who} пишет ({where}): «{body}»\n{why_stopped(session, business, now)}. Ответить: {answer}\nОплатить: {pay}"
