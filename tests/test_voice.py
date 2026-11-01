"""Voice messages: download, speech-to-text, then the same engine as a typed message (joop/voice.py)."""

import dataclasses

import httpx
from sqlmodel import select

from joop import db, voice
from joop.agent.llm import AgentReply
from joop.channels.meta import InstagramClient, WhatsAppClient, parse_instagram, parse_whatsapp
from joop.channels.telegram import TelegramClient, parse_update
from joop.dispatch import process_incoming
from joop.models import Lead, Message
from joop.ops import launch_checks

from .conftest import NOW_UTC, FakeLLM

AUDIO = b"OggS-fake-voice"


def tg_voice(caption=""):
    msg = {"message_id": 7, "chat": {"id": 42, "type": "private"}, "from": {"id": 42, "first_name": "Айбек"},
           "voice": {"file_id": "VOICE-1", "duration": 4}}
    if caption:
        msg["caption"] = caption
    return parse_update({"update_id": 1, "message": msg})


def test_channels_keep_where_to_download_a_voice_message():
    assert (tg_voice().kind, tg_voice().media_label, tg_voice().media_ref) == ("media", "голосовое сообщение", "VOICE-1")
    photo = parse_update({"update_id": 2, "message": {"message_id": 8, "chat": {"id": 42, "type": "private"},
                                                      "from": {"id": 42}, "photo": [{"file_id": "P"}]}})
    assert photo.media_ref == ""  # only voice and audio are downloaded
    wa = {"object": "whatsapp_business_account", "entry": [{"changes": [{"field": "messages", "value": {
        "metadata": {"phone_number_id": "pn-1"},
        "messages": [{"from": "996555000111", "id": "wamid.1", "type": "audio", "audio": {"id": "MEDIA-9", "voice": True}}]}}]}]}
    [(_, m)] = parse_whatsapp(wa)
    assert (m.kind, m.media_label, m.media_ref) == ("media", "голосовое сообщение", "MEDIA-9")
    ig = {"object": "instagram", "entry": [{"id": "ig-1", "messaging": [{"sender": {"id": "u1"}, "recipient": {"id": "ig-1"},
          "message": {"mid": "m1", "attachments": [{"type": "audio", "payload": {"url": "https://cdn.fbsbx.com/v/a.mp4"}}]}}]}]}
    [(_, m)] = parse_instagram(ig)
    assert m.media_ref == "https://cdn.fbsbx.com/v/a.mp4"


def _http(routes, seen):
    def handler(request):
        seen.append(request)
        for prefix, response in routes.items():
            if str(request.url).startswith(prefix):
                return response(request) if callable(response) else response
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_downloads_per_channel():
    seen = []
    http = _http({
        "https://tg.test/botT0K/getFile": httpx.Response(200, json={"ok": True, "result": {"file_path": "voice/a.oga", "file_size": 15}}),
        "https://tg.test/file/botT0K/voice/a.oga": httpx.Response(200, content=AUDIO),
        "https://graph.test/v26.0/MEDIA-9": httpx.Response(200, json={"url": "https://lookaside.fbsbx.com/x", "file_size": 15}),
        "https://lookaside.fbsbx.com/x": httpx.Response(200, content=AUDIO),
        "https://cdn.fbsbx.com/v/a.mp4": httpx.Response(200, content=AUDIO),
    }, seen)
    assert TelegramClient(http, "https://tg.test", "T0K").download("VOICE-1") == AUDIO
    assert WhatsAppClient(http, "https://graph.test", "v26.0", "pn-1", "wa-tok").download("MEDIA-9") == AUDIO
    assert all(r.headers.get("authorization") == "Bearer wa-tok" for r in seen if "fbsbx" in str(r.url) or "graph" in str(r.url))
    ig = InstagramClient(http, "https://graph.instagram.test", "v26.0", "ig-1", "ig-tok")
    assert ig.download("https://cdn.fbsbx.com/v/a.mp4") == AUDIO
    assert ig.download("https://evil.test/a.mp4") is None and ig.download("http://cdn.fbsbx.com/a") is None  # only Meta's https
    big = _http({"https://tg.test/botT0K/getFile": httpx.Response(200, json={"ok": True, "result": {"file_path": "v", "file_size": 11 * 2**20}})}, [])
    assert TelegramClient(big, "https://tg.test", "T0K").download("VOICE-1") is None  # over 10 MB: not downloaded


def test_elevenlabs_request_and_answer(settings):
    seen = []
    http = _http({"https://stt.test/v1/speech-to-text": httpx.Response(200, json={"language_code": "kir", "text": "  Саламатсызбы,\n баасы канча?  "})}, seen)
    stt = voice.make_transcriber(dataclasses.replace(settings, stt_provider="elevenlabs", stt_api_key="k-1", stt_api_base="https://stt.test"), http)
    assert stt.transcribe(AUDIO) == "Саламатсызбы, баасы канча?"
    request = seen[0]
    assert request.headers["xi-api-key"] == "k-1" and b'name="model_id"' in request.content and b"scribe_v2" in request.content
    assert b'name="file"' in request.content and AUDIO in request.content
    assert voice.make_transcriber(settings, http) is None  # off by default
    failing = _http({"https://stt.test": httpx.Response(500)}, [])
    assert voice.ElevenLabsTranscriber(failing, "k", "scribe_v2", "https://stt.test").transcribe(AUDIO) is None


class FakeStt:
    def __init__(self, text):
        self.text, self.calls = text, []

    def transcribe(self, audio):
        self.calls.append(audio)
        return self.text


class FakeTelegram:
    def __init__(self, rt_sender):
        self.sender = rt_sender

    def send_text(self, chat_id, text):
        return self.sender.send_text(chat_id, text)

    def download(self, file_id):
        return AUDIO if file_id == "VOICE-1" else None


def wire(rt, text):
    stt = FakeStt(text)
    rt.transcriber = lambda: stt
    rt.telegram = lambda business: FakeTelegram(rt.tg) if business.telegram_bot_token else None
    return stt


def test_voice_is_answered_like_text(business, rt):
    stt = wire(rt, "Сколько стоит консультация?")
    rt._llm = FakeLLM([AgentReply("Консультация — 500 сом.")])
    out = process_incoming(rt, business.id, tg_voice(), NOW_UTC)
    assert out.reply == "Консультация — 500 сом." and stt.calls == [AUDIO]
    assert rt._llm.calls[0]["messages"][-1]["content"].endswith("Сколько стоит консультация?")
    assert ("42", "Консультация — 500 сом.") in rt.tg.sent
    with db.new_session() as s:
        texts = s.exec(select(Message.text).where(Message.role == "customer")).all()
        assert texts == ["[голосовое] Сколько стоит консультация?"]  # staff see it was a voice message
        assert s.exec(select(Lead)).first() is None


def test_without_recognition_a_voice_message_goes_to_staff_as_before(business, rt):
    rt._llm = FakeLLM([])
    out = process_incoming(rt, business.id, tg_voice(), NOW_UTC)  # STT not set up
    assert out.lead_id is not None and rt._llm.calls == []
    wire(rt, None)  # recognised nothing
    out = process_incoming(rt, business.id, dataclasses.replace(tg_voice(), external_id="tg:42:8"), NOW_UTC)
    assert out.lead_id is not None and rt._llm.calls == []


def test_launch_check_mentions_voice(settings):
    names = {c.name: c for c in launch_checks(settings, {}, live=False)}
    check = names["Голосовые сообщения (STT_PROVIDER, STT_API_KEY)"]
    assert not check.ok and not check.required
