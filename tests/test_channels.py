import json
from datetime import timedelta

import httpx
from sqlmodel import select

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
from .test_web import client  # noqa: F401  (a fixture)


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
        sent = handle_incoming(s, b, IncomingMessage("instagram", "igsid-7", "text", "Есть время?", "", "ig:a"), lambda: llm, NOW_UTC)
        cut = clip_bytes(sent.reply, 1000)
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


def _business_update(sender_id: int, text: str, message_id: int = 41, **extra) -> dict:
    msg = {"message_id": message_id, "business_connection_id": "conn-1", "chat": {"id": 900, "type": "private"},
           "from": {"id": sender_id, "first_name": "Айгерим"}, "text": text, **extra}
    return {"update_id": 9, "business_message": msg}


def test_telegram_business_customer_owner_and_own_bot_messages():
    customer = parse_update(_business_update(900, "Сколько стоит маникюр?"))
    assert (customer.kind, customer.chat_id, customer.user_name) == ("text", "bc:conn-1:900", "Айгерим")
    assert parse_update(_business_update(900, "/start")).kind == "text"  # a personal chat has no bot commands
    owner = parse_update(_business_update(555, "Да, приходите в 15:00"))
    assert (owner.kind, owner.text) == ("echo", "Да, приходите в 15:00")  # typed by the owner: the AI pauses
    assert parse_update(_business_update(555, "Ответ ИИ", sender_business_bot={"id": 1, "is_bot": True})) is None
    no_connection = _business_update(900, "привет")
    del no_connection["business_message"]["business_connection_id"]
    assert parse_update(no_connection) is None


def test_telegram_business_reply_goes_through_the_connection():
    from joop.channels.telegram import TelegramClient, split_chat_id

    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    client = TelegramClient(httpx.Client(transport=httpx.MockTransport(handler)), "https://api.telegram.org", "T")
    assert client.send_text("bc:conn-1:900", "Ждём вас") and client.send_text("777", "Привет")
    first, second = (json.loads(r.content) for r in seen)
    assert first == {"chat_id": "900", "text": "Ждём вас", "business_connection_id": "conn-1"}
    assert second == {"chat_id": "777", "text": "Привет"}
    assert split_chat_id("bc:a:b:900") == ("a:b", "900") and split_chat_id("-100") == ("", "-100")
    client.get_updates(None, timeout=0)
    assert "business_message" in json.loads(seen[-1].content)["allowed_updates"]


def test_telegram_business_owner_reply_pauses_the_ai(business):
    llm = FakeLLM([AgentReply("Маникюр — 800 сом.")])
    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.telegram_business_connection = "conn-1"
        first = handle_incoming(s, b, parse_update(_business_update(900, "Сколько стоит маникюр?")), lambda: llm, NOW_UTC)
        assert first.reply == "Маникюр — 800 сом."
        staff = handle_incoming(s, b, parse_update(_business_update(555, "Я сам отвечу", 42)), lambda: llm, NOW_UTC)
        assert staff.skipped == "staff_reply"
        later = handle_incoming(s, b, parse_update(_business_update(900, "А педикюр?", 43)), lambda: llm, NOW_UTC + timedelta(minutes=1))
        assert later.skipped == "paused" and not later.reply
        assert later.admin_notes == []  # the owner already sees this chat in their own Telegram


def test_channels_page_explains_telegram_business_once_a_bot_is_connected(client, business):  # noqa: F811
    from .test_web import login

    login(client)
    assert "telegram-business" not in client.get("/panel/channels").text
    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.telegram_bot_token, b.telegram_bot_username = "1:x", "aktish_bot"
        s.add(b)
        s.commit()
    page = client.get("/panel/channels").text
    assert 'id="telegram-business"' in page and "Business Mode" in page and "Telegram Premium" in page


