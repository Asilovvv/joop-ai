"""The block list: a blocked chat costs nothing and hears nothing from Joop."""

from fastapi.testclient import TestClient
from sqlmodel import select

from joop import db
from joop.agent.engine import handle_incoming
from joop.agent.llm import AgentReply
from joop.channels.base import IncomingMessage
from joop.models import Business, Conversation, Message
from joop.web.app import create_app

from .conftest import NOW_UTC, FakeLLM
from .test_web import csrf_of, login


def _say(business, text, ext):
    llm = FakeLLM([AgentReply("Здравствуйте!")])
    with db.new_session() as s:
        out = handle_incoming(s, s.get(Business, business.id), IncomingMessage("telegram", "666", "text", text, "Спамер", ext),
                              lambda: llm, NOW_UTC)
        s.commit()
    return out, llm


def test_block_silences_the_chat_and_unblock_restores_it(business, settings, rt):
    _say(business, "Купите крипту", "s1")
    with db.new_session() as s:
        conv_id = s.exec(select(Conversation).where(Conversation.chat_id == "666")).one().id
    with TestClient(create_app(settings, rt, init=False)) as c:
        login(c)
        page = c.get(f"/panel/conversations/{conv_id}").text
        assert "В чёрный список" in page
        token = csrf_of(page)
        c.post(f"/panel/conversations/{conv_id}/block", data={"csrf": token, "action": "block"})
        assert "Чат в чёрном списке" in c.get(f"/panel/conversations/{conv_id}").text
        assert "чёрный список" in c.get("/panel/conversations").text
        out, llm = _say(business, "Купите крипту ещё раз", "s2")
        assert out.skipped == "blocked" and llm.calls == [] and not out.admin_notes
        with db.new_session() as s:
            assert len(s.exec(select(Message).where(Message.conversation_id == conv_id)).all()) == 2  # nothing new stored
            assert s.get(Conversation, conv_id).silenced
        c.post(f"/panel/conversations/{conv_id}/block", data={"csrf": token, "action": "unblock"})
        out, llm = _say(business, "Извините, хочу записаться", "s3")
        assert not out.skipped and llm.calls


def test_blocked_chat_is_out_of_broadcasts_and_voice_is_not_recognised(business, rt, monkeypatch):
    from joop import broadcasts, dispatch, voice

    with db.new_session() as s:
        conv = Conversation(business_id=business.id, channel="telegram", chat_id="777", blocked_at=NOW_UTC)
        s.add(conv)
        s.commit()
        b = s.get(Business, business.id)
        assert broadcasts.preview(s, b, "all", "", NOW_UTC).telegram == 0
    called = []
    monkeypatch.setattr(voice, "prepare", lambda *a, **k: called.append(1) or a[2])
    dispatch.process_incoming(rt, business.id, IncomingMessage("telegram", "777", "media", "", "x", "v1", media_ref="file1"), NOW_UTC)
    assert called == []  # recognition costs money: not for a blocked chat


def test_block_is_per_business_and_not_for_the_test_chat(business, settings, rt):
    with db.new_session() as s:
        other = Business(slug="other", name="Другой", password_hash="x")
        s.add(other)
        s.commit()
        oconv = Conversation(business_id=other.id, channel="telegram", chat_id="1")
        test = Conversation(business_id=business.id, channel="console", chat_id="t")
        s.add_all([oconv, test])
        s.commit()
        oid, tid = oconv.id, test.id
    with TestClient(create_app(settings, rt, init=False)) as c:
        login(c)
        token = csrf_of(c.get("/panel/conversations").text)
        assert c.post(f"/panel/conversations/{oid}/block", data={"csrf": token}).status_code == 404
        assert c.post(f"/panel/conversations/{tid}/block", data={"csrf": token}).status_code == 400


def test_nothing_joop_starts_reaches_a_blocked_chat_and_no_late_answer(business, rt):
    """Sixth-plus review (#122-#131), findings 2 and 3: reminders and the after-outage answer skip blocked chats."""
    from datetime import timedelta

    from joop import recovery
    from joop.agent.engine import ERROR_REPLY
    from joop.followups import deliver_to_chat
    from joop.models import Lead

    with db.new_session() as s:
        b = s.get(Business, business.id)
        conv = Conversation(business_id=b.id, channel="telegram", chat_id="888", blocked_at=NOW_UTC, last_customer_at=NOW_UTC)
        s.add(conv)
        s.commit()
        assert deliver_to_chat(s, rt, b, conv, "Напоминаем о записи завтра", NOW_UTC) is False
        s.add(Message(business_id=b.id, conversation_id=conv.id, role="customer", text="?", created_at=NOW_UTC - timedelta(minutes=5)))
        s.add(Message(business_id=b.id, conversation_id=conv.id, role="ai", text=ERROR_REPLY, created_at=NOW_UTC - timedelta(minutes=5)))
        s.add(Lead(business_id=b.id, kind="error", conversation_id=conv.id, channel="telegram", created_at=NOW_UTC - timedelta(minutes=5)))
        s.commit()
        assert conv.id not in {c.id for c, _ in recovery.waiting(s, b, NOW_UTC)}


def test_web_chats_cannot_be_blocked(business, settings, rt):
    with db.new_session() as s:
        conv = Conversation(business_id=business.id, channel="web", chat_id="web-abc")
        s.add(conv)
        s.commit()
        cid = conv.id
    with TestClient(create_app(settings, rt, init=False)) as c:
        login(c)
        page = c.get(f"/panel/conversations/{cid}").text
        assert "В чёрный список" not in page
        assert c.post(f"/panel/conversations/{cid}/block", data={"csrf": csrf_of(page), "action": "block"}).status_code == 400
