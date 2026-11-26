"""The owner hears that the AI is about to stop before it does, and staff see who writes after (joop/period_end.py).

Before: a trial ran out in silence, the AI stopped three days later, and a customer writing in Telegram or the site
chat — chats only the bot reads — was seen by nobody.
"""

import dataclasses
from datetime import datetime, timedelta

from sqlmodel import select

from joop import billing, db
from joop.agent.engine import handle_incoming
from joop.channels.base import IncomingMessage
from joop.models import Business, Payment, Staff, Subscription
from joop.scheduler import run_due_jobs
from joop.stats import TEST_CHANNEL

from .conftest import FakeLLM

START = datetime(2026, 11, 2, 6, 0)  # 12:00 in Bishkek: sign-up
TRIAL_ENDS = START + timedelta(days=14)  # 16.11 12:00 in Bishkek


def morning(day: int) -> datetime:
    """08:30 in Bishkek on the given November day: the morning summary's hour."""
    return datetime(2026, 11, day, 2, 30)


def setup(business_id, *, cancelled=False, free=False, staff=2):
    with db.new_session() as s:
        b = s.get(Business, business_id)
        b.admin_chat_ids = "-5001"
        for i in range(staff):
            s.add(Staff(business_id=b.id, name=f"Мастер {i}", role="мастер"))
        sub = billing.start_trial(s, b, 14, START)
        if cancelled:
            billing.cancel(sub, START + timedelta(days=1))
        if free:
            sub.plan = "free"
        s.commit()


def summary(business_id, rt, day: int) -> str | None:
    """The owner's notice in that morning's summary, if any."""
    before = len(rt.tg.sent)
    with db.new_session() as s:
        run_due_jobs(s, rt, s.get(Business, business_id), morning(day))
        s.commit()
    notes = [text for chat, text in rt.tg.sent[before:] if chat == "-5001" and "Оплатить" in text]
    assert len(notes) <= 1
    return notes[0] if notes else None


def test_the_owner_is_told_at_each_step_once(business, rt):
    setup(business.id)
    assert summary(business.id, rt, 13) is None  # four days left: nothing yet
    soon = summary(business.id, rt, 14)
    assert soon.startswith("Пробный период «Ак-Тиш Дент» заканчивается 16.11 в 12:00 — осталось 3 дня. "
                           "Без оплаты ИИ ответит клиентам ещё 3 дня, а 19.11 остановится.")
    assert "Оплатить: https://joop.test/panel/billing" in soon
    assert summary(business.id, rt, 15) is None  # said once
    assert summary(business.id, rt, 16).startswith("Пробный период «Ак-Тиш Дент» заканчивается 16.11 в 12:00 — осталось 1 день.")
    waiting = summary(business.id, rt, 17)
    assert waiting.startswith("Пробный период «Ак-Тиш Дент» закончился 16.11. ИИ отвечает клиентам до 19.11 12:00, "
                              "потом остановится: клиенты в Telegram и в чате на сайте останутся без ответа.")
    assert summary(business.id, rt, 18) is None
    stopped = summary(business.id, rt, 20)
    assert stopped.startswith("ИИ-администратор «Ак-Тиш Дент» остановлен 19.11: пробный период закончился.")
    assert "их сообщения из Telegram и с сайта будут приходить сюда" in stopped
    assert summary(business.id, rt, 21) is None and summary(business.id, rt, 27) is None


def test_a_payment_starts_the_count_again(business, rt):
    setup(business.id)
    assert summary(business.id, rt, 14)
    with db.new_session() as s:
        payment = Payment(business_id=business.id, amount_som=1500, period_days=30, method="manual", status="pending")
        s.add(payment)
        s.commit()
        billing.mark_paid(s, payment, morning(15))  # paid early: 30 days on top of the trial
        s.commit()
        paid_until = billing.get_subscription(s, business.id).paid_until
    assert summary(business.id, rt, 16) is None  # the trial's end no longer matters
    end_day = (paid_until - timedelta(days=3)).day
    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.last_digest_date = ""
        s.commit()
    with db.new_session() as s:  # three days before the paid month ends
        run_due_jobs(s, rt, s.get(Business, business.id), datetime(paid_until.year, paid_until.month, end_day, 2, 30))
        s.commit()
    assert rt.tg.sent[-1][1].startswith("Оплаченный период «Ак-Тиш Дент» заканчивается")


