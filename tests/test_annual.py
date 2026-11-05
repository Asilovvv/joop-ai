"""The year offer at the end of the second paid month (joop/annual.py)."""

import dataclasses
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlmodel import select

from joop import annual, billing, db, founder_digest
from joop.models import Business, Payment, Subscription
from joop.web.app import create_app

from .conftest import NOW_UTC
from .test_saas import app_client, owner_login, saas_settings  # noqa: F401  (fixtures)


def _two_months(business_id, first_at, price=3000):
    """Two monthly payments: the first at `first_at`, the second a month later."""
    with db.new_session() as s:
        billing.start_trial(s, s.get(Business, business_id), 14, first_at - timedelta(days=14))
        for n in range(2):
            pay = Payment(business_id=business_id, amount_som=price)
            s.add(pay)
            s.flush()
            billing.mark_paid(s, pay, first_at + timedelta(days=30 * n))
        s.commit()


def test_candidates_are_those_with_two_payments_and_a_period_about_to_end(business):
    _two_months(business.id, NOW_UTC - timedelta(days=50))  # paid until +10 days
    with db.new_session() as s:
        [c] = annual.candidates(s, NOW_UTC, 3000, 10)
        assert c.months_paid == 2 and c.price == 3000 and c.annual_price == 30_000 and c.saves == 6_000
        assert annual.candidates(s, NOW_UTC - timedelta(days=20), 3000, 10) == []  # the period ends in 30 days: too early
        sub = s.exec(select(Subscription)).one()
        sub.year_offered_at = NOW_UTC
        s.add(sub)
        s.commit()
        assert annual.candidates(s, NOW_UTC, 3000, 10) == []  # already offered


def test_one_payment_a_cancellation_or_a_year_already_paid_do_not_qualify(business):
    with db.new_session() as s:
        billing.start_trial(s, s.get(Business, business.id), 14, NOW_UTC - timedelta(days=40))
        pay = Payment(business_id=business.id, amount_som=3000)
        s.add(pay)
        s.flush()
        billing.mark_paid(s, pay, NOW_UTC - timedelta(days=25))
        s.commit()
        assert annual.candidates(s, NOW_UTC, 3000, 10) == []  # one payment only
        year = Payment(business_id=business.id, amount_som=30000, period_days=365)
        s.add(year)
        s.flush()
        billing.mark_paid(s, year, NOW_UTC - timedelta(days=360))
        s.commit()
        assert annual.candidates(s, NOW_UTC, 3000, 10) == []  # a year was already bought
    _two_months(business.id, NOW_UTC - timedelta(days=50))
    with db.new_session() as s:
        sub = s.exec(select(Subscription)).one()
        billing.cancel(sub, NOW_UTC)
        s.add(sub)
        s.commit()
        assert annual.candidates(s, NOW_UTC, 3000, 10) == []


def test_offer_text_uses_the_businesss_own_numbers_and_waits_for_the_price(business):
    from joop.agent.engine import handle_incoming
    from joop.agent.llm import AgentReply
    from joop.channels.base import IncomingMessage
    from .conftest import FakeLLM

    _two_months(business.id, NOW_UTC - timedelta(days=50))
    with db.new_session() as s:
        b = s.get(Business, business.id)
        for n, chat in enumerate(("1001", "1002", "1003")):
            handle_incoming(s, b, IncomingMessage("telegram", chat, "text", "Сколько стоит?", "", f"tg:{chat}:{n}"),
                            lambda: FakeLLM([AgentReply("3 000 сом.")]), NOW_UTC - timedelta(days=20))
        s.commit()
    with db.new_session() as s:
        [c] = annual.candidates(s, NOW_UTC, 3000, 10)
        text = annual.offer_text(s, c, NOW_UTC)
        assert text.startswith("«Ак-Тиш Дент», вы с Joop AI уже 2-й месяц: с первой оплаты ИИ ответил 3 клиентам и записал 0.")
        assert "30 000 сом за 12 месяцев вместо 36 000 — 10 месяцев по цене, 2 в подарок, и цена не меняется до 14.11.2027." in text
        [c] = annual.candidates(s, NOW_UTC, 3000, 0)
        assert annual.offer_text(s, c, NOW_UTC) == ""  # the discount is the founder's decision
        assert founder_digest.text(s, NOW_UTC, 3000, 10).endswith(" Предложить год: Ак-Тиш Дент.")
        assert "Предложить год" not in founder_digest.text(s, NOW_UTC + timedelta(days=30), 3000, 10)


def test_console_reminds_marks_offered_and_takes_a_year_payment(app_client, saas_settings, rt, business):
    _two_months(business.id, NOW_UTC - timedelta(days=50))
    token = owner_login(app_client)
    page = app_client.get("/owner").text
    assert "Предложить год" in page and "ANNUAL_MONTHS=10" in page and "Оплачен год" not in page  # no price yet: who, not what
    rt.settings = dataclasses.replace(saas_settings, annual_months=10)
    with TestClient(create_app(rt.settings, rt, init=False)) as c:
        token2 = owner_login(c)
        page = c.get("/owner").text
        assert "год 30 000 сом, экономия 6 000" in page and "Оплачен год" in page and "10 месяцев по цене" in page
        c.post(f"/owner/business/{business.id}", data={"action": "paid_year", "csrf": token2})
        with db.new_session() as s:
            sub = s.exec(select(Subscription)).one()
            assert sub.paid_until == NOW_UTC + timedelta(days=10 + 365)
            year = s.exec(select(Payment).where(Payment.period_days == 365)).one()
            assert year.amount_som == 30_000 and year.status == "paid"
        assert "Предложить год" not in c.get("/owner").text  # a year is bought: nothing to offer
    _two_months(business.id, NOW_UTC - timedelta(days=50))  # another business-like state: mark as offered by hand
    with db.new_session() as s:
        for p in s.exec(select(Payment).where(Payment.period_days == 365)).all():
            s.delete(p)
        sub = s.exec(select(Subscription)).one()
        sub.paid_until = NOW_UTC + timedelta(days=5)
        s.add(sub)
        s.commit()
    assert "Предложить год" in app_client.get("/owner").text
    app_client.post(f"/owner/business/{business.id}", data={"action": "year_offered", "csrf": token})
    assert "Предложить год" not in app_client.get("/owner").text
    with db.new_session() as s:
        assert s.exec(select(Subscription)).one().year_offered_at == NOW_UTC
