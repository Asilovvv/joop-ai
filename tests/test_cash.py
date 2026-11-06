"""Visit payments and the day's cash (joop/cash.py, /panel/cash)."""

from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlmodel import select

from joop import cash, db
from joop.models import Booking, Business
from joop.scheduler import digest_text
from joop.timeutil import utc_to_local
from joop.web.app import create_app

from .conftest import NOW_UTC
from .test_web import csrf_of, login

LOCAL = utc_to_local(NOW_UTC, "Asia/Bishkek")  # 2026-11-04 23:14


def _seed(business_id):
    with db.new_session() as s:
        b = s.get(Business, business_id)
        rows = [
            Booking(business_id=b.id, customer_name="Айбек", customer_phone="+996555123456", service="Профессиональная чистка", staff_name="Айгерим",
                    start=LOCAL - timedelta(hours=3), channel="telegram"),
            Booking(business_id=b.id, customer_name="Нурлан", customer_phone="+996555000002", service="Профессиональная чистка + Фторирование", staff_name="Айгерим",
                    start=LOCAL - timedelta(hours=2), channel="telegram", upsell_status="accepted", upsell_price=500),
            Booking(business_id=b.id, customer_name="Мадина", customer_phone="+996555000003", service="Консультация", staff_name="Бакыт",
                    start=LOCAL + timedelta(hours=5), channel="telegram"),  # still ahead: not unpaid yet
            Booking(business_id=b.id, customer_name="Тест", customer_phone="+996555000009", service="Консультация", start=LOCAL - timedelta(hours=1), channel="console"),
            Booking(business_id=b.id, customer_name="Вчера", customer_phone="+996555000004", service="Консультация", staff_name="Бакыт",
                    start=LOCAL - timedelta(days=1), channel="whatsapp", paid_som=500, paid_method="card", paid_at=NOW_UTC - timedelta(days=1)),
        ]
        s.add_all(rows)
        s.commit()
        return [r.id for r in rows]


def test_suggested_amount_day_and_month(business):
    ids = _seed(business.id)
    with db.new_session() as s:
        b = s.get(Business, business.id)
        first, second = s.get(Booking, ids[0]), s.get(Booking, ids[1])
        assert cash.suggested(s, first) == 3000 and cash.suggested(s, second) == 3500  # price list + accepted add-on
        d = cash.day(s, b, LOCAL, LOCAL)
        assert [x.customer_name for x in d.unpaid] == ["Айбек", "Нурлан"] and d.total == 0  # the test chat and the future visit are out
        cash.record(first, 3000, "cash", NOW_UTC)
        cash.record(second, 3500, "card", NOW_UTC)
        s.add(first)
        s.add(second)
        s.commit()
        d = cash.day(s, b, LOCAL, LOCAL)
        assert d.total == 6500 and d.by_method == {"cash": 3000, "card": 3500} and d.by_staff == {"Айгерим": 6500} and d.unpaid == []
        m = cash.month(s, b, LOCAL)
        assert m.total == 7000 and m.visits == 3 and m.by_staff == [("Айгерим", 6500), ("Бакыт", 500)]
        assert m.by_service[0] == ("Профессиональная чистка", 6500)
        assert cash.digest_line(s, b, LOCAL) == "Касса за вчера: 500 сом (карта 500), оплачено визитов 1."
        assert "Касса за вчера: 500 сом" in digest_text(s, b, NOW_UTC)
        cash.record(first, 0, "cash", NOW_UTC)
        assert first.paid_som == 0 and first.paid_at is None


def test_cash_page_records_a_payment_and_the_customer_card_prefers_it(business, rt, settings):
    ids = _seed(business.id)
    with TestClient(create_app(settings, rt, init=False)) as c:
        login(c)
        page = c.get("/panel/cash").text
        assert "Визиты без оплаты (2)" in page and 'value="3500"' in page and 'href="/panel/cash"' in page
        token = csrf_of(page)
        r = c.post(f"/panel/bookings/{ids[0]}/pay", data={"csrf": token, "amount": "3 000", "method": "transfer"}, follow_redirects=False)
        assert r.headers["location"].startswith("/panel/cash?date=2026-11-04")
        page = c.get("/panel/cash?date=2026-11-04").text
        assert "Визиты без оплаты (1)" in page and "перевод" in page and "3 000" in page
        assert c.post("/panel/bookings/999/pay", data={"csrf": token, "amount": "1"}).status_code == 404
        assert "3 000" in c.get("/panel/customers/555123456").text
        assert "Касса" in c.get("/panel/cash?date=nonsense").text  # a bad date falls back to today


def test_receipt_mark_counts_payments_without_a_fiscal_receipt(business, rt, settings):
    """Joop is not a ККМ: it keeps the «чек пробит» mark and reminds where it is missing (docs/kkm-kg.md)."""
    ids = _seed(business.id)
    with TestClient(create_app(settings, rt, init=False)) as c:
        login(c)
        token = csrf_of(c.get("/panel/cash").text)
        c.post(f"/panel/bookings/{ids[0]}/pay", data={"csrf": token, "amount": "3000", "method": "cash", "receipt": "1"})
        c.post(f"/panel/bookings/{ids[1]}/pay", data={"csrf": token, "amount": "3500", "method": "card"})
        page = c.get("/panel/cash?date=2026-11-04").text
        assert "оплат без отметки о чеке ККМ" in page and page.count('class="chip ok">пробит') == 1
        assert c.post(f"/panel/bookings/{ids[2]}/receipt", data={"csrf": token}).status_code == 400  # nothing paid yet
        c.post(f"/panel/bookings/{ids[1]}/receipt", data={"csrf": token})
        assert "оплат без отметки о чеке ККМ" not in c.get("/panel/cash?date=2026-11-04").text
        c.post(f"/panel/bookings/{ids[1]}/pay", data={"csrf": token, "amount": "0"})
    with db.new_session() as s:
        assert s.get(Booking, ids[1]).receipt_at is None  # an undone payment takes its mark with it
        b = s.get(Business, business.id)
        assert "Без отметки о чеке ККМ: 1" in cash.digest_line(s, b, LOCAL)  # yesterday's card payment in the seed
