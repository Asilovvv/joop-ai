"""Findings of the independent review of PRs #80–#85, each closed with a test."""

import dataclasses
from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlmodel import select

from joop import billing, db, founder_digest, free_plan, health
from joop.agent.llm import AgentReply
from joop.models import Booking, Business, Conversation, FounderDigest, Payment, Staff, Subscription
from joop.scheduler import Scheduler, first_week_report_text
from joop.web.app import create_app

from .conftest import NOW_UTC, FakeLLM
from .test_free_plan import _one_master, say
from .test_pilot import activity
from .test_saas import app_client, owner_login, saas_settings  # noqa: F401  (fixtures)
from .test_web import login


def test_paying_after_a_cancellation_resumes(business):
    """Finding 1: a payment is the strongest "resume"; the paid month must not run labelled «Отменена»."""
    with db.new_session() as s:
        sub = billing.start_trial(s, s.get(Business, business.id), 14, NOW_UTC)
        billing.cancel(sub, NOW_UTC, "подумаю")
        payment = Payment(business_id=business.id, amount_som=3000, method="manual", period_days=30)
        s.add(payment)
        s.flush()
        billing.mark_paid(s, payment, NOW_UTC + timedelta(days=3))
        s.commit()
        sub = s.exec(select(Subscription)).one()
        assert sub.cancelled_at is None and sub.cancel_reason == ""
        assert billing.state(sub, NOW_UTC + timedelta(days=5)).label == "Оплачено"
        assert billing.state(sub, sub.paid_until + timedelta(days=1)).code == "grace"  # the grace period is back


def test_free_plan_with_more_masters_stops_the_ai_instead_of_bending(business, rt):
    """Finding 2: Altegio sync or a profile import can add masters past the limit; the AI then waits, data stays."""
    _one_master(business.id)
    with db.new_session() as s:
        free_plan.switch(billing.start_trial(s, s.get(Business, business.id), 14, NOW_UTC))
        s.commit()
        assert billing.access_ok(s, business.id, NOW_UTC)
        second = s.exec(select(Staff).where(Staff.business_id == business.id, Staff.active == False)).first()  # noqa: E712
        second.active = True  # what an Altegio sync does
        s.add(second)
        s.commit()
        assert not billing.access_ok(s, business.id, NOW_UTC)
        assert billing.state(billing.get_subscription(s, business.id), NOW_UTC).label == "Бесплатно: один мастер"
    rt._llm = FakeLLM([AgentReply("Чем помочь?")])
    assert say(business.id, rt, "Привет").skipped == "subscription"


def test_billing_page_explains_why_the_free_plan_waits(business, app_client):
    with db.new_session() as s:
        free_plan.switch(billing.start_trial(s, s.get(Business, business.id), 14, NOW_UTC))  # three masters
        s.commit()
    login(app_client)
    page = app_client.get("/panel/billing").text
    assert "На бесплатном тарифе один мастер" in page and "ИИ сейчас не отвечает" in page


def test_digest_is_written_later_in_the_week_when_monday_was_missed(engine, rt, saas_settings):
    """Finding 3: a server down on Monday must not leave a hole in the journal."""
    rt.settings = saas_settings
    tuesday = datetime(2026, 11, 10, 6, 0)  # Tuesday 12:00 Bishkek, nothing written on Monday
    Scheduler(rt, interval=60).tick(tuesday)
    with db.new_session() as s:
        [row] = s.exec(select(FounderDigest)).all()
        assert row.week_start == datetime(2026, 11, 2).date()
    Scheduler(rt, interval=60).tick(tuesday + timedelta(days=1))
    with db.new_session() as s:
        assert len(s.exec(select(FounderDigest)).all()) == 1  # still one line for that week
    with db.new_session() as s:
        assert not founder_digest.due(s, datetime(2026, 11, 16, 2, 0))  # next Monday 08:00: before the hour


def test_checklist_counts_the_free_plan_as_settled(business, app_client):
    """Finding 4: the launch checklist's «Оплата» item is done on the free plan."""
    _one_master(business.id)
    with db.new_session() as s:
        free_plan.switch(billing.start_trial(s, s.get(Business, business.id), 14, NOW_UTC))
        s.commit()
    login(app_client)
    page = app_client.get("/panel/setup").text
    assert "Бесплатный тариф: один мастер, без срока" in page


