"""The free chat audit: a WhatsApp export in, the numbers a prospect loses out (joop/audit.py, /audit)."""

import dataclasses
import io
from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlmodel import select

from joop import audit, db, health
from joop.models import Prospect
from joop.web.app import create_app

from .test_web import csrf_of

ANDROID = """04.11.2026, 10:58 - Сообщения и звонки защищены сквозным шифрованием.
04.11.2026, 10:58 - Клиент А: Здравствуйте! Сколько стоит маникюр?
04.11.2026, 11:40 - Салон Гүл: Здравствуйте! 800 сом
04.11.2026, 11:41 - Клиент А: А завтра можно?
04.11.2026, 12:30 - Салон Гүл: Да, есть 15:00
04.11.2026, 22:15 - Клиент А: Запишите на 15:00
05.11.2026, 10:05 - Салон Гүл: Записала
"""
IOS = """‎[04.11.2026, 23:10:02] Клиент Б: Салам! Чач кыркуу канча турат?
‎[05.11.2026, 10:30:11] Салон Гүл: Саламатсызбы, 500 сом
[05.11.2026, 10:31:00] Клиент Б: Бүгүн 18:00 болобу?
"""
US = """11/4/26, 7:02 PM - Client C: Hi, do you have a slot tomorrow?
This is a second line of the same message
11/4/26, 7:03 PM - Client C: <Media omitted>
"""


def test_parses_android_ios_and_us_formats_and_continuation_lines():
    a = audit.parse(ANDROID)
    assert [m.sender for m in a][:2] == ["Клиент А", "Салон Гүл"] and len(a) == 6  # the system line is dropped
    assert a[0].at == datetime(2026, 11, 4, 10, 58) and a[0].text == "Здравствуйте! Сколько стоит маникюр?"
    i = audit.parse(IOS)
    assert len(i) == 3 and i[0].at == datetime(2026, 11, 4, 23, 10, 2) and i[0].sender == "Клиент Б"
    u = audit.parse(US)
    assert len(u) == 2 and u[0].at == datetime(2026, 11, 4, 19, 2) and u[0].text.endswith("same message")
    assert audit.parse("just some text\nwithout dates") == []


def test_report_counts_what_the_business_loses():
    chats = [audit.parse(ANDROID), audit.parse(IOS)]
    me = audit.guess_business(chats)
    assert me == "Салон Гүл"
    r = audit.report(chats, me, work_start="10:00", work_end="20:00")
    assert r.dialogues == 2 and r.customer_messages == 5 and r.business_messages == 4
    assert r.off_hours == 2  # 22:15 and 23:10
    # reply times: 42 min, 49 min, 11h50m (overnight), 11h20m, and one never answered (18:00 болобу?)
    assert r.answered == 4 and r.unanswered == 1 and r.ended_by_customer == 1
    assert r.median_reply_minutes == 364 and r.within_15_min == 0 and r.over_an_hour == 2
    assert r.price_questions == 2 and r.price_waited_over_an_hour == 1  # the night-time Kyrgyz one waited till morning
    assert r.first_day == datetime(2026, 11, 4).date() and r.last_day == datetime(2026, 11, 5).date()
    assert audit.report([audit.parse("nothing")], "", "10:00", "20:00").dialogues == 0


def test_audit_page_shows_the_numbers_keeps_no_files_and_makes_a_prospect(settings, rt, engine, monkeypatch):
    rt.settings = dataclasses.replace(settings, owner_password="owner-pass-123", founder_bot_token="F:TOKEN", founder_chat_id="42")
    monkeypatch.setattr(health, "_send", lambda rt_, text: rt.tg.send_text("42", text))
    with TestClient(create_app(rt.settings, rt, init=False)) as c:
        page = c.get("/audit")
        assert page.status_code == 200 and "Аудит переписки" in page.text
        token = csrf_of(page.text)
        r = c.post("/audit", data={"csrf": token, "work_start": "10:00", "work_end": "20:00"},
                   files=[("chats", ("a.txt", io.BytesIO(ANDROID.encode()), "text/plain")),
                          ("chats", ("b.txt", io.BytesIO(IOS.encode()), "text/plain"))])
        assert r.status_code == 200
        assert "Диалогов: 2" in r.text and "в нерабочее время" in r.text and "Салон Гүл" in r.text
        assert "Клиент А" not in r.text  # customers' names stay out of the report
        assert 'name="token"' in r.text
        token2 = csrf_of(r.text)
        r = c.post("/audit/lead", data={"csrf": token2, "token": audit._last_token(), "business": "Салон Гүл", "phone": "0555 123 456",
                                        "contact_name": "Гүлнара"})
        assert r.status_code == 200 and "Спасибо" in r.text
        with db.new_session() as s:
            [p] = s.exec(select(Prospect)).all()
            assert p.name == "Салон Гүл" and p.phone == "0555 123 456" and "Диалогов: 2" in p.notes and p.status == "replied"
        assert any("аудит переписки" in t and "Салон Гүл" in t for _, t in rt.tg.sent)
        assert c.post("/audit", data={"csrf": token}, files=[("chats", ("x.txt", io.BytesIO(b"no dates here"), "text/plain"))]).text.count(
            "Не нашли сообщений WhatsApp") == 1
