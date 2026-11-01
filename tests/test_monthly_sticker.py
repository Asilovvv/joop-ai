"""The printable QR sticker and the monthly report to the owner."""

from datetime import datetime, timedelta

from sqlmodel import select

from joop import db
from joop.models import Booking, Business, Conversation, Lead, Message, Order, Service
from joop.scheduler import monthly_report_text, run_due_jobs
from joop.timeutil import local_to_utc

from .test_web import client, login  # noqa: F401  (client is a fixture)

TZ = "Asia/Bishkek"
NOW = local_to_utc(datetime(2026, 11, 1, 10, 0), TZ)  # the 1st, after the digest hour
IN_OCTOBER = local_to_utc(datetime(2026, 10, 15, 21, 0), TZ)


def seed_october(business_id):
    with db.new_session() as s:
        b = s.get(Business, business_id)
        priced = s.exec(select(Service).where(Service.business_id == b.id, Service.price_value != None)).first()  # noqa: E711
        assert priced is not None
        conv = Conversation(business_id=b.id, channel="telegram", chat_id="m1", created_at=IN_OCTOBER)
        s.add(conv)
        s.flush()
        s.add(Message(business_id=b.id, conversation_id=conv.id, role="customer", text="?", created_at=IN_OCTOBER, off_hours=True))
        s.add(Message(business_id=b.id, conversation_id=conv.id, role="customer", text="?", created_at=NOW))  # November: not counted
        s.add(Booking(business_id=b.id, conversation_id=conv.id, start=IN_OCTOBER, service=priced.name.upper(), source="ai",
                      created_at=IN_OCTOBER, created_off_hours=True))
        s.add(Booking(business_id=b.id, conversation_id=conv.id, start=IN_OCTOBER, service="что-то без цены", source="ai",
                      created_at=IN_OCTOBER))
        s.add(Booking(business_id=b.id, start=IN_OCTOBER, service=priced.name, source="panel", created_at=IN_OCTOBER))  # staff's own
        s.add(Order(business_id=b.id, total=2500, created_at=IN_OCTOBER))
        s.add(Order(business_id=b.id, total=9999, status="cancelled", created_at=IN_OCTOBER))
        s.add(Lead(business_id=b.id, kind="handoff", created_at=IN_OCTOBER))
        s.commit()
        return priced.price_value


def test_monthly_report_values_only_exact_prices(business):
    price = seed_october(business.id)
    with db.new_session() as s:
        text = monthly_report_text(s, s.get(Business, business.id), NOW)
    assert text.startswith("Итоги за октябрь «Ак-Тиш Дент»")
    assert "Ответил 1 клиенту, из них 1 — в нерабочее время." in text
    assert "Записал сам 2 клиентов, из них 1 — ночью и в выходные." in text
    total = f"{price + 2500:,}".replace(",", " ")
    assert f"около {total} сом" in text and "ещё 1 запись — услуги без точной цены" in text
    assert "Оформил заказов: 1." in text and "Передал вам 1 вопрос," in text


def test_russian_plurals():
    from joop.scheduler import _ru

    assert [_ru(n, "запись", "записи", "записей") for n in (1, 2, 5, 11, 12, 21, 22, 25, 111)] == [
        "1 запись", "2 записи", "5 записей", "11 записей", "12 записей", "21 запись", "22 записи", "25 записей", "111 записей"]


def test_quiet_month_sends_nothing_and_the_report_goes_on_the_1st(business, rt):
    with db.new_session() as s:
        assert monthly_report_text(s, s.get(Business, business.id), NOW) is None
    seed_october(business.id)
    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.digest_hour, b.admin_chat_ids = 9, "777"
        s.add(b)
        s.commit()
    with db.new_session() as s:
        assert run_due_jobs(s, rt, s.get(Business, business.id), NOW)["monthly"] is True
        s.commit()
    assert any("Итоги за октябрь" in text for chat, text in rt.tg.sent if chat == "777")
    with db.new_session() as s:  # the 2nd: no monthly report
        b = s.get(Business, business.id)
        b.last_digest_date = ""
        assert "monthly" not in run_due_jobs(s, rt, b, NOW + timedelta(days=1))


def test_sticker_sheet_has_four_stickers_with_the_chat_qr(client, business):  # noqa: F811
    assert client.get("/panel/sticker", follow_redirects=False).status_code in {302, 303}
    login(client)
    page = client.get("/panel/sticker").text
    assert page.count('class="sticker"') == 4 and page.count("<svg") == 4
    assert "Задайте вопрос — ответим сразу" in page and "Суроо бериңиз — дароо жооп беребиз" in page and "Ask us anything" in page
    assert "Ак-Тиш Дент" in page and "https://joop.test/c/aktish" in page  # the QR's title carries its link
    assert 'href="/panel/sticker"' in client.get("/panel/channels").text