def test_telegram_start_greeting_carries_the_free_signature(business, rt):
    """Finding 5: on Telegram the first contact is /start, so the greeting is where the signature goes."""
    _one_master(business.id)
    with db.new_session() as s:
        free_plan.switch(billing.start_trial(s, s.get(Business, business.id), 14, NOW_UTC))
        s.commit()
    out = say(business.id, rt, "/start", "telegram", "1001")
    assert out.reply.endswith("\n\n— отвечает Joop AI, ИИ-администратор для бизнеса · https://joop.test/ai/aktish")
    rt._llm = FakeLLM([AgentReply("Чем помочь?")])
    assert say(business.id, rt, "Привет", "telegram", "1001").reply == "Чем помочь?"  # not twice


def test_the_founder_looking_in_does_not_count_as_the_owner_reviewing(business, app_client):
    """Finding 6: the week-one metric is about the owner, not the founder helping with setup."""
    with db.new_session() as s:
        conv = activity(s, s.get(Business, business.id), "996555000111", 1)
        s.commit()
        cid = conv.id
    token = owner_login(app_client)
    app_client.post(f"/owner/business/{business.id}", data={"csrf": token, "action": "login"})
    assert app_client.get(f"/panel/conversations/{cid}").status_code == 200
    with db.new_session() as s:
        assert s.get(Conversation, cid).reviewed_at is None


def test_free_plan_refused_while_paid_and_cancel_refused_on_free(business, app_client, rt, monkeypatch):
    """Finding 7: no switching to free with paid days left; nothing to cancel on the free plan."""
    _one_master(business.id)
    with db.new_session() as s:
        sub = billing.start_trial(s, s.get(Business, business.id), 14, NOW_UTC)
        sub.paid_until = NOW_UTC + timedelta(days=20)
        sub.status = "active"
        s.add(sub)
        s.commit()
    token = login(app_client)
    page = app_client.get("/panel/billing").text
    assert "Перейти на бесплатный" not in page and "после оплаченного периода" in page
    r = app_client.post("/panel/billing/free", data={"csrf": token})
    assert "оплаченный период" in r.text
    with db.new_session() as s:
        sub = s.exec(select(Subscription)).one()
        assert sub.plan == "pro"
        sub.paid_until, sub.status = None, "trial"
        free_plan.switch(sub)
        s.add(sub)
        s.commit()
    monkeypatch.setattr(health, "_send", lambda rt_, text: rt.tg.send_text("42", text))
    r = app_client.post("/panel/billing/cancel", data={"csrf": token, "reason": "x"})
    assert "На бесплатном тарифе нечего отменять" in r.text and not rt.tg.sent
    with db.new_session() as s:
        assert s.exec(select(Subscription)).one().cancelled_at is None


def test_day_seven_report_does_not_invite_a_cancelled_owner_to_cancel(business, rt):
    """Finding 8."""
    with db.new_session() as s:
        b = s.get(Business, business.id)
        sub = billing.start_trial(s, b, 14, NOW_UTC - timedelta(days=8))
        billing.cancel(sub, NOW_UTC - timedelta(days=1), "")
        for i, days in enumerate((8, 5, 3)):  # the first real customer wrote eight days ago
            activity(s, b, f"c{i}", days)
        s.commit()
        text = first_week_report_text(s, b, NOW_UTC) or ""
    assert "отменить можно в любой момент" not in text
    assert "Подписка отменена: ИИ остановится" in text


# --- the second review (PRs #88–#92) --------------------------------------------------------------


