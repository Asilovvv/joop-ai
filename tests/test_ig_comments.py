"""Instagram comment → a private reply in Direct, the AI's answer, then the usual dialogue (joop/channels/meta.py, joop/ig_comments.py)."""

import json

import httpx
from sqlmodel import select

from joop import db, ig_comments
from joop.channels.meta import InstagramClient, parse_instagram
from joop.models import Business, Conversation, Message

from .test_web import _signed, client  # noqa: F401  (fixture)


def _comment(text, cid="c-1", sender="igsid-7", account="ig-1", username="aigerim_nails"):
    return {"object": "instagram", "entry": [{"id": account, "time": 1, "changes": [{"field": "comments", "value": {
        "id": cid, "text": text, "from": {"id": sender, "username": username}, "media": {"id": "m-1", "media_product_type": "FEED"},
    }}]}]}


def test_parse_comment_events_and_skip_the_businesss_own():
    [(account, m)] = parse_instagram(_comment("Сколько стоит маникюр?"))
    assert account == "ig-1" and m.chat_id == "igsid-7" and m.kind == "text" and m.text == "Сколько стоит маникюр?"
    assert m.user_name == "aigerim_nails" and m.external_id == "igc:c-1" and m.reply_to == "c-1"
    assert parse_instagram(_comment("Спасибо всем!", sender="ig-1")) == []  # the business answering under its own post
    assert parse_instagram(_comment("")) == []


def test_private_and_public_replies_go_to_the_right_endpoints():
    seen = []
    http = httpx.Client(transport=httpx.MockTransport(lambda r: seen.append(r) or httpx.Response(200, json={"id": "x"})))
    client = InstagramClient(http, "https://graph.instagram.test", "v26.0", "ig-1", "tok")
    assert client.send_private_reply("c-1", "Здравствуйте! Маникюр — 800 сом.")
    assert seen[0].url.path == "/v26.0/ig-1/messages" and json.loads(seen[0].content)["recipient"] == {"comment_id": "c-1"}
    assert client.reply_to_comment("c-1", "Ответили вам в Директ")
    assert seen[1].url.path == "/v26.0/c-1/replies" and json.loads(seen[1].content) == {"message": "Ответили вам в Директ"}


def test_wanted_comments_only_questions_and_keywords():
    b = Business(slug="x", name="X", ig_comments=True)
    assert ig_comments.wanted(b, "Сколько стоит?") and ig_comments.wanted(b, "цена") and ig_comments.wanted(b, "Канча турат")
    assert ig_comments.wanted(b, "а вы на выходных работаете?")  # any question
    assert not ig_comments.wanted(b, "Красота!") and not ig_comments.wanted(b, "")
    b.ig_comment_keywords = "запись"
    assert ig_comments.wanted(b, "Хочу запись") and not ig_comments.wanted(b, "цена")
    b.ig_comments = False
    assert not ig_comments.wanted(b, "Сколько стоит?")


def test_comment_opens_direct_with_the_ais_answer_and_the_thread_continues(client, rt, business):
    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.ig_account_id, b.ig_access_token = "ig-1", "tok"
        s.commit()
    raw, headers = _signed(_comment("Сколько стоит чистка?"))
    assert client.post("/webhooks/meta", content=raw, headers=headers).text == "EVENT_RECEIVED"
    assert rt.ig.sent == [] and rt.ig.private == []  # off by default: comments are left alone
    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.ig_comments = True
        s.commit()
    raw, headers = _signed(_comment("Сколько стоит чистка?", cid="c-2"))
    client.post("/webhooks/meta", content=raw, headers=headers)
    assert rt.ig.sent == []  # the first word goes through the comment, not to a user id
    [(cid, text)] = rt.ig.private
    assert cid == "c-2" and text.startswith("Здравствуйте! Я ИИ-помощник «Ак-Тиш Дент»")
    assert rt.ig.public == [("c-2", "Ответили вам в Директ")]
    raw, headers = _signed(_comment("Красиво!", cid="c-3"))
    client.post("/webhooks/meta", content=raw, headers=headers)
    assert len(rt.ig.private) == 1  # not a question: nothing
    # the customer answers in Direct: the same conversation, the usual send
    dm = {"object": "instagram", "entry": [{"id": "ig-1", "time": 2, "messaging": [
        {"sender": {"id": "igsid-7"}, "recipient": {"id": "ig-1"}, "timestamp": 2, "message": {"mid": "m-9", "text": "А завтра можно?"}}]}]}
    raw, headers = _signed(dm)
    client.post("/webhooks/meta", content=raw, headers=headers)
    assert len(rt.ig.sent) == 1 and rt.ig.sent[0][0] == "igsid-7"
    with db.new_session() as s:
        conv = s.exec(select(Conversation).where(Conversation.chat_id == "igsid-7")).one()
        assert conv.display_name == "aigerim_nails"
        assert [m.role for m in s.exec(select(Message).where(Message.conversation_id == conv.id).order_by(Message.id)).all()] == ["customer", "ai", "customer", "ai"]


def test_channels_page_saves_the_comment_settings(business, rt, settings):
    import dataclasses

    from fastapi.testclient import TestClient

    from joop.web.app import create_app
    from .test_web import csrf_of, login

    rt.settings = dataclasses.replace(settings, meta_verify_token="v", meta_app_secret="s")
    with TestClient(create_app(rt.settings, rt, init=False)) as c:
        login(c)
        token = csrf_of(c.get("/panel/channels").text)
        c.post("/panel/channels", data={"csrf": token, "ig_account_id": "ig-1", "ig_comments": "1", "ig_comment_keywords": "цена, запись",
                                        "ig_comment_public_reply": "Написали вам в Директ"})
        with db.new_session() as s:
            b = s.get(Business, business.id)
            assert b.ig_comments and b.ig_comment_keywords == "цена, запись" and b.ig_comment_public_reply == "Написали вам в Директ"
