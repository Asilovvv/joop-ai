import dataclasses
import re

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from joop import db
from joop.agent.llm import AgentReply
from joop.models import Business, Conversation, Message
from joop.web import demo
from joop.web.app import create_app
from joop.web.saas import unique_slug


@pytest.fixture
def site(settings, rt, engine):
    demo._by_address.clear()
    s = dataclasses.replace(settings, anthropic_api_key="test-key", site_demo_daily_limit=300, owner_password="owner-pass-123")
    rt.settings = s
    with TestClient(create_app(s, rt, init=False)) as c:
        yield c


def page_csrf(client) -> str:
    return re.search(r'<meta name="csrf" content="([^"]+)"', client.get("/").text).group(1)


def say(client, text, key="salon", csrf=None):
    return client.post("/demo/chat", json={"key": key, "text": text, "csrf": csrf or page_csrf(client)})


def test_landing_offers_the_live_chat_only_with_a_key(site, settings, rt, engine):
    assert 'class="composer" data-composer' in site.get("/").text
    off = dataclasses.replace(settings, anthropic_api_key="", site_demo_daily_limit=300)
    with TestClient(create_app(off, rt, init=False)) as c:
        assert 'class="composer" data-composer' not in c.get("/").text


def test_visitor_talks_to_the_real_engine_of_a_hidden_demo_business(site, llm):
    llm.replies = [AgentReply("Маникюр с покрытием — 1 200 сом."), AgentReply("Записать вас?")]
    r = say(site, "Сколько стоит маникюр?")
    assert r.status_code == 200 and r.json()["reply"] == "Маникюр с покрытием — 1 200 сом." and r.json()["left"] == demo.PER_SESSION - 1
    assert "Салон" in llm.calls[0]["system"]  # the demo salon's own data went to the model
    say(site, "А завтра?")
    with db.new_session() as s:
        b = s.exec(select(Business).where(Business.slug == "site-demo-salon")).one()
        convs = s.exec(select(Conversation).where(Conversation.business_id == b.id)).all()
        assert len(convs) == 1 and convs[0].chat_id.startswith("site-salon-") and convs[0].channel == "console"
    # The second message continued the same conversation.
    assert len(llm.calls[1]["messages"]) > len(llm.calls[0]["messages"])
    # Hidden from the founder console.
    token = re.search(r'name="csrf" value="([^"]+)"', site.get("/owner/login").text).group(1)
    site.post("/owner/login", data={"password": "owner-pass-123", "csrf": token})
    assert "site-demo-salon" not in site.get("/owner").text


def test_limits_per_session_and_per_day(site, llm, settings, rt):
    csrf = page_csrf(site)
    for _ in range(demo.PER_SESSION):
        assert say(site, "Привет", csrf=csrf).status_code == 200
    r = say(site, "Ещё", csrf=csrf)
    assert r.status_code == 429 and "закончились" in r.json()["error"]

    low = dataclasses.replace(settings, anthropic_api_key="test-key", site_demo_daily_limit=2)
    with TestClient(create_app(low, rt, init=False)) as c:  # the site already has 16 visitor messages today
        r = say(c, "Привет")
        assert r.status_code == 429 and "лимит" in r.json()["error"]


def test_bad_requests(site):
    assert say(site, "Привет", key="casino").status_code == 400
    assert say(site, "   ").status_code == 400
    assert site.post("/demo/chat", json={"key": "salon", "text": "Привет", "csrf": "wrong"}).status_code == 403


def test_demo_slugs_are_reserved(engine):
    with db.new_session() as s:
        assert unique_slug(s, "Site Demo Salon").startswith("c-site-demo")


def test_demo_slots_are_refreshed(site, llm):
    say(site, "Привет", key="clinic")
    with db.new_session() as s:
        b = s.exec(select(Business).where(Business.slug == "site-demo-clinic")).one()
        from joop.models import Slot

        before = len(s.exec(select(Slot).where(Slot.business_id == b.id)).all())
        demo._refreshed.clear()
        demo.demo_business(s, "clinic")  # same week: nothing new, nothing doubled
        assert len(s.exec(select(Slot).where(Slot.business_id == b.id)).all()) == before > 0
        assert s.exec(select(Message).where(Message.business_id == b.id, Message.role == "customer")).one().text == "Привет"
