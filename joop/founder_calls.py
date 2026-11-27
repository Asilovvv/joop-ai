"""«Позвонить сегодня»: the businesses the founder should call, with the reason and what to offer.

The first paying customers come from calls, not from the site: a trial that ends in three days with results to show,
an owner stuck halfway through the setup, an AI stopped last week for want of a payment. The console had every
business in one table and the founder had to read it to find them. Now they are listed on top of /owner and sent to
the founder's Telegram every morning at 10:00 Bishkek (once a day: FounderCallList is the lock), each with the owner's
name and phone from the sign-up form:

- «ends»: a trial or a paid month ends in three days or less (not cancelled, no transfer waiting) — offer to pay,
  with what the AI did in the period;
- «setup»: signed up 1–10 days ago, still in the trial, the «Запуск» checklist not done — offer help (the turnkey
  setup), naming the step they stopped at;
- «stopped»: the AI stopped for payment in the last 14 days (not cancelled) — win them back with the results.

The site's demo businesses, cancelled, suspended and free-plan subscriptions are not listed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlmodel import Session, select

from . import billing, health
from .models import Booking, Business, Conversation, FounderCallList, Lead, Order, Subscription
from .pilot import DEMO_PREFIX
from .stats import not_test, real_conversation
from .timeutil import DEFAULT_TZ, utc_to_local

log = logging.getLogger(__name__)

SEND_HOUR = 10  # Bishkek: after the morning summaries, when owners pick up the phone
SETUP_DAYS = (1, 10)  # a day to try alone; after ten days a stalled setup is a lost lead, not a call
STOPPED_DAYS = 14
KINDS = ("ends", "stopped", "setup")  # the order of the list: money first


@dataclass
class Call:
    business_id: int
    name: str
    who: str  # «Бектур, +996 555 123 456», or what is known
    kind: str
    reason: str
    offer: str


def _results(s: Session, business_id: int, since: datetime) -> str:
    """What the AI did since `since`, in a few words: the thing to say on the phone."""
    talks = s.exec(select(func.count()).select_from(Conversation).where(
        Conversation.business_id == business_id, real_conversation(), Conversation.created_at >= since)).one()
    done = sum(s.exec(select(func.count()).select_from(model).where(
        model.business_id == business_id, not_test(model, business_id), model.created_at >= since)).one()
        for model in (Booking, Lead, Order))
    if not talks and not done:
        return "настоящих клиентов ещё не было"
    return f"{talks} диалогов с клиентами, {done} записей, заказов и заявок"


def _setup_step(s: Session, b: Business, now: datetime) -> tuple[int, int, str] | None:
    """(done, total, the first step not done) of the «Запуск» checklist, or None when it is all done."""
    from .web.saas import checklist  # the checklist the owner sees; it lives with the panel

    steps = checklist(s, b, now)
    left = [step for step in steps if not step["done"]]
    return (len(steps) - len(left), len(steps), left[0]["title"]) if left else None


def calls(s: Session, now: datetime) -> list[Call]:
    rows = s.exec(select(Business, Subscription).join(Subscription, Subscription.business_id == Business.id)
                  .where(Business.slug.not_like(f"{DEMO_PREFIX}%"))).all()
    out: list[Call] = []
    for b, sub in rows:
        if sub.status == "suspended" or sub.plan == "free" or sub.cancelled_at is not None:
            continue
        st = billing.state(sub, now)
        phone = (sub.contact_phone or b.phone).replace(" ", "\u00a0")  # a number is not broken across lines
        who = ", ".join(x for x in (sub.contact_name, phone) if x) or "контакта нет: откройте панель"
        waiting = billing.pending_transfer(s, b.id, now)
        end, paid = billing.last_end(sub)
        local_end = utc_to_local(end, DEFAULT_TZ) if end else None
        if st.code in ("active", "trial") and st.days_left <= 3 and not waiting and local_end:
            what = "Оплаченный период" if st.code == "active" else "Пробный период"
            since = sub.created_at if st.code == "trial" else end - timedelta(days=30)
            out.append(Call(b.id, b.name, who, "ends",
                            f"{what} заканчивается {local_end:%d.%m} (осталось {st.days_left} дн.). "
                            f"За это время: {_results(s, b.id, since)}.",
                            "Предложите оплату или год." if st.code == "trial" else "Напомните продлить."))
            continue
        if st.code == "expired" and not waiting and end and now - (end + timedelta(days=billing.GRACE_DAYS)) <= timedelta(days=STOPPED_DAYS):
            stop = utc_to_local(end + timedelta(days=billing.GRACE_DAYS), DEFAULT_TZ)
            out.append(Call(b.id, b.name, who, "stopped",
                            f"ИИ остановлен {stop:%d.%m}: {'оплаченный' if paid else 'пробный'} период закончился. "
                            f"За {'месяц' if paid else 'пробный период'}: {_results(s, b.id, sub.created_at if not paid else end - timedelta(days=30))}.",
                            "Верните: оплата — и ИИ сразу отвечает; один мастер — бесплатный тариф."))
            continue
        age = (now - sub.created_at).days
        if st.code == "trial" and SETUP_DAYS[0] <= age <= SETUP_DAYS[1]:
            step = _setup_step(s, b, now)
            if step:
                done, total, first = step
                out.append(Call(b.id, b.name, who, "setup",
                                f"Не закончил настройку: {done} из {total}, дальше «{first}». Зарегистрировался {age} дн. назад.",
                                "Предложите помочь: настройка «под ключ» или 10 минут по телефону."))
    return sorted(out, key=lambda c: (KINDS.index(c.kind), c.name))


def text(found: list[Call], console_url: str = "") -> str:
    lines = [f"Joop AI: позвонить сегодня ({len(found)})."]
    for i, c in enumerate(found, 1):
        lines.append(f"{i}. «{c.name}» — {c.who}. {c.reason} {c.offer}")
    if console_url:
        lines.append(f"Консоль: {console_url}")
    return "\n".join(lines)


def due(s: Session, now: datetime) -> bool:
    local = utc_to_local(now, DEFAULT_TZ)
    if local.hour < SEND_HOUR:
        return False
    return s.exec(select(FounderCallList.id).where(FounderCallList.day == local.date())).first() is None


def maybe_send(s: Session, rt, now: datetime) -> FounderCallList | None:
    """Every morning after 10:00 Bishkek, once: the list to the founder's Telegram, when there is anyone to call."""
    if not due(s, now):
        return None
    found = calls(s, now)
    base = rt.settings.public_base_url.rstrip("/")
    row = FounderCallList(day=utc_to_local(now, DEFAULT_TZ).date(), count=len(found),
                          text=text(found, f"{base}/owner" if base else "") if found else "")
    s.add(row)
    s.commit()  # the lock first: a failed send is not repeated, the list is on /owner anyway
    if found:
        try:
            row.sent = bool(health.tell_founder(rt, row.text))
        except Exception:
            log.exception("The founder's call list was not sent")
        s.add(row)
        s.commit()
    return row
