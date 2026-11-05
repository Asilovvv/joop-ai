"""The sales funnel the AI moves by itself (joop/funnel.py, /panel/funnel)."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlmodel import select

from joop import db, funnel, staff_reply
from joop.models import Booking, Business, Conversation, Lead, Order
from joop.web.app import create_app

from .conftest import NOW_UTC
from .test_web import csrf_of, login


def _seed(business_id):
    with db.new_session() as s:
        b = s.get(Business, business_id)
        convs = [Conversation(business_id=b.id, channel="telegram", chat_id=str(1000 + i), customer_name=n, last_customer_at=NOW_UTC)
                 for i, n in enumerate(("Айбек", "Нурлан", "Мадина", "Эрмек"))]
        s.add_all(convs)
        s.flush()
        for i, conv in enumerate(convs):
            s.add(Lead(business_id=b.id, conversation_id=conv.id, kind="request", summary=f"заявка {i}", channel="telegram",
                       created_at=NOW_UTC - timedelta(days=3)))
        s.add(Lead(business_id=b.id, kind="error", summary="сбой", channel="telegram"))  # not a sale
        s.add(Lead(business_id=b.id, kind="request", summary="тест", channel="console"))  # the panel's test chat
        s.flush()
        # Айбек booked and the visit passed; Нурлан booked for tomorrow; Мадина ordered; Эрмек nothing yet
        s.add(Booking(business_id=b.id, conversation_id=convs[0].id, customer_name="Айбек", start=NOW_UTC - timedelta(days=1),
                      channel="telegram", created_at=NOW_UTC - timedelta(days=2)))
        s.add(Booking(business_id=b.id, conversation_id=convs[1].id, customer_name="Нурлан", start=NOW_UTC + timedelta(days=1),
                      channel="telegram", created_at=NOW_UTC - timedelta(days=2)))
        s.add(Order(business_id=b.id, conversation_id=convs[2].id, channel="telegram", total=900, created_at=NOW_UTC - timedelta(days=2)))
        s.commit()
        return [c.id for c in convs]


def test_stages_move_from_facts_and_staff_replies(business, rt):
    ids = _seed(business.id)
    with db.new_session() as s:
        b = s.get(Business, business.id)
        assert funnel.advance(s, b, NOW_UTC) == 4  # Айбек: booked then visited; Нурлан: booked; Мадина: booked
        s.commit()
        stages = {x.summary: x.stage for x in s.exec(select(Lead).where(Lead.kind == "request", Lead.channel == "telegram")).all()}
        assert stages == {"заявка 0": "visited", "заявка 1": "booked", "заявка 2": "booked", "заявка 3": "new"}
        assert funnel.advance(s, b, NOW_UTC) == 0  # settled
        conv = s.get(Conversation, ids[3])
        ok, _ = staff_reply.send(s, rt, b, conv, "Перезвоню вам", NOW_UTC, "Айгерим")
        assert ok
        s.commit()
        assert s.exec(select(Lead).where(Lead.summary == "заявка 3")).one().stage == "contacted"
        f = funnel.report(s, b, NOW_UTC)
        assert f.total == 4 and f.counts == {"new": 0, "contacted": 1, "booked": 2, "visited": 1, "lost": 0}
        assert f.booked_pct == 75 and f.visited_pct == 33


def test_funnel_page_and_the_lost_button(business, rt, settings):
    _seed(business.id)
    with TestClient(create_app(settings, rt, init=False)) as c:
        login(c)
        page = c.get("/panel/funnel").text  # advances on open
        assert "заявок стали записью" in page and "Пришёл" in page and "сбой" not in page and "тест" not in page
        assert 'href="/panel/funnel"' in page and 'href="/panel/customers"' in page  # both in the sidebar
        token = csrf_of(page)
        with db.new_session() as s:
            lead = s.exec(select(Lead).where(Lead.summary == "заявка 3")).one()
        c.post(f"/panel/funnel/{lead.id}", data={"csrf": token, "stage": "lost"})
        with db.new_session() as s:
            row = s.get(Lead, lead.id)
            assert row.stage == "lost" and row.status == "done"
        assert c.post(f"/panel/funnel/{lead.id}", data={"csrf": token, "stage": "nope"}).status_code == 400
        assert c.post("/panel/funnel/999", data={"csrf": token, "stage": "lost"}).status_code == 404
