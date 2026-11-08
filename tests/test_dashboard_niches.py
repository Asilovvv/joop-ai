"""The dashboard and the weekly report speak the niche's language: orders for a wholesaler, qualified leads as results."""

from datetime import timedelta

from fastapi.testclient import TestClient

from joop import db
from joop.models import Business, Conversation, Lead, Message, Order
from joop.presets import create_business
from joop.scheduler import weekly_report_text
from joop.stats import activity
from joop.web.app import create_app

from .conftest import NOW_UTC
from .test_web import csrf_of


def test_a_wholesalers_dashboard_and_report(engine, settings, rt):
    """A wholesaler takes no bookings: the dashboard showed «Ближайшие записи … когда ИИ запишет клиента», and a
    qualified buyer request («объём, сроки») was counted as «вопросов передано людям» instead of a result."""
    with db.new_session() as s:
        b = create_business(s, slug="opt", name="Опт Импорт", password="opt-pass-123", niche="wholesale", demo=True, now_utc=NOW_UTC)
        s.flush()
        conv = Conversation(business_id=b.id, channel="telegram", chat_id="w1", customer_name="Бакыт")
        s.add(conv)
        s.flush()
        s.add(Message(business_id=b.id, conversation_id=conv.id, role="customer", text="Нужны термосы оптом", created_at=NOW_UTC))
        s.add(Lead(business_id=b.id, conversation_id=conv.id, kind="lead", summary="Термосы, 20 коробок", channel="telegram",
                   created_at=NOW_UTC))
        s.add(Lead(business_id=b.id, conversation_id=conv.id, kind="handoff", summary="Вопрос про сертификаты", channel="telegram",
                   created_at=NOW_UTC))
        s.add(Order(business_id=b.id, conversation_id=conv.id, customer_name="Бакыт", customer_phone="+996555111222", total=14400,
                    channel="telegram", created_at=NOW_UTC))
        s.commit()
        n = activity(s, b.id, NOW_UTC - timedelta(days=1))
        assert (n["qualified"], n["leads"], n["orders"]) == (1, 2, 1)
        report = weekly_report_text(s, s.get(Business, b.id), NOW_UTC + timedelta(hours=1))
        assert "заявок с бюджетом и сроками 1" in report and "Передал вам 1 вопросов" in report
        assert "Итого 2 готовых обращений" in report
    with TestClient(create_app(settings, rt, init=False)) as c:
        c.post("/login", data={"slug": "opt", "password": "opt-pass-123", "csrf": csrf_of(c.get("/login").text)})
        page = c.get("/panel").text
        assert "Последние заказы" in page and "14400 сом" in page and "Ближайшие записи" not in page
        assert "заявок с бюджетом и сроками собрал ИИ" in page and "уведомлений о заказах и заявках" in page
        assert '<b>1</b><span>вопросов передано людям' in page
