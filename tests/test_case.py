"""A case with real numbers from the database, for the founder to publish (joop/case.py, /owner/business/{id}/case)."""

from datetime import timedelta

from sqlmodel import select

from joop import case, db
from joop.models import Booking, Business, Conversation, Message, Service
from joop.presets import create_business

from .conftest import NOW_UTC
from .test_pilot import activity
from .test_saas import app_client, owner_login, saas_settings  # noqa: F401  (fixtures)


def _seed(business_id):
    with db.new_session() as s:
        b = s.get(Business, business_id)
        svc = s.exec(select(Service).where(Service.business_id == b.id, Service.name == "Профессиональная чистка")).first()
        c1 = activity(s, b, "a", 20, off=True)
        activity(s, b, "a", 19)
        c2 = activity(s, b, "b", 10, off=True)
        activity(s, b, "c", 5)
        for conv, days, off in ((c1, 19, True), (c2, 9, False), (c2, 3, False)):
            s.add(Booking(business_id=b.id, conversation_id=conv.id, customer_name="Клиент", customer_phone="+996555000001",
                          service=svc.name, start=NOW_UTC - timedelta(days=days), source="ai", channel="telegram",
                          created_at=NOW_UTC - timedelta(days=days, hours=1), created_off_hours=off, rating=5 if days == 9 else 0))
        s.commit()


def test_case_numbers_come_from_the_database_only(business):
    _seed(business.id)
    with db.new_session() as s:
        b = s.get(Business, business.id)
        c = case.build(s, b, NOW_UTC, days=30)
    assert c.days == 30 and c.conversations == 3 and c.off_conversations == 2 and c.off_pct == 67
    assert c.bookings == 3 and c.off_bookings == 1 and c.value_som == 9000 and c.valued == 3  # 3 × 3 000
    assert c.rated == 1 and c.average_rating == 5.0
    assert c.headline() == "За 30 дней ИИ ответил 3 клиентам, 2 из них — в нерабочее время, записал 3; по прайсу это около 9 000 сом."
    assert case.build(s, b, NOW_UTC, days=30, lang="ky").headline().startswith("30 күндө ИИ 3 кардарга жооп берди")
    with db.new_session() as s:
        quiet = create_business(s, slug="quiet1", name="Тихая", password="secret-pass", now_utc=NOW_UTC)
        s.flush()
        assert case.build(s, quiet, NOW_UTC, days=30).conversations == 0


def test_case_page_for_the_founder(business, app_client):
    _seed(business.id)
    assert app_client.get(f"/owner/business/{business.id}/case", follow_redirects=False).headers["location"] == "/owner/login"
    owner_login(app_client)
    page = app_client.get(f"/owner/business/{business.id}/case?days=30").text
    assert "Кейс: Ак-Тиш Дент" in page and "9 000 сом" in page and "67%" in page and "Только цифры из базы" in page
    assert "Жооп берди" in app_client.get(f"/owner/business/{business.id}/case?days=30&lang=ky").text or "кардарга" in app_client.get(
        f"/owner/business/{business.id}/case?days=30&lang=ky").text
    assert app_client.get("/owner/business/999/case").status_code == 404


def test_case_leaves_out_cancelled_bookings_unanswered_chats_test_chats_and_names_orders(business):
    """Fourth review, findings 1, 2, 3, 6, 8: a published number must survive a sceptical reader."""
    from joop.models import Order
    from joop.stats import TEST_CHANNEL

    _seed(business.id)
    with db.new_session() as s:
        b = s.get(Business, business.id)
        released = s.exec(select(Booking).where(Booking.rating == 0).order_by(Booking.id)).first()
        released.status = "cancelled"  # released for no-show: not a result
        s.add(released)
        quiet = Conversation(business_id=b.id, channel="telegram", chat_id="paused", created_at=NOW_UTC)  # staff answered, the AI was paused
        s.add(quiet)
        s.flush()
        s.add(Message(business_id=b.id, conversation_id=quiet.id, role="customer", text="?", created_at=NOW_UTC - timedelta(days=2)))
        s.add(Message(business_id=b.id, conversation_id=quiet.id, role="staff", text="Ответил человек", created_at=NOW_UTC - timedelta(days=2)))
        s.add(Booking(business_id=b.id, customer_name="Тест", customer_phone="+996555000002", service="Профессиональная чистка",
                      start=NOW_UTC - timedelta(days=1), source="ai", channel=TEST_CHANNEL, created_at=NOW_UTC - timedelta(days=1), rating=1))
        s.add(Order(business_id=b.id, channel="telegram", total=1500, created_at=NOW_UTC - timedelta(days=1)))
        s.commit()
        c = case.build(s, b, NOW_UTC, days=30)
    assert c.conversations == 3 and c.bookings == 2 and c.value_som == 6000 + 1500 and c.orders == 1
    assert c.rated == 1 and c.average_rating == 5.0  # the test chat's rating of 1 is not counted
    assert c.headline() == "За 30 дней ИИ ответил 3 клиентам, 2 из них — в нерабочее время, записал 2 и принял 1 заказ; по прайсу это около 7 500 сом."
    c.valued, c.rated = 1, 5
    assert c.not_valued_text() == "ещё 1 запись без точной цены не посчитаны" and c.rated_text() == "5 оценок"