def test_the_summary_leads_with_it(business, rt, settings):
    rt.settings = dataclasses.replace(settings, price_som=1500)
    setup(business.id)
    before = len(rt.tg.sent)
    with db.new_session() as s:
        run_due_jobs(s, rt, s.get(Business, business.id), morning(14))
        s.commit()
    first = [text for chat, text in rt.tg.sent[before:] if chat == "-5001"][0]
    assert first.startswith("Пробный период") and "Оплатить (1 500 сом в месяц): https://joop.test/panel/billing" in first


def alone(business_id):
    """One master left: the others of the demo data stop working here."""
    with db.new_session() as s:
        for i, row in enumerate(s.exec(select(Staff).where(Staff.business_id == business_id)).all()):
            row.active = i == 0
            s.add(row)
        s.commit()


def test_one_master_is_offered_the_free_plan(business, rt):
    setup(business.id, staff=0)
    alone(business.id)
    assert "можно перейти на бесплатный тариф" in summary(business.id, rt, 14)


def test_nothing_after_a_cancellation_or_on_the_free_plan(business, rt):
    """Cancelling promises no reminders to pay; the free plan never ends."""
    setup(business.id, cancelled=True)
    assert [summary(business.id, rt, day) for day in (14, 16, 17, 20)] == [None] * 4


def test_nothing_on_the_free_plan(business, rt):
    setup(business.id, free=True, staff=0)
    alone(business.id)
    assert [summary(business.id, rt, day) for day in (14, 16, 17, 20)] == [None] * 4


def test_a_business_stopped_long_ago_is_not_told_today(business, rt):
    """Businesses whose trial ended before this existed: a «stopped» notice weeks late would be news from the past."""
    setup(business.id)
    assert summary(business.id, rt, 27) is None


def say(business_id, text, channel="telegram", chat="700", when=morning(20) + timedelta(hours=4)):
    with db.new_session() as s:
        out = handle_incoming(s, s.get(Business, business_id), IncomingMessage(channel, chat, "text", text, "Айбек", f"m{chat}{text}"),
                              lambda: FakeLLM(), when, base_url="https://joop.test")
        s.commit()
        return out


def test_after_the_stop_staff_see_who_writes_where_only_the_bot_reads(business):
    setup(business.id)
    out = say(business.id, "Здравствуйте, можно записаться на завтра?")
    assert out.skipped == "subscription" and out.reply is None
    (note,) = out.admin_notes
    assert note.startswith("Айбек пишет (Telegram): «Здравствуйте, можно записаться на завтра?»\n"
                           "ИИ не отвечает: пробный период закончился и не оплачен. Ответить: https://joop.test/panel/conversations/")
    assert note.endswith("Оплатить: https://joop.test/panel/billing")
    site = say(business.id, "Есть свободное время?", channel="web", chat="web-" + "a" * 24)
    assert len(site.admin_notes) == 1 and "(чат на сайте)" in site.admin_notes[0]
    # WhatsApp and Instagram: staff see the message in their own app; the owner's test chat is the owner's own
    assert say(business.id, "Салам", channel="whatsapp", chat="996555000111").admin_notes == []
    assert say(business.id, "проверка", channel=TEST_CHANNEL, chat="test").admin_notes == []


def test_while_the_ai_still_answers_there_is_no_note(business):
    setup(business.id)
    out = say(business.id, "Здравствуйте", when=morning(17))  # the waiting days: the AI answers
    assert out.skipped == "" and out.reply and out.admin_notes == []


def test_the_reason_says_what_stopped_it(business):
    setup(business.id, cancelled=True)
    with db.new_session() as s:
        assert s.exec(select(Subscription)).one().cancelled_at is not None
    note = say(business.id, "Здравствуйте", when=morning(17)).admin_notes[0]  # cancelled: no waiting days
    assert "ИИ не отвечает: подписка отменена." in note