def test_only_the_owners_own_telegram_business_connection_is_answered(business, rt):
    from joop import tgbusiness

    def conn(user_chat_id, enabled=True, can_reply=True):
        return {"business_connection": {"id": "conn-1", "user": {"id": int(user_chat_id)}, "user_chat_id": int(user_chat_id),
                                        "is_enabled": enabled, "rights": {"can_reply": can_reply}}}

    llm = FakeLLM([AgentReply("Маникюр — 800 сом.")])
    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.admin_chat_ids = "555"
        s.add(b)
        s.commit()
        # a stranger with Premium added our public bot to their account: their chats are not answered
        assert tgbusiness.apply(s, b, tgbusiness.parse_connection(conn(777))) == tgbusiness.NOT_LINKED
        assert b.telegram_business_connection == ""
        out = handle_incoming(s, b, parse_update(_business_update(900, "Сколько стоит?")), lambda: llm, NOW_UTC)
        assert out.skipped == "unknown_connection" and llm.calls == []
        # the owner, linked as the alerts chat, connects: answered from now on
        assert tgbusiness.apply(s, b, tgbusiness.parse_connection(conn(555, can_reply=False))) == tgbusiness.NO_REPLY
        assert tgbusiness.apply(s, b, tgbusiness.parse_connection(conn(555))) == tgbusiness.CONNECTED
        assert b.telegram_business_connection == "conn-1"
        assert handle_incoming(s, b, parse_update(_business_update(900, "Сколько стоит?", 50)), lambda: llm, NOW_UTC).reply
        assert tgbusiness.apply(s, b, tgbusiness.parse_connection(conn(555, enabled=False))) == ""
        assert b.telegram_business_connection == ""


def test_personal_telegram_chats_get_no_broadcasts_and_business_messages_only_within_24_hours(business, rt):
    from joop import broadcasts
    from joop.followups import deliver_to_chat
    from joop.models import Conversation

    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.telegram_bot_token = "1:x"
        personal = Conversation(business_id=b.id, channel="telegram", chat_id="bc:conn-1:900", last_customer_at=NOW_UTC - timedelta(hours=1),
                                last_message_at=NOW_UTC - timedelta(hours=1), created_at=NOW_UTC - timedelta(days=3))
        s.add_all([b, personal])
        s.commit()
        assert not broadcasts._reachable(b, personal, NOW_UTC)  # the bot is connected: still never
        assert broadcasts.preview(s, b, "all", "", NOW_UTC).reachable == 0
        sent: list[str] = []
        rt.telegram = lambda business: type("C", (), {"send_text": lambda self, chat, text: sent.append(chat) or True})()
        assert deliver_to_chat(s, rt, b, personal, "Ждём вас завтра", NOW_UTC) and sent == ["bc:conn-1:900"]
        assert not deliver_to_chat(s, rt, b, personal, "Ждём вас", NOW_UTC + timedelta(days=1))  # Telegram would refuse


def test_personal_telegram_chats_follow_the_24_hour_window_everywhere_the_business_writes_first():
    from joop import staff_reply
    from joop.followups import can_write
    from joop.models import Conversation

    day_ago, hour_ago = NOW_UTC - timedelta(hours=25), NOW_UTC - timedelta(hours=1)
    assert can_write("telegram", "777", None, NOW_UTC)  # a bot chat: always
    assert can_write("telegram", "bc:conn-1:900", hour_ago, NOW_UTC)
    assert not can_write("telegram", "bc:conn-1:900", day_ago, NOW_UTC) and not can_write("telegram", "bc:conn-1:900", None, NOW_UTC)
    assert can_write("whatsapp", "996555", hour_ago, NOW_UTC) and not can_write("whatsapp", "996555", day_ago, NOW_UTC)
    assert not can_write("console", "try", hour_ago, NOW_UTC)
    old = Conversation(business_id=1, channel="telegram", chat_id="bc:conn-1:900", last_customer_at=day_ago)
    assert "личном Telegram" in staff_reply.blocked(old, NOW_UTC)
    old.last_customer_at = hour_ago
    assert staff_reply.blocked(old, NOW_UTC) == ""
    assert staff_reply.blocked(Conversation(business_id=1, channel="telegram", chat_id="777"), NOW_UTC) == ""


def test_no_reminder_attempt_to_a_personal_telegram_chat_outside_24_hours(business, rt):
    from joop.models import Booking, Conversation, Slot
    from joop.scheduler import _send_reminder

    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.telegram_bot_token = "1:x"
        conv = Conversation(business_id=b.id, channel="telegram", chat_id="bc:conn-1:900", last_customer_at=NOW_UTC - timedelta(days=3))
        s.add_all([b, conv])
        s.flush()
        slot = s.exec(select(Slot).where(Slot.business_id == b.id)).first()
        booking = Booking(business_id=b.id, slot_id=slot.id, staff_name="Айгуль", start=slot.start, service="Чистка",
                          customer_name="Айгерим", channel="telegram", chat_id=conv.chat_id, conversation_id=conv.id)
        s.add(booking)
        s.flush()
        assert _send_reminder(s, rt, b, booking, NOW_UTC) == "" and rt.tg.sent == []
        conv.last_customer_at = NOW_UTC - timedelta(hours=2)
        assert _send_reminder(s, rt, b, booking, NOW_UTC) == "sent" and rt.tg.sent[-1][0] == "bc:conn-1:900"
