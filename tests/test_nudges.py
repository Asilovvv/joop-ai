"""Reminders to staff about requests nobody answered (joop/nudges.py)."""

from datetime import datetime, timedelta

from sqlmodel import select

from joop import db, nudges
from joop.models import Business, Conversation, Lead, Message
from joop.scheduler import digest_text, run_due_jobs
from joop.timeutil import local_to_utc, utc_to_local

from .conftest import NOW_UTC
from .test_web import client, csrf_of, login  # noqa: F401  (client is a fixture)

DAY = NOW_UTC - timedelta(hours=8)  # Wednesday 15:14 in Bishkek: working hours


def setup(business_id, **values):
    with db.new_session() as s:
        b = s.get(Business, business_id)
        b.admin_chat_ids, b.work_start, b.work_end = "999", "09:00", "19:00"
        for k, v in values.items():
            setattr(b, k, v)
        s.add(b)
        s.commit()


def lead(business_id, created, name="Айбек", kind="handoff", status="new", staff_reply_at=None, summary="Хочу пожаловаться на мастера"):
    with db.new_session() as s:
        conv = Conversation(business_id=business_id, channel="whatsapp", chat_id=f"c-{name}-{created:%H%M}")
        s.add(conv)
        s.flush()
        x = Lead(business_id=business_id, conversation_id=conv.id, kind=kind, summary=summary, customer_name=name,
                 customer_phone="0555 123 456", channel="whatsapp", status=status, created_at=created)
        s.add(x)
        if staff_reply_at:
            s.add(Message(business_id=business_id, conversation_id=conv.id, role="staff", text="Здравствуйте!", created_at=staff_reply_at))
        s.commit()
        return x.id


def due_ids(business_id, now):
    with db.new_session() as s:
        return [x.id for x in nudges.overdue(s, s.get(Business, business_id), now)]


def test_only_open_unanswered_requests_after_the_wait(business):
    setup(business.id)
    old = lead(business.id, DAY - timedelta(minutes=40))
    lead(business.id, DAY - timedelta(minutes=10), name="Свежий")
    lead(business.id, DAY - timedelta(minutes=50), name="Ответили", staff_reply_at=DAY - timedelta(minutes=45))
    lead(business.id, DAY - timedelta(minutes=50), name="Закрыта", status="done")
    lead(business.id, DAY - timedelta(days=4), name="Старая")
    assert due_ids(business.id, DAY) == [old]
    assert due_ids(business.id, NOW_UTC) == []  # 23:14: nobody is at work


def test_night_requests_are_due_after_opening(business):
    setup(business.id)
    local_day = utc_to_local(DAY, business.timezone).date()
    night = lead(business.id, local_to_utc(datetime.combine(local_day, datetime.min.time()) + timedelta(hours=2), business.timezone))
    at = lambda h, m: local_to_utc(datetime.combine(local_day, datetime.min.time()) + timedelta(hours=h, minutes=m), business.timezone)  # noqa: E731
    assert due_ids(business.id, at(9, 10)) == []  # opened at 9:00, the 30 minutes run from then
    assert due_ids(business.id, at(9, 31)) == [night]


def test_one_message_once_and_the_switch(business, rt):
    setup(business.id)
    ids = [lead(business.id, DAY - timedelta(minutes=60 + i), name=f"Клиент{i}") for i in range(7)]
    with db.new_session() as s:
        report = run_due_jobs(s, rt, s.get(Business, business.id), DAY)
        s.commit()
    assert report["nudged"] == 7
    [text] = [t for chat, t in rt.tg.sent if chat == "999" and t.startswith("Ждёт ответа")]
    assert text.startswith("Ждёт ответа больше 30 мин: 7 заявок\n— Клиент6, 0555 123 456 (WhatsApp): Хочу пожаловаться")
    assert "…и ещё 2." in text and text.endswith("отметьте «Готово» в разделе «Заявки».")
    with db.new_session() as s:
        assert all(s.get(Lead, i).nudged_at == DAY for i in ids)
        assert nudges.send(s, rt, s.get(Business, business.id), DAY + timedelta(minutes=10)) == 0  # once per request
    lead(business.id, DAY - timedelta(minutes=40), name="Новая")
    setup(business.id, lead_nudge_minutes=0)
    assert due_ids(business.id, DAY) == []
    setup(business.id, admin_chat_ids="")
    with db.new_session() as s:
        assert nudges.send(s, rt, s.get(Business, business.id), DAY) == 0  # no Telegram linked: nothing marked


def test_morning_summary_counts_open_requests(business):
    setup(business.id)
    lead(business.id, DAY - timedelta(hours=3))
    lead(business.id, DAY - timedelta(minutes=20), name="Свежий")
    with db.new_session() as s:
        text = digest_text(s, s.get(Business, business.id), DAY)
    assert "Не закрыто заявок: 1 — ответьте клиентам" in text


def test_panel_setting(client, business):  # noqa: F811
    token = login(client)
    page = client.get("/panel/settings").text
    assert 'name="lead_nudge_minutes" value="30"' in page
    client.post("/panel/settings", data={"csrf": csrf_of(page) or token, "name": "Ак-Тиш Дент", "work_start": "09:00",
                                          "work_end": "19:00", "timezone": "Asia/Bishkek", "niche": "dental",
                                          "bot_enabled": "1", "lead_nudge_minutes": "45"})
    with db.new_session() as s:
        assert s.exec(select(Business.lead_nudge_minutes).where(Business.id == business.id)).one() == 45