def test_a_yes_to_another_question_is_not_a_confirmation_and_a_payment_yes_goes_to_deposits(business, rt):
    """Findings 1 and 12: only a «да» right after the reminder's question confirms; «Да, перевела» is a payment; 👍 counts."""
    from datetime import datetime

    from joop import confirm
    from joop.agent.engine import handle_incoming
    from joop.channels.base import IncomingMessage
    from .test_scheduler import EVENING_UTC, _book, _run

    assert confirm.says_yes("👍") and confirm.says_yes("+") and confirm.says_yes("Да, приду")
    assert not confirm.says_yes("Да, запишите на 10:00") and not confirm.says_yes("Ок, а адрес какой") and not confirm.says_yes("да а сколько стоит")
    _book(business, "telegram", "1001")
    _run(business, rt)  # the reminder with the question

    def say(text, n, llm):
        with db.new_session() as s:
            out = handle_incoming(s, s.get(Business, business.id), IncomingMessage("telegram", "1001", "text", text, "Айбек", f"tg:1001:r{n}"),
                                  lambda: llm, EVENING_UTC + timedelta(minutes=n))
            s.commit()
            return out

    llm = FakeLLM([AgentReply("Есть Пт 06.11 15:00 — записать?"), AgentReply("Записала маму на пятницу.")])
    assert say("А можно ещё маме завтра?", 1, llm).reply == "Есть Пт 06.11 15:00 — записать?"
    assert say("да", 2, llm).reply == "Записала маму на пятницу."  # the AI asked something else: the model gets this «да»
    with db.new_session() as s:
        assert s.exec(select(Booking).where(Booking.channel == "telegram")).one().confirmed_at is None


def test_template_reminder_asks_nothing_so_nobody_is_blamed_for_silence(business, rt):
    """Finding 2: a WhatsApp template reminder is «template», not «sent»: no release, no «без ответа»."""
    from joop import confirm
    from joop.scheduler import digest_text
    from .test_scheduler import EVENING_UTC, _book, _run

    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.wa_phone_number_id, b.wa_access_token, b.wa_reminder_template, b.release_unconfirmed_hours = "pn1", "tok", "appointment_reminder", 12
        s.add(b)
        s.commit()
    _book(business, "whatsapp", "996555000111", minutes_ago_customer=48 * 60)  # outside the 24-hour window: template
    _run(business, rt)
    with db.new_session() as s:
        row = s.exec(select(Booking).where(Booking.channel == "whatsapp")).one()
        assert row.reminder_status == "template" and confirm.unconfirmed([row]) == []
    assert "unconfirmed" not in _run(business, rt, datetime(2026, 11, 5, 1, 0))  # 07:00, three hours before the visit
    with db.new_session() as s:
        assert s.exec(select(Booking).where(Booking.channel == "whatsapp")).one().status == "booked"
        assert "Не подтвердили" not in (digest_text(s, s.get(Business, business.id), datetime(2026, 11, 5, 2, 10)) or "")


def test_release_waits_three_hours_after_the_question_and_spares_paid_bookings(business, rt):
    """Findings 3 and 4."""
    from .test_scheduler import EVENING_UTC, _book, _run

    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.release_unconfirmed_hours, b.admin_chat_ids = 12, "999"
        s.add(b)
        s.commit()
    _book(business, "telegram", "1001")
    _book(business, "telegram", "1002", name="Нурлан")
    with db.new_session() as s:
        paid = s.exec(select(Booking).where(Booking.customer_name == "Нурлан")).one()
        paid.deposit_status = "paid"
        s.add(paid)
        s.commit()
    report = _run(business, rt)  # 18:05: reminders go out; the visit is at 10:00, within 12 hours — but no release yet
    assert report["reminders"]["sent"] == 2 and "unconfirmed" not in report
    assert "unconfirmed" not in _run(business, rt, EVENING_UTC + timedelta(hours=2))  # 20:05: under three hours since the question
    assert _run(business, rt, EVENING_UTC + timedelta(hours=4))["unconfirmed"] == {"released": 1}  # 22:05, 12 h before 10:00: Айбек only
    with db.new_session() as s:
        rows = {b.customer_name: b.status for b in s.exec(select(Booking).where(Booking.channel == "telegram")).all()}
        assert rows == {"Айбек": "cancelled", "Нурлан": "booked"}


