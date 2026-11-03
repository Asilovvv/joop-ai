"""The two pilot numbers the strategy still lacked: dialogues the owner checked in week one, and retention (joop/retention.py)."""

from datetime import timedelta

from sqlmodel import select

from joop import billing, db, retention
from joop.models import Business, Conversation, Message, Payment
from joop.presets import create_business

from .conftest import NOW_UTC
from .test_pilot import activity
from .test_saas import app_client, owner_login, saas_settings  # noqa: F401  (fixtures)
from .test_web import login


def test_opening_a_dialogue_marks_it_reviewed_once(business, app_client):
    with db.new_session() as s:
        conv = activity(s, s.get(Business, business.id), "996555000111", 1)
        s.commit()
        cid = conv.id
    login(app_client)
    assert app_client.get(f"/panel/conversations/{cid}").status_code == 200
    with db.new_session() as s:
        first = s.get(Conversation, cid).reviewed_at
        assert first is not None
    app_client.get(f"/panel/conversations/{cid}")
    with db.new_session() as s:
        assert s.get(Conversation, cid).reviewed_at == first  # the first look is what counts


def test_week_one_reviews_and_retention_at_30_and_90_days(engine):
    with db.new_session() as s:
        old = create_business(s, slug="old1", name="Старый салон", password="secret-pass", now_utc=NOW_UTC - timedelta(days=100))
        gone = create_business(s, slug="gone1", name="Ушедшая", password="secret-pass", now_utc=NOW_UTC - timedelta(days=40))
        fresh = create_business(s, slug="fresh1", name="Новая", password="secret-pass", now_utc=NOW_UTC - timedelta(days=3))
        create_business(s, slug="site-demo-x", name="Витрина", password="secret-pass", now_utc=NOW_UTC - timedelta(days=200))
        for b, days in ((old, 100), (gone, 40), (fresh, 3)):
            b.created_at = NOW_UTC - timedelta(days=days)  # create_business stamps the real clock
            s.add(b)
        s.flush()
        sub = billing.start_trial(s, old, 14, NOW_UTC - timedelta(days=100))
        sub.paid_until = NOW_UTC + timedelta(days=10)
        s.add(Payment(business_id=old.id, amount_som=3000, status="paid", paid_at=NOW_UTC))
        billing.start_trial(s, gone, 14, NOW_UTC - timedelta(days=40))  # trial over, never paid
        billing.start_trial(s, fresh, 14, NOW_UTC - timedelta(days=3))
        # the old salon went live 99 days ago; the owner opened two of its three week-one dialogues in time, one too late
        start = NOW_UTC - timedelta(days=99)
        for chat, reviewed in (("a", start + timedelta(days=1)), ("b", start + timedelta(days=6)), ("c", start + timedelta(days=9))):
            conv = Conversation(business_id=old.id, channel="whatsapp", chat_id=chat, created_at=start, reviewed_at=reviewed)
            s.add(conv)
            s.flush()
            s.add(Message(business_id=old.id, conversation_id=conv.id, role="customer", text="?", created_at=start))
        late = Conversation(business_id=old.id, channel="whatsapp", chat_id="d", created_at=start + timedelta(days=20),
                            reviewed_at=start + timedelta(days=20))  # after week one: not counted
        s.add(late)
        s.flush()
        s.add(Message(business_id=old.id, conversation_id=late.id, role="customer", text="?", created_at=start + timedelta(days=20)))
        s.commit()
    with db.new_session() as s:
        rows, summary = retention.report(s, NOW_UTC)
    by = {r.business: r for r in rows}
    assert list(by) == ["Старый салон", "Ушедшая", "Новая"]  # demo left out, oldest first
    assert by["Старый салон"].week_one_conversations == 3 and by["Старый салон"].week_one_reviewed == 2
    assert by["Старый салон"].kept and not by["Ушедшая"].kept and by["Новая"].kept  # a running trial counts as kept so far
    assert by["Новая"].week_one_conversations == 0 and by["Новая"].live_at is None
    assert summary.kept_30 == (1, 2) and summary.kept_90 == (1, 1)  # of those old enough to judge
    assert summary.week_one_reviewed == 2


def test_pilot_page_shows_the_retention_section(engine, app_client):
    with db.new_session() as s:
        b = create_business(s, slug="s1", name="Салон", password="secret-pass", now_utc=NOW_UTC - timedelta(days=35))
        b.created_at = NOW_UTC - timedelta(days=35)
        s.add(b)
        s.flush()
        billing.start_trial(s, b, 14, NOW_UTC - timedelta(days=35))
        s.commit()
    owner_login(app_client)
    page = app_client.get("/owner/pilot").text
    assert "Удержание" in page and "<b>0 из 1</b><span>удержано через 30 дней" in page and "<b>—</b><span>удержано через 90 дней" in page
    assert "Проверено в первую неделю" in page
