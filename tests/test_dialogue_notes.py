"""Staff-only notes in a dialogue: never sent, never read by the AI."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlmodel import select

from joop import db
from joop.models import Business, Conversation, ConversationNote, Message
from joop.web.app import create_app

from .conftest import NOW_UTC
from .test_web import csrf_of, login


def _conv(business_id):
    with db.new_session() as s:
        conv = Conversation(business_id=business_id, channel="telegram", chat_id="88", customer_name="Бакыт")
        s.add(conv)
        s.commit()
        s.add(Message(business_id=business_id, conversation_id=conv.id, role="customer", text="Можно завтра?",
                      created_at=NOW_UTC - timedelta(minutes=10)))
        s.commit()
        return conv.id


def test_note_is_shown_in_place_and_never_becomes_a_message(business, settings, rt):
    conv_id = _conv(business.id)
    with TestClient(create_app(settings, rt, init=False)) as c:
        login(c)
        page = c.get(f"/panel/conversations/{conv_id}").text
        assert "Заметка для своих" in page
        token = csrf_of(page)
        c.post(f"/panel/conversations/{conv_id}/note", data={"csrf": token, "text": "  Перезвонить после 18:00 <script>  "})
        page = c.get(f"/panel/conversations/{conv_id}").text
        assert "Перезвонить после 18:00 &lt;script&gt;" in page and "клиент не видит" in page
        assert page.index("Можно завтра?") < page.index("Перезвонить после 18:00")  # in time order
        assert "Заметка пустая" in c.post(f"/panel/conversations/{conv_id}/note", data={"csrf": token, "text": "  "},
                                          follow_redirects=True).text
        assert c.post(f"/panel/conversations/{conv_id}/note", data={"csrf": "bad", "text": "x"}).status_code in (400, 403)
    with db.new_session() as s:
        assert [m.role for m in s.exec(select(Message).where(Message.conversation_id == conv_id)).all()] == ["customer"]
        note = s.exec(select(ConversationNote)).one()
        assert note.text == "Перезвонить после 18:00 <script>" and note.author


def test_note_delete_and_other_business_cannot_touch_it(business, settings, rt):
    conv_id = _conv(business.id)
    with db.new_session() as s:
        other = Business(slug="other", name="Другой", password_hash="x")
        s.add(other)
        s.commit()
        oconv = Conversation(business_id=other.id, channel="telegram", chat_id="9")
        s.add(oconv)
        s.commit()
        foreign = ConversationNote(business_id=other.id, conversation_id=oconv.id, text="чужое")
        mine = ConversationNote(business_id=business.id, conversation_id=conv_id, text="моё")
        s.add_all([foreign, mine])
        s.commit()
        fid, mid, ocid = foreign.id, mine.id, oconv.id
    with TestClient(create_app(settings, rt, init=False)) as c:
        login(c)
        token = csrf_of(c.get(f"/panel/conversations/{conv_id}").text)
        assert c.post(f"/panel/conversations/{ocid}/note", data={"csrf": token, "text": "x"}).status_code == 404
        assert c.post(f"/panel/conversations/{conv_id}/note/{fid}/delete", data={"csrf": token}).status_code == 404
        assert c.post(f"/panel/conversations/{ocid}/note/{mid}/delete", data={"csrf": token}).status_code == 404
        c.post(f"/panel/conversations/{conv_id}/note/{mid}/delete", data={"csrf": token})
    with db.new_session() as s:
        assert s.get(ConversationNote, mid) is None and s.get(ConversationNote, fid) is not None


def test_the_ai_does_not_read_notes(business):
    from joop.agent.engine import handle_incoming
    from joop.agent.llm import AgentReply
    from joop.channels.base import IncomingMessage

    from .conftest import FakeLLM

    conv_id = _conv(business.id)
    with db.new_session() as s:
        s.add(ConversationNote(business_id=business.id, conversation_id=conv_id, text="СЕКРЕТНАЯ ЗАМЕТКА: клиент должник",
                               created_at=NOW_UTC - timedelta(minutes=5)))
        s.commit()
        llm = FakeLLM([AgentReply("Здравствуйте!")])
        handle_incoming(s, s.get(Business, business.id), IncomingMessage("telegram", "88", "text", "Здравствуйте", "Бакыт", "tg:88:n1"),
                        lambda: llm, NOW_UTC)
        s.commit()
    seen = str(llm.calls)
    assert llm.calls and "Можно завтра?" in seen and "СЕКРЕТНАЯ ЗАМЕТКА" not in seen