def test_one_yes_confirms_both_reminded_visits(business, rt):
    """Finding 11."""
    from datetime import datetime

    from joop.agent.engine import handle_incoming
    from joop.channels.base import IncomingMessage
    from joop.models import Slot, Staff
    from .test_scheduler import EVENING_UTC, _book, _run

    _book(business, "telegram", "1001")
    with db.new_session() as s:
        b = s.get(Business, business.id)
        slot = s.exec(select(Slot).join(Staff).where(Slot.business_id == b.id, Slot.status == "free",
                                                     Slot.start == datetime(2026, 11, 5, 11, 0))).first()
        llm = FakeLLM([AgentReply("Записала", booking={"slot_id": slot.id, "name": "Айбек", "phone": "0555123456", "service": "чистка"})])
        handle_incoming(s, b, IncomingMessage("telegram", "1001", "text", "и ещё на 11", "", "tg:1001:second"), lambda: llm, EVENING_UTC - timedelta(minutes=5))
        s.commit()
    _run(business, rt)
    with db.new_session() as s:
        out = handle_incoming(s, s.get(Business, business.id), IncomingMessage("telegram", "1001", "text", "да", "Айбек", "tg:1001:yes"),
                              lambda: FakeLLM([AgentReply("x")]), EVENING_UTC + timedelta(minutes=10))
        s.commit()
    assert out.reply == "Спасибо, ждём вас Чт 05.11 10:00 и Чт 05.11 11:00!"
    with db.new_session() as s:
        assert all(b.confirmed_at for b in s.exec(select(Booking).where(Booking.channel == "telegram")).all())


def test_follow_up_offers_two_different_times_and_not_after_thanks(business, rt):
    """Findings 7 and 8."""
    from joop.agent.engine import handle_incoming
    from joop.channels.base import IncomingMessage
    from joop.scheduler import run_due_jobs
    from .test_unfinished import ASKED_UTC, LATER, _turn_on

    _turn_on(business.id)

    def say(text, chat, llm, now=ASKED_UTC):
        with db.new_session() as s:
            handle_incoming(s, s.get(Business, business.id), IncomingMessage("telegram", chat, "text", text, "Айбек", f"tg:{chat}:{text[:10]}"), lambda: llm, now)
            s.commit()

    say("Сколько стоит чистка?", "1001", FakeLLM([AgentReply("3 000 сом.")]))
    llm = FakeLLM([AgentReply("Нет, выходной."), AgentReply("Пожалуйста!")])
    say("Вы работаете в воскресенье?", "1002", llm)
    say("Понятно, спасибо", "1002", llm, ASKED_UTC + timedelta(minutes=1))
    with db.new_session() as s:
        report = run_due_jobs(s, rt, s.get(Business, business.id), LATER)
        s.commit()
    assert report["unfinished"] == {"sent": 1}  # 1001 only: 1002 said thanks
    [text] = [t for chat, t in rt.tg.sent if chat == "1001" and t.startswith("Если удобно")]
    times = text.split(": ", 1)[1].split(". ")[0].split(" или ")
    assert len(times) == 2 and times[0] != times[1]
    assert not [t for chat, t in rt.tg.sent if chat == "1002" and t.startswith("Если удобно")]


def test_follow_up_numbers_count_only_delivered_and_still_booked(business, rt):
    """Finding 9."""
    from joop import unfinished
    from joop.models import Conversation

    with db.new_session() as s:
        b = s.get(Business, business.id)
        tried = Conversation(business_id=b.id, channel="telegram", chat_id="t1", followup_at=NOW_UTC)  # marked, nothing delivered
        sent = Conversation(business_id=b.id, channel="telegram", chat_id="t2", followup_at=NOW_UTC)
        s.add(tried)
        s.add(sent)
        s.flush()
        from joop.models import Message

        s.add(Message(business_id=b.id, conversation_id=sent.id, role="ai", text="Если удобно…", created_at=NOW_UTC))
        s.add(Booking(business_id=b.id, conversation_id=sent.id, start=NOW_UTC + timedelta(days=1), status="cancelled", channel="telegram",
                      source="ai", created_at=NOW_UTC + timedelta(hours=1)))
        s.commit()
        assert unfinished.week_numbers(s, b, NOW_UTC - timedelta(days=1)) == (1, 0)


def test_a_friends_phone_does_not_open_her_history(business, rt):
    """Finding 10."""
    from datetime import datetime

    from joop import regulars
    from joop.models import Conversation

    with db.new_session() as s:
        b = s.get(Business, business.id)
        friend = Conversation(business_id=b.id, channel="telegram", chat_id="f1", customer_name="Айгүл", customer_phone="+996555123456")
        me = Conversation(business_id=b.id, channel="telegram", chat_id="m1", customer_name="Айбек", customer_phone="+996555123456")
        s.add(friend)
        s.add(me)
        s.flush()
        s.add(Booking(business_id=b.id, conversation_id=friend.id, customer_name="Айгүл", customer_phone="+996555123456", service="Эпиляция",
                      staff_name="Элина Ким", start=datetime(2026, 10, 30, 12, 0), channel="telegram", source="ai"))
        s.commit()
        assert regulars.prompt_hint(s, b, me, datetime(2026, 11, 4, 12, 0)) == ""  # same phone, another person: nothing
        assert "Эпиляция" in regulars.prompt_hint(s, b, friend, datetime(2026, 11, 4, 12, 0))


