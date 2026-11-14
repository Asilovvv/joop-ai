"""The owner chooses how long the AI stays out of a chat after staff answered (12 hours by default)."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlmodel import select

from joop import db, staff_reply
from joop.agent.engine import handle_incoming
from joop.agent.llm import AgentReply
from joop.channels.base import IncomingMessage
from joop.models import Business, Conversation
from joop.presets import create_business
from joop.web.app import create_app

from .conftest import NOW_UTC, FakeLLM
from .test_web import csrf_of


def clinic(minutes=None):
    with db.new_session() as s:
        b = create_business(s, slug="dent", name="Дент", password="pass-12345", niche="dental", demo=True, now_utc=NOW_UTC)
        if minutes:
            b.takeover_minutes = minutes
        s.add(Conversation(business_id=b.id, channel="web", chat_id="v1", created_at=NOW_UTC))
        s.commit()
        return b


def say(business_id, text, ext, now, chat="v1"):
    llm = FakeLLM([AgentReply("Ответ ИИ.")])
    with db.new_session() as s:
        out = handle_incoming(s, s.get(Business, business_id), IncomingMessage("web", chat, "text", text, "", ext), lambda: llm, now)
        s.commit()
    return out, llm


def staff_answers(rt, business_id, now):
    with db.new_session() as s:
        conv = s.exec(select(Conversation).where(Conversation.business_id == business_id)).one()
        ok, _ = staff_reply.send(s, rt, s.get(Business, business_id), conv, "Здравствуйте, это администратор.", now, author="Айгуль")
        s.commit()
        return ok


def test_default_stays_twelve_hours(engine, rt):
    b = clinic()
    assert staff_answers(rt, b.id, NOW_UTC)
    out, llm = say(b.id, "А цена?", "a", NOW_UTC + timedelta(hours=11))
    assert out.skipped == "paused" and not llm.calls


def test_a_short_pause_lets_the_ai_pick_up_later(engine, rt):
    b = clinic(15)
    assert staff_answers(rt, b.id, NOW_UTC)
    out, _ = say(b.id, "А цена?", "a", NOW_UTC + timedelta(minutes=10))
    assert out.skipped == "paused"
    out, llm = say(b.id, "Вы тут?", "b", NOW_UTC + timedelta(minutes=16))
    assert not out.skipped and out.reply == "Ответ ИИ."  # the customer wrote later: the AI answers again


def test_owner_picks_it_in_settings_and_the_dialogue_says_it(settings, rt, engine):
    b = clinic()
    with TestClient(create_app(settings, rt, init=False)) as c:
        token = csrf_of(c.get("/login").text)
        c.post("/login", data={"slug": "dent", "password": "pass-12345", "csrf": token})
        page = c.get("/panel/settings").text
        assert 'name="takeover_minutes"' in page and '<option value="720" selected>12 часов</option>' in page
        form = {"csrf": csrf_of(page), "name": "Дент", "takeover_minutes": "60", "timezone": "Asia/Bishkek"}
        c.post("/panel/settings", data=form)
        c.post("/panel/settings", data={**form, "takeover_minutes": "7"})  # not one of the choices: kept as it was
        with db.new_session() as s:
            assert s.get(Business, b.id).takeover_minutes == 60
            conv_id = s.exec(select(Conversation).where(Conversation.business_id == b.id)).one().id
        assert "После ответа ИИ не вмешивается в этот диалог 1 час." in c.get(f"/panel/conversations/{conv_id}").text
