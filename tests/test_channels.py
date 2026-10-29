import json
from datetime import timedelta

import httpx

from joop import db
from joop.agent.engine import handle_incoming
from joop.agent.llm import AgentReply
from joop.channels.base import clip_bytes
from joop.channels.base import IncomingMessage
from joop.channels.meta import InstagramClient, WhatsAppClient, parse_whatsapp
from joop.channels.telegram import parse_update
from joop.models import Business
from joop.scheduler import TOKEN_REFRESH_EVERY, run_due_jobs

from .conftest import NOW_UTC, FakeLLM


def _recording_client():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("refresh_access_token"):
            return httpx.Response(200, json={"access_token": "new-token", "token_type": "bearer", "expires_in": 5183944})
        return httpx.Response(200, json={"messages": [{"id": "wamid.1"}]})

    return httpx.Client(transport=httpx.MockTransport(handler)), seen


def test_clip_bytes_respects_utf8_limit():
    text = "Здравствуйте! " * 100  # Cyrillic: 2 bytes per letter
    clipped = clip_bytes(text, 1000)
    assert len(clipped.encode("utf-8")) <= 1000 and clipped.endswith("…")
    assert clip_bytes("короткий", 1000) == "короткий"


def test_whatsapp_hidden_number_uses_bsuid():
    payload = {"object": "whatsapp_business_account", "entry": [{"changes": [{"field": "messages", "value": {
        "metadata": {"phone_number_id": "pn-1"},
        "contacts": [{"user_id": "KG.123", "profile": {"name": "Айгуль"}}],
        "messages": [{"from_user_id": "KG.123", "id": "wamid.9", "type": "text", "text": {"body": "Здравствуйте"}}],
    }}]}]}
    [(account, message)] = parse_whatsapp(payload)
    assert account == "pn-1" and message.chat_id == "bsuid:KG.123" and message.user_name == "Айгуль"

    http, seen = _recording_client()
    client = WhatsAppClient(http, "https://graph.test", "v26.0", "pn-1", "tok")
    assert client.send_text("bsuid:KG.123", "Ответ")
    assert client.send_text("996555000111", "Ответ")
    first, second = (json.loads(r.content) for r in seen)
    assert first["recipient"] == "KG.123" and "to" not in first
    assert second["to"] == "996555000111" and "recipient" not in second
    assert seen[0].url == "https://graph.test/v26.0/pn-1/messages"
    assert seen[0].headers["authorization"] == "Bearer tok"


def test_instagram_send_and_token_refresh():
    http, seen = _recording_client()
    client = InstagramClient(http, "https://graph.instagram.test", "v26.0", "ig-1", "old-token")
    assert client.send_text("igsid-1", "Ж" * 900)
    body = json.loads(seen[0].content)
    assert body["recipient"] == {"id": "igsid-1"}
    assert len(body["message"]["text"].encode("utf-8")) <= 1000
    assert client.refresh_token() == "new-token"
    assert seen[1].url.params["grant_type"] == "ig_refresh_token"


def test_long_reply_echo_cut_by_channel_is_still_ours(business):
    long_reply = "Здравствуйте! " + "Свободно завтра у терапевта в десять, одиннадцать и в пятнадцать часов. " * 10
    llm = FakeLLM([AgentReply(long_reply)])
    with db.new_session() as s:
        b = s.get(Business, business.id)
        handle_incoming(s, b, IncomingMessage("instagram", "igsid-7", "text", "Есть время?", "", "ig:a"), lambda: llm, NOW_UTC)
        cut = clip_bytes(long_reply, 1000)
        out = handle_incoming(s, b, IncomingMessage("instagram", "igsid-7", "echo", cut, "", "ig:b"), lambda: llm, NOW_UTC)
        assert out.skipped == "own_echo"
        short = handle_incoming(s, b, IncomingMessage("instagram", "igsid-7", "echo", "Здравствуйте!", "", "ig:c"), lambda: llm, NOW_UTC)
        assert short.skipped == "staff_reply"  # short texts must match exactly


def test_instagram_token_refreshed_weekly(business, rt):
    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.ig_account_id, b.ig_access_token = "ig-1", "old"
        b.ig_token_refreshed_at = NOW_UTC - TOKEN_REFRESH_EVERY - timedelta(hours=1)
        report = run_due_jobs(s, rt, b, NOW_UTC)
        assert report["instagram_token"] is True
        assert b.ig_access_token == "refreshed-token" and b.ig_token_refreshed_at == NOW_UTC
        assert "instagram_token" not in run_due_jobs(s, rt, b, NOW_UTC + timedelta(days=1))

        rt.ig.ok = False
        b.ig_token_refreshed_at = NOW_UTC - TOKEN_REFRESH_EVERY
        assert run_due_jobs(s, rt, b, NOW_UTC)["instagram_token"] is False
        # failed refresh is retried the next day, not every few minutes
        assert "instagram_token" not in run_due_jobs(s, rt, b, NOW_UTC + timedelta(hours=2))
        assert run_due_jobs(s, rt, b, NOW_UTC + timedelta(days=1, minutes=1))["instagram_token"] is False


def test_telegram_group_text_is_ignored_but_commands_pass():
    group = {"update_id": 1, "message": {"message_id": 1, "chat": {"id": -100, "type": "group"}, "from": {"id": 5}, "text": "привет всем"}}
    assert parse_update(group) is None
    group["message"]["text"] = "/admin 12345678"
    assert parse_update(group).kind == "command"
    voice = {"update_id": 2, "message": {"message_id": 2, "chat": {"id": 7, "type": "private"}, "from": {"id": 7}, "voice": {"file_id": "x"}}}
    assert parse_update(voice).media_label == "голосовое сообщение"