def test_audit_thanks_is_not_an_unanswered_question_and_weekends_count_when_asked():
    """Finding 13."""
    from joop import audit

    chat = audit.parse("04.11.2026, 11:00 - Клиент: Сколько стоит?\n04.11.2026, 11:10 - Салон: 800 сом\n04.11.2026, 11:12 - Клиент: Спасибо!\n"
                       "10.11.2026, 15:00 - подойдёт?\n")
    assert len(chat) == 3 and chat[-1].text == "Спасибо!\n10.11.2026, 15:00 - подойдёт?"  # a continuation line with a date
    r = audit.report([chat], "Салон", "10:00", "20:00")
    assert r.unanswered == 1 and r.answered == 1  # «15:00 — подойдёт?» after the thanks is a question that waited
    thanks = audit.parse("04.11.2026, 11:00 - Клиент: Сколько стоит?\n04.11.2026, 11:10 - Салон: 800 сом\n04.11.2026, 11:12 - Клиент: Спасибо!\n")
    assert audit.report([thanks], "Салон", "10:00", "20:00").unanswered == 0
    sat = audit.parse("07.11.2026, 12:00 - Клиент: Есть окно?\n07.11.2026, 12:05 - Салон: Да\n")  # Saturday noon
    assert audit.report([sat], "Салон", "10:00", "20:00").off_hours == 0
    assert audit.report([sat], "Салон", "10:00", "20:00", weekend_off=True).off_hours == 1
    night = audit.parse("04.11.2026, 23:00 - Клиент: Открыто?\n04.11.2026, 23:05 - Бар: Да\n")
    assert audit.report([night], "Бар", "20:00", "04:00").off_hours == 0  # a bar open overnight


def test_audit_lead_has_a_honeypot_a_cooldown_and_does_not_walk_a_prospect_back(settings, rt, engine):
    """Findings 5 and 6."""
    import io

    from joop import audit
    from joop.models import Prospect
    from joop.web.app import create_app
    from .test_audit import ANDROID
    from .test_web import csrf_of

    with db.new_session() as s:
        s.add(Prospect(name="Старое имя", phone="0555 123 456", status="trial", niche="dental"))
        s.commit()
    with TestClient(create_app(settings, rt, init=False)) as c:
        token = csrf_of(c.get("/audit").text)
        r = c.post("/audit", data={"csrf": token}, files=[("chats", ("a.txt", io.BytesIO(ANDROID.encode()), "text/plain"))])
        tok = audit._last_token()
        r = c.post("/audit/lead", data={"csrf": csrf_of(r.text), "token": tok, "business": "Бот", "phone": "0555 123 456", "website": "spam"})
        assert "Спасибо" not in r.text  # honeypot
        r = c.post("/audit", data={"csrf": token}, files=[("chats", ("a.txt", io.BytesIO(ANDROID.encode()), "text/plain"))])
        r = c.post("/audit/lead", data={"csrf": csrf_of(r.text), "token": audit._last_token(), "business": "Новое имя", "phone": "0555 123 456",
                                        "niche": "beauty"})
        assert "Спасибо" in r.text
        with db.new_session() as s:
            [p] = s.exec(select(Prospect)).all()
            assert p.name == "Старое имя" and p.status == "trial" and p.niche == "dental" and "Аудит переписки" in p.notes
        r = c.post("/audit", data={"csrf": token}, files=[("chats", ("a.txt", io.BytesIO(ANDROID.encode()), "text/plain"))])
        r = c.post("/audit/lead", data={"csrf": csrf_of(r.text), "token": audit._last_token(), "business": "Ещё", "phone": "0555 999 888"})
        assert "Спасибо" not in r.text  # within the 30-second cooldown
        with db.new_session() as s:
            assert len(s.exec(select(Prospect)).all()) == 1
