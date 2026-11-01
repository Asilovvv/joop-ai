"""Web chat: the business's AI on a link and on any website (joop/web/webchat.py)."""

import re

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from joop import db
from joop.agent.llm import AgentReply
from joop.models import Business, Conversation, Lead
from joop.web import webchat
from joop.web.app import create_app

from .conftest import FakeLLM, first_free_slot
from .test_web import login


@pytest.fixture
def web(settings, rt, business):
    webchat.reset_limits()
    with TestClient(create_app(settings, rt, init=False)) as c:
        yield c
    webchat.reset_limits()


def say(client, text, visitor="", slug="aktish"):
    return client.post(f"/c/{slug}/chat", json={"text": text, "visitor": visitor})


def test_page_and_widget_are_public(web, business):
    page = web.get("/c/aktish")
    assert page.status_code == 200 and "Ак-Тиш Дент" in page.text and "Сурооңузду жазыңыз" in page.text
    assert "set-cookie" not in page.headers  # no session for visitors
    js = web.get("/c/aktish/widget.js")
    assert js.headers["content-type"].startswith("application/javascript")
    assert '"https://joop.test"' in js.text and '"aktish"' in js.text and "/c/' + slug + '?embed=1" in js.text
    assert web.get("/c/no-such-business").status_code == 404
    assert web.get("/c/no-such-business/widget.js").status_code == 404


def test_visitor_talks_to_the_same_engine_and_can_book(web, business, rt):
    with db.new_session() as s:  # staff linked their Telegram for notes
        b = s.get(Business, business.id)
        b.admin_chat_ids = "777"
        s.add(b)
        s.commit()
    slot = first_free_slot(business.id)
    rt._llm = FakeLLM([
        AgentReply("Консультация — 500 сом. Записать вас?"),
        AgentReply("Записала!", booking={"slot_id": slot.id, "name": "Айбек", "phone": "0555 123 456", "service": "консультация"}),
    ])
    r = say(web, "Сколько стоит консультация?")
    visitor = r.json()["visitor"]
    assert r.status_code == 200 and r.json()["reply"].startswith("Консультация") and re.fullmatch(r"[a-f0-9]{24}", visitor)
    assert "чате на сайте" in rt._llm.calls[0]["system"]
    r = say(web, "Запишите, Айбек, 0555 123 456", visitor)
    assert r.json() == {"reply": "Записала!", "visitor": visitor}
    with db.new_session() as s:
        convs = s.exec(select(Conversation).where(Conversation.business_id == business.id, Conversation.channel == "web")).all()
        assert len(convs) == 1 and convs[0].chat_id == f"web-{visitor}"  # the same visitor, the same conversation
    assert any(chat == "777" and "Айбек" in text for chat, text in rt.tg.sent)  # staff got the booking note in Telegram


def test_bad_tokens_get_a_fresh_one_and_input_is_checked(web, rt):
    rt._llm = FakeLLM([AgentReply("Здравствуйте!")])
    r = say(web, "Привет", visitor="../../etc")
    assert re.fullmatch(r"[a-f0-9]{24}", r.json()["visitor"])
    assert say(web, "   ").status_code == 400
    assert web.post("/c/aktish/chat", content=b"not json", headers={"content-type": "application/json"}).status_code == 400


def test_limits_per_visitor_and_per_business(web, rt, monkeypatch):
    rt._llm = FakeLLM([AgentReply("Ок.")] * 10)
    monkeypatch.setattr(webchat, "PER_VISITOR", 2)
    visitor = say(web, "1").json()["visitor"]
    say(web, "2", visitor)
    r = say(web, "3", visitor)
    assert r.status_code == 429 and "много" in r.json()["error"]
    monkeypatch.setattr(webchat, "PER_BUSINESS", 2)  # two web messages of this business today already
    r = say(web, "4")
    assert r.status_code == 429 and "перегружен" in r.json()["error"]


def test_switched_off_or_demo_businesses_have_no_chat(web, business):
    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.bot_enabled = False
        s.add(b)
        s.commit()
    assert web.get("/c/aktish").status_code == 404 and say(web, "Привет").status_code == 404


def test_model_failure_gives_a_clear_message(web, rt):
    class Broken(FakeLLM):
        def respond(self, *a, **k):
            raise RuntimeError("down")

    rt._llm = Broken([])
    r = say(web, "Привет")
    assert r.status_code == 200 and r.json()["reply"]  # the engine's own fallback reply, and a lead for staff
    with db.new_session() as s:
        assert s.exec(select(Lead).where(Lead.kind == "error")).first() is not None


def test_panel_shows_link_code_and_qr(web, business):
    login(web)
    page = web.get("/panel/channels").text
    assert "Чат на сайте и ссылка для Instagram" in page
    assert 'value="https://joop.test/c/aktish"' in page
    assert "https://joop.test/c/aktish/widget.js" in page and "<svg" in page
