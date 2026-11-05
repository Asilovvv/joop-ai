"""Background jobs: reminders the day before an appointment and the morning summary for staff."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, time, timedelta

from sqlmodel import Session, select

from . import altegio, billing, broadcasts, cash, confirm, crm, deposits, founder_digest, funnel, health, nudges, ops, recovery, trust, unfinished
from . import gaps as empty_slots
from .db import new_session
from .dispatch import notify_admins
from .faq_gaps import SHOWN as GAPS_SHOWN, open_gaps
from .followups import _kyrgyz, send_return_invites, send_review_requests
from .models import Booking, Business, Conversation, Message
from .runtime import Runtime
from .stats import TEST_CHANNEL, activity, real_messages
from .timeutil import fmt_slot, utc_to_local, utcnow

log = logging.getLogger(__name__)

JOB_WINDOW_HOURS = 3  # a job may run late (server restart), but not at night
SERVICE_WINDOW = timedelta(hours=23)  # Meta allows free-form messages within 24h of the customer's last message
TOKEN_REFRESH_EVERY = timedelta(days=7)  # Instagram user tokens expire after 60 days unless refreshed


def _due(hour_now: int, target: int) -> bool:
    return target <= hour_now < target + JOB_WINDOW_HOURS


def reminder_text(business: Business, booking: Booking, kyrgyz: bool = False) -> str:
    if kyrgyz:
        parts = [f"Эскертебиз: эртең, {confirm.fmt_slot_ky(booking.start)}, сиз «{business.name}» жазылгансыз"]
        if booking.service:
            parts[0] += f" ({booking.service})"
        if booking.staff_name:
            parts.append(f"Адис: {booking.staff_name}")
        if business.address:
            parts.append(f"Дарек: {business.address}")
        return ". ".join(parts) + ". " + confirm.ASK_KY
    parts = [f"Напоминаем: завтра, {fmt_slot(booking.start)}, вы записаны в «{business.name}»"]
    if booking.service:
        parts[0] += f" ({booking.service})"
    if booking.staff_name:
        parts.append(f"Специалист: {booking.staff_name}")
    if business.address:
        parts.append(f"Адрес: {business.address}")
    return ". ".join(parts) + ". " + confirm.ASK_RU


def _send_reminder(session: Session, rt: Runtime, business: Business, booking: Booking, now_utc: datetime) -> str:
    """"sent": the text with the question went out; "template": the approved WhatsApp template, which asks nothing; "": nothing."""
    conv = session.get(Conversation, booking.conversation_id) if booking.conversation_id else None
    text = reminder_text(business, booking, bool(conv) and _kyrgyz(session, conv.id))
    in_window = bool(conv and conv.last_customer_at and now_utc - conv.last_customer_at < SERVICE_WINDOW)
    sent = ""
    if booking.channel == "telegram" or (booking.channel in {"whatsapp", "instagram"} and in_window):
        client = rt.channel_client(business, booking.channel)
        sent = "sent" if client and client.send_text(booking.chat_id, text) else ""
    if not sent and booking.channel == "whatsapp" and business.wa_reminder_template:
        # Outside the 24-hour window WhatsApp only allows approved templates.
        client = rt.whatsapp(business)
        params = [booking.customer_name or "клиент", fmt_slot(booking.start), booking.staff_name or business.name]
        sent = "template" if client and client.send_template(booking.chat_id, business.wa_reminder_template, business.wa_template_lang, params) else ""
    if sent == "sent" and conv is not None:
        session.add(Message(business_id=business.id, conversation_id=conv.id, role="ai", text=text, created_at=now_utc))
    return sent


def send_reminders(session: Session, rt: Runtime, business: Business, now_utc: datetime) -> dict[str, int]:
    now_local = utc_to_local(now_utc, business.timezone)
    day = datetime.combine((now_local + timedelta(days=1)).date(), time.min)
    bookings = session.exec(
        select(Booking)
        .where(
            Booking.business_id == business.id,
            Booking.status == "booked",
            Booking.start >= day,
            Booking.start < day + timedelta(days=1),
            Booking.reminder_status == "",
            Booking.channel != TEST_CHANNEL,  # a test booking has nobody to remind: no "remind by hand" note either
        )
        .order_by(Booking.start)
    ).all()
    manual: list[Booking] = []
    for booking in bookings:
        ok = _send_reminder(session, rt, business, booking, now_utc)
        booking.reminder_status = ok or "manual"
        session.add(booking)
        if not ok:
            manual.append(booking)
    if manual:
        lines = ["Напомните вручную о записи на завтра:"]
        lines += [f"{b.start:%H:%M} — {b.customer_name}, {b.customer_phone or 'телефон не указан'} ({b.staff_name})" for b in manual]
        notify_admins(rt, business, ["\n".join(lines)])
    return {"sent": len(bookings) - len(manual), "manual": len(manual)}


def digest_text(session: Session, business: Business, now_utc: datetime) -> str | None:
    stats = activity(session, business.id, now_utc - timedelta(hours=24))
    now_local = utc_to_local(now_utc, business.timezone)
    day = datetime.combine(now_local.date(), time.min)
    today = session.exec(
        select(Booking)
        .where(
            Booking.business_id == business.id,
            Booking.status == "booked",
            Booking.start >= day,
            Booking.start < day + timedelta(days=1),
            Booking.channel != TEST_CHANNEL,
        )
        .order_by(Booking.start)
    ).all()
    if not stats["conversations"] and not stats["leads"] and not today:
        return None
    lines = [
        f"Сводка «{business.name}» на {now_local:%d.%m}",
        f"За сутки: диалогов {stats['conversations']} (в нерабочее время {stats['off_hours_conversations']}), "
        f"записей через ИИ {stats['bookings']} (в нерабочее время {stats['off_hours_bookings']}), "
        f"заявок администратору {stats['leads']}.",
    ]
    still_open = nudges.open_count(session, business, now_utc)
    if still_open:
        lines.append(f"Не закрыто заявок: {still_open} — ответьте клиентам и отметьте «Готово» в разделе «Заявки».")
    silent = confirm.unconfirmed(today)
    if silent:
        lines.append(confirm.digest_line(silent))
    money = cash.digest_line(session, business, now_local)
    if money:
        lines.append(money)
    if today:
        lines.append("Сегодня записаны:")
        lines += [f"{b.start:%H:%M} — {b.customer_name}, {b.customer_phone} — {b.service or 'приём'} ({b.staff_name})"
                  + (" ✓" if b.confirmed_at else "") for b in today]
    else:
        lines.append("Записей на сегодня в системе нет.")
    return "\n".join(lines)


def weekly_report_text(session: Session, business: Business, now_utc: datetime) -> str | None:
    """Monday report for the owner: what the AI did in 7 days, so the value of the subscription is visible."""
    st = activity(session, business.id, now_utc - timedelta(days=7))
    if not st["conversations"]:
        return None
    results = st["bookings"] + st["requests"] + st["orders"]
    lines = [
        f"Итоги недели «{business.name}»: ИИ-администратор",
        f"Ответил {st['conversations']} клиентам, из них {st['off_hours_conversations']} — в нерабочее время, когда никого не было на месте.",
    ]
    parts = []
    if st["bookings"]:
        parts.append(f"записей {st['bookings']} (ночью и в выходные: {st['off_hours_bookings']})")
    if st["requests"]:
        parts.append(f"заявок на запись {st['requests']}")
    if st["orders"]:
        parts.append(f"заказов {st['orders']}")
    if parts:
        lines.append("Оформил: " + ", ".join(parts) + ".")
    if st["leads"]:
        lines.append(f"Передал вам {st['leads']} вопросов, на которые нужен человек.")
    invited, returned = empty_slots.week_numbers(session, business, now_utc - timedelta(days=7))
    if invited:
        lines.append(f"Пригласили в пустые окна: {invited}, записались: {returned}.")
    chased, came = unfinished.week_numbers(session, business, now_utc - timedelta(days=7))
    if chased:
        lines.append(f"Напомнили о себе {_ru(chased, 'клиенту', 'клиентам', 'клиентам')}, "
                     f"{'который спросил и замолчал' if chased == 1 else 'которые спросили и замолчали'}; записались после этого: {came}.")
    if results:
        lines.append(f"Итого {results} готовых обращений без участия администратора.")
    gaps = open_gaps(session, business, now_utc)
    if gaps:
        many = "не меньше " if len(gaps) >= GAPS_SHOWN else ""
        lines.append(f"Вопросы клиентов, на которые у ИИ не было ответа: {many}{len(gaps)} (панель, раздел «Вопросы»). "
                     "Ответьте один раз — и дальше ИИ будет отвечать на них сам.")
    return "\n".join(lines)


MONTHS = ("январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь")


def _som(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def _ru(n: int, one: str, few: str, many: str) -> str:
    """Russian plural: 1 запись, 2 записи, 5 записей (11–14 take the "many" form)."""
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} {one}"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return f"{n} {few}"
    return f"{n} {many}"


def monthly_report_text(session: Session, business: Business, now_utc: datetime) -> str | None:
    """On the 1st: what the AI did last month and what it brought, valued at the business's own prices.

    Only exact prices count: a booking whose service has one price in the price list, and orders whose total
    the code computed. Bookings without such a price are named, not guessed."""
    from sqlalchemy import func

    from .models import Lead, Order, Service
    from .timeutil import local_to_utc

    from .timeutil import local_to_utc

    now_local = utc_to_local(now_utc, business.timezone)
    first_this = datetime.combine(now_local.date().replace(day=1), time.min)
    first_last = (first_this - timedelta(days=1)).replace(day=1)
    since, until = local_to_utc(first_last, business.timezone), local_to_utc(first_this, business.timezone)
    lines = period_lines(session, business, since, until)
    if lines is None:
        return None
    return "\n".join([f"Итоги за {MONTHS[first_last.month - 1]} «{business.name}»: ИИ-администратор", *lines])


def period_lines(session: Session, business: Business, since: datetime, until: datetime) -> list[str] | None:
    """What the AI did between two UTC moments, valued at the business's own prices; None when nobody wrote.

    Only exact prices count: a booking whose service has one price in the price list, and orders whose total
    the code computed. Bookings without such a price are named, not guessed."""
    from sqlalchemy import func

    from .models import Lead, Order, Service

    window = (Message.business_id == business.id, Message.role == "customer", Message.created_at >= since, Message.created_at < until,
              real_messages(business.id))
    conversations = session.exec(select(func.count(func.distinct(Message.conversation_id))).where(*window)).one() or 0
    if not conversations:
        return None
    off_conversations = session.exec(select(func.count(func.distinct(Message.conversation_id))).where(
        *window, Message.off_hours == True)).one() or 0  # noqa: E712
    handoffs = session.exec(select(func.count()).select_from(Lead).where(
        Lead.business_id == business.id, Lead.kind == "handoff", Lead.created_at >= since, Lead.created_at < until,
        Lead.channel != TEST_CHANNEL)).one() or 0
    prices = {s.name.casefold(): s.price_value for s in session.exec(select(Service).where(
        Service.business_id == business.id, Service.price_value != None)).all()}  # noqa: E711
    bookings = session.exec(select(Booking).where(Booking.business_id == business.id, Booking.source == "ai",
                                                  Booking.created_at >= since, Booking.created_at < until,
                                                  Booking.channel != TEST_CHANNEL)).all()
    valued = []
    for b in bookings:  # an accepted add-on (joop/upsell.py) is "Маникюр + Дизайн": the base price plus the add-on's
        name, extra = b.service or "", 0
        if b.upsell_status == "accepted" and " + " in name:
            name, extra = name.rsplit(" + ", 1)[0], b.upsell_price
        if name and name.casefold() in prices:
            valued.append(prices[name.casefold()] + extra)
    added = [b for b in bookings if b.upsell_status == "accepted"]
    orders = session.exec(select(Order).where(Order.business_id == business.id, Order.created_at >= since,
                                              Order.created_at < until, Order.status != "cancelled",
                                              Order.channel != TEST_CHANNEL)).all()
    order_sum = sum(o.total for o in orders if o.total)
    total = sum(valued) + order_sum
    lines = [f"Ответил {_ru(conversations, 'клиенту', 'клиентам', 'клиентам')}, из них {off_conversations} — в нерабочее время."]
    off_bookings = sum(1 for b in bookings if b.created_off_hours)
    if bookings:
        lines.append(f"Записал сам {_ru(len(bookings), 'клиента', 'клиентов', 'клиентов')}"
                     + (f", из них {off_bookings} — ночью и в выходные." if off_bookings else "."))
    if orders:
        lines.append(f"Оформил заказов: {len(orders)}.")
    if total:
        rest = len(bookings) - len(valued)
        lines.append(f"По ценам вашего прайса это около {_som(total)} сом"
                     + (f" (ещё {_ru(rest, 'запись', 'записи', 'записей')} — услуги без точной цены, не посчитаны)." if rest > 0 else "."))
    if added:
        lines.append(f"Допродажа: {_ru(len(added), 'дополнительная услуга', 'дополнительные услуги', 'дополнительных услуг')} "
                     f"к записям — ещё {_som(sum(b.upsell_price for b in added))} сом.")
    if handoffs:
        lines.append(f"Передал вам {_ru(handoffs, 'вопрос', 'вопроса', 'вопросов')}, на которые нужен человек.")
    return lines


def first_week_report_text(session: Session, business: Business, now_utc: datetime, price_som: int = 0) -> str | None:
    """Once, on the morning after the seventh day with real customers: the week in numbers and what it would cost.

    The strategy's day-7 report: by the end of the trial week the owner has a figure, not a feeling. Sent once
    (Business.first_week_report_at); nothing when nobody wrote."""
    started = trust.first_live_at(session, business)
    if started is None or business.first_week_report_at is not None or now_utc - started < timedelta(days=7):
        return None
    lines = period_lines(session, business, started, now_utc)
    if lines is None:
        return None
    sub = billing.get_subscription(session, business.id)
    st = billing.state(sub, now_utc) if sub else None
    tail = []
    if st and st.code == "trial":
        tail.append(f"Пробный период: ещё {_ru(st.days_left, 'день', 'дня', 'дней')}.")
    if st and st.code == "free":
        tail.append("Вы на бесплатном тарифе для одного мастера — без срока.")
    elif sub and sub.cancelled_at and sub.trial_ends_at:
        tail.append(f"Подписка отменена: ИИ остановится {utc_to_local(sub.trial_ends_at, business.timezone):%d.%m}. "
                    "Передумаете — «Возобновить» в панели, раздел «Оплата».")
    elif price_som:
        tail.append(f"Подписка — {_som(price_som)} сом в месяц, отменить можно в любой момент: панель → «Оплата».")
    tail.append("Если что-то отвечает не так — впишите ответ в «Вопросы» или напишите мне, поправлю в тот же день.")
    business.first_week_report_at = now_utc
    return "\n".join([f"Первая неделя с ИИ-администратором «{business.name}» — итоги", *lines, *tail])


def refresh_instagram_token(rt: Runtime, business: Business, now_utc: datetime) -> bool | None:
    """Swap the Instagram token for a fresh one weekly. None = nothing to do, False = failed (retry tomorrow)."""
    if not business.ig_access_token:
        return None
    last = business.ig_token_refreshed_at
    if last is not None and now_utc - last < TOKEN_REFRESH_EVERY:
        return None
    client = rt.instagram(business)
    if client is None:
        return None
    token = client.refresh_token()
    if token:
        business.ig_access_token = token
        business.ig_token_refreshed_at = now_utc
        return True
    business.ig_token_refreshed_at = now_utc - TOKEN_REFRESH_EVERY + timedelta(days=1)
    log.warning("Instagram token for %s was not refreshed; will retry tomorrow", business.slug)
    return False


def sync_altegio(session: Session, rt: Runtime, business: Business, now_utc: datetime) -> bool:
    """Refresh prices, team and free times from Altegio; a failure is kept for the panel and retried next time."""
    client = rt.altegio(business)
    if client is None:
        business.altegio_error = "Нет ключа Altegio: задайте ALTEGIO_PARTNER_TOKEN на сервере или ключ салона в панели."
        business.altegio_synced_at = now_utc
        session.add(business)
        return False
    try:
        with session.begin_nested():
            altegio.sync(session, business, client, now_utc)
        return True
    except altegio.AltegioError as exc:
        log.warning("Altegio sync for %s failed: %s", business.slug, exc)
        business.altegio_error = f"Altegio не ответил ({exc.status or 'нет связи'}). Повторим через 10 минут."
        business.altegio_synced_at = now_utc
        session.add(business)
        return False


def run_due_jobs(session: Session, rt: Runtime, business: Business, now_utc: datetime) -> dict:
    """Every due job for one business. Each job is committed on its own as soon as it is done: a job that has
    already sent messages (reminders, broadcasts, released bookings) must keep its marks even if a later job in
    the same round fails, otherwise the next round would send the same messages again."""
    now_local = utc_to_local(now_utc, business.timezone)
    today = now_local.date().isoformat()
    report: dict = {}

    def step(name: str, job) -> None:
        try:
            value = job()
        except Exception:
            session.rollback()
            log.exception("Scheduled job %s failed for %s", name, business.slug)
            return
        if value is not None and value != {} and not (value == 0 and value is not False):
            report[name] = value  # None, {} and 0 mean "nothing to do"; False means "tried and failed"
        session.add(business)
        session.commit()

    def reminders():
        if not (_due(now_local.hour, business.reminder_hour) and business.last_reminder_date != today):
            return None
        business.last_reminder_date = today
        report["reminders"] = send_reminders(session, rt, business, now_utc)
        report["returns"] = send_return_invites(session, rt, business, now_utc)
        return None

    def digest():
        if not (_due(now_local.hour, business.digest_hour) and business.last_digest_date != today):
            return None
        business.last_digest_date = today
        texts = [t for t in [digest_text(session, business, now_utc),
                             trust.week_one_review(session, business, now_utc, rt.settings.public_base_url)] if t]
        if now_local.weekday() == 0:  # Monday: the week in numbers
            weekly = weekly_report_text(session, business, now_utc)
            if weekly:
                texts.append(weekly)
                report["weekly"] = True
        week = first_week_report_text(session, business, now_utc, rt.settings.price_som)
        if week:
            texts.append(week)
            report["first_week"] = True
        if now_local.day == 1:  # the 1st: last month and what it brought
            monthly = monthly_report_text(session, business, now_utc)
            if monthly:
                texts.append(monthly)
                report["monthly"] = True
        report["digest"] = bool(texts) and notify_admins(rt, business, texts) > 0
        return None

    def push_crm():
        client = rt.crm(business)
        return crm.push_due(session, client, business, now_utc, rt.settings.public_base_url) if client is not None else None

    # first: customers an outage left waiting get their answer before staff are reminded about their requests
    step("answered_after_outage", lambda: recovery.answer_waiting(session, rt, business, now_utc))
    step("reminders_round", reminders)
    step("digest_round", digest)
    step("nudged", lambda: nudges.send(session, rt, business, now_utc))
    step("deposits", lambda: deposits.check_deadlines(session, rt, business, now_utc))
    step("unconfirmed", lambda: confirm.release_unconfirmed(session, rt, business, now_utc))
    step("unfinished", lambda: unfinished.send_due(session, rt, business, now_utc))
    step("funnel", lambda: funnel.advance(session, business, now_utc))
    step("broadcast", lambda: broadcasts.send_due(session, rt, business, now_utc))
    step("reviews", lambda: send_review_requests(session, rt, business, now_utc))
    step("crm", push_crm)
    step("altegio", lambda: sync_altegio(session, rt, business, now_utc) if altegio.due(business, now_utc) else None)
    step("instagram_token", lambda: refresh_instagram_token(rt, business, now_utc))
    return report


class Scheduler(threading.Thread):
    """Runs due jobs for every active business every `interval` seconds."""

    def __init__(self, rt: Runtime, interval: int) -> None:
        super().__init__(daemon=True, name="joop-scheduler")
        self.rt = rt
        self.interval = interval
        self._stop = threading.Event()

    def tick(self, now_utc: datetime | None = None) -> None:
        with new_session() as session:
            ids = session.exec(select(Business.id).where(Business.bot_enabled == True)).all()  # noqa: E712
        for business_id in ids:
            with new_session() as session:
                business = session.get(Business, business_id)
                try:
                    run_due_jobs(session, self.rt, business, now_utc or utcnow())
                    session.commit()
                except Exception:
                    session.rollback()
                    log.exception("Scheduled jobs failed for business %s", business_id)
        with new_session() as session:
            try:
                health.maybe_alert(session, self.rt, now_utc or utcnow())
            except Exception:
                log.exception("Founder alert check failed")
        with new_session() as session:  # Monday: the founder's one line a week
            try:
                founder_digest.maybe_send(session, self.rt, now_utc or utcnow())
            except Exception:
                session.rollback()
                log.exception("Founder digest failed")
        try:  # one consistent copy of the database a day (joop/ops.py)
            if ops.backup_due(self.rt.settings, now_utc or utcnow()):
                ops.make_backup(self.rt.settings, now_utc or utcnow())
        except Exception:
            log.exception("Daily database backup failed")

    def run(self) -> None:  # pragma: no cover - thread loop
        while not self._stop.wait(5):
            self.tick()
            if self._stop.wait(self.interval):
                break

    def stop(self) -> None:
        self._stop.set()
