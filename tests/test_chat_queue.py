"""One thread for a chat, however many messages arrive (joop/dispatch.py).

Every webhook message is a task in the server's shared pool of 40 threads, the pool the panel's pages run in too.
A chat is answered one message at a time, so fifty messages sent to one chat used to hold fifty threads, each waiting
its turn for up to 150 seconds: one chat could stop every answer and every page."""

import threading
import time

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from joop import db, dispatch
from joop.agent import engine
from joop.agent.llm import AgentReply
from joop.channels.base import IncomingMessage
from joop.dispatch import process_incoming
from joop.models import Business, ConversationNote, Message
from joop.scheduler import Scheduler
from joop.web.app import create_app

from .conftest import NOW_UTC, FakeLLM
from .test_web import _signed


class Gated(FakeLLM):
    """Answers «ответ на: <the customer's message>». The first call waits for `gate`: the chat is being answered.
    With `slow`, the call that waits is the one for that message, whenever it comes."""

    def __init__(self, slow: str | None = None):
        super().__init__()
        self.entered, self.gate = threading.Event(), threading.Event()
        self.asked: list[str] = []
        self.slow = slow
        self._guard = threading.Lock()

    def respond(self, system, messages, schema=None):
        text = messages[-1]["content"]
        with self._guard:
            self.asked.append(text)
            waits = len(self.asked) == 1 if self.slow is None else text == self.slow
        if waits:
            self.entered.set()
            assert self.gate.wait(20), "the test never opened the gate"
        return AgentReply(f"ответ на: {text}")


def message(text: str, chat: str = "800") -> IncomingMessage:
    return IncomingMessage("telegram", chat, "text", text, "Айбек", f"tg:{chat}:{text}")


class Busy:
    """A chat whose first message («сообщение 0») is being answered in a thread of its own until `finish()`."""

    def __init__(self, rt, business_id: int, chat: str = "800"):
        self.rt, self.business_id, self.llm = rt, business_id, Gated()
        rt._llm = self.llm
        self.outcome = None
        self.thread = threading.Thread(target=self._first, args=(chat,))
        self.thread.start()
        assert self.llm.entered.wait(10)

    def _first(self, chat: str) -> None:
        self.outcome = process_incoming(self.rt, self.business_id, message("сообщение 0", chat), NOW_UTC)

    def finish(self) -> None:
        self.llm.gate.set()
        self.thread.join(30)
        assert not self.thread.is_alive()


@pytest.fixture
def busy(business, rt):
    chat = Busy(rt, business.id)
    yield chat
    chat.llm.gate.set()
    chat.thread.join(30)


def _stored(business_id: int, role: str = "customer") -> list[str]:
    with db.new_session() as s:
        return list(s.exec(select(Message.text).where(Message.business_id == business_id, Message.role == role)
                           .order_by(Message.id)).all())


def test_messages_to_a_chat_being_answered_wait_in_its_queue(business, rt, busy):
    for i in range(1, 21):  # twenty more while the first is with the model: none of them holds its thread
        assert process_incoming(rt, business.id, message(f"сообщение {i}"), NOW_UTC).skipped == "queued"
    assert len(dispatch._queues[(business.id, "telegram", "800")].waiting) == 20
    other = process_incoming(rt, business.id, message("другой чат", chat="801"), NOW_UTC)
    assert other.reply == "ответ на: другой чат"  # another chat is answered meanwhile
    busy.finish()
    wanted = [f"сообщение {i}" for i in range(21)]
    assert busy.outcome.reply == "ответ на: сообщение 0"  # the answering thread reports its own message
    assert [t for t in _stored(business.id) if t != "другой чат"] == wanted  # all kept, in arrival order
    assert [text for chat, text in rt.tg.sent if chat == "800"] == [f"ответ на: {t}" for t in wanted]  # and answered so
    assert busy.llm.asked == ["сообщение 0", "другой чат"] + wanted[1:]
    assert dispatch._queues == {} and engine._turns == {}  # nothing is kept for a chat that is quiet again
    assert process_incoming(rt, business.id, message("позже"), NOW_UTC).reply == "ответ на: позже"


def test_each_queued_message_reads_the_answers_before_it(business, rt, busy):
    for i in (1, 2):
        process_incoming(rt, business.id, message(f"сообщение {i}"), NOW_UTC)
    seen: list[list[str]] = []
    plain = busy.llm.respond

    def watching(system, messages, schema=None):
        seen.append([m["content"] for m in messages])
        return plain(system, messages, schema)

    busy.llm.respond = watching
    busy.finish()
    assert seen[-1] == ["сообщение 0", "ответ на: сообщение 0", "сообщение 1", "ответ на: сообщение 1", "сообщение 2"]


def test_a_repeated_delivery_in_the_queue_is_answered_once(business, rt, busy):
    again = message("сообщение 1")
    for _ in range(3):  # Telegram and Meta deliver a webhook again when they are unsure
        assert process_incoming(rt, business.id, again, NOW_UTC).skipped == "queued"
    busy.finish()
    assert _stored(business.id) == ["сообщение 0", "сообщение 1"] and busy.llm.asked == ["сообщение 0", "сообщение 1"]


def test_past_the_queues_limit_messages_are_not_read_and_staff_hear_once(business, rt, monkeypatch, caplog):
    monkeypatch.setattr(dispatch, "MAX_QUEUED", 3)
    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.admin_chat_ids = "-5001"
        s.add(b)
        s.commit()
    busy = Busy(rt, business.id)
    try:
        results = [process_incoming(rt, business.id, message(f"сообщение {i}"), NOW_UTC).skipped for i in range(1, 8)]
        assert results == ["queued"] * 3 + ["flood"] * 4
        notes = [text for chat, text in rt.tg.sent if chat == "-5001"]
        assert len(notes) == 1  # once for the whole burst, not once a message
        assert "В чат Telegram «Айбек» приходит слишком много сообщений подряд: больше 3 ждут ответа" in notes[0]
        assert "«Диалоги» → этот чат → «В чёрный список»" in notes[0]
    finally:
        with caplog.at_level("WARNING", logger="joop.dispatch"):
            busy.finish()
    assert _stored(business.id) == [f"сообщение {i}" for i in range(4)]  # the four that fitted
    assert any("4 telegram message(s) of business" in r.getMessage() for r in caplog.records)
    assert dispatch._queues == {}
    with db.new_session() as s:  # the dialogue says so too: without an alerts chat nobody else would
        note = s.exec(select(ConversationNote)).one()
    assert note.author == "Joop AI" and note.text.startswith(
        "ИИ не прочитал и не сохранил 4 сообщения этого чата: в очереди уже ждали ответа 3.")
    assert process_incoming(rt, business.id, message("позже"), NOW_UTC).reply == "ответ на: позже"  # the chat is not shut


def test_a_message_that_breaks_does_not_stop_the_queue(business, rt, busy, monkeypatch):
    """Whatever goes wrong with one message, the ones behind it are answered and the chat is free afterwards: a queue
    nobody empties would swallow every later message of the chat."""
    plain = dispatch.after_reply

    def breaking(rt_, business_, outcome):
        if outcome.reply in ("ответ на: сообщение 0", "ответ на: сообщение 2"):
            raise RuntimeError("bug")
        return plain(rt_, business_, outcome)

    monkeypatch.setattr(dispatch, "after_reply", breaking)
    for i in (1, 2, 3):
        process_incoming(rt, business.id, message(f"сообщение {i}"), NOW_UTC)
    busy.finish()
    assert busy.outcome.skipped == "error"  # its own message broke after the reply went out
    assert [text for chat, text in rt.tg.sent if chat == "800"] == [f"ответ на: сообщение {i}" for i in range(4)]
    assert dispatch._queues == {} and engine._turns == {}


def test_a_stuck_message_does_not_hold_its_chat_for_ever(business, rt, busy, monkeypatch, caplog):
    """The answering thread never comes back (a bug, a call without a timeout): after STUCK_AFTER the chat's next
    message takes the queue over. Late and out of order beats never."""
    monkeypatch.setattr(engine, "CHAT_WAIT", 0.1)  # the stuck thread still holds the chat's turn
    assert process_incoming(rt, business.id, message("сообщение 1"), NOW_UTC).skipped == "queued"
    monkeypatch.setattr(dispatch, "STUCK_AFTER", 0.0)  # «сообщение 0» has been in work too long
    with caplog.at_level("ERROR", logger="joop.dispatch"):
        took_over = process_incoming(rt, business.id, message("сообщение 2"), NOW_UTC)
    assert took_over.reply == "ответ на: сообщение 2"
    assert any("its chat goes on without it" in r.getMessage() for r in caplog.records)
    # What waited comes first. «сообщение 0» is stored and has no answer yet, so the model reads it with «сообщение 1».
    assert [text for chat, text in rt.tg.sent] == ["ответ на: сообщение 0\nсообщение 1", "ответ на: сообщение 2"]
    assert dispatch._queues == {}
    busy.finish()  # the stuck thread wakes at last: it finishes its own message and touches nothing else
    assert busy.outcome.reply == "ответ на: сообщение 0"
    assert _stored(business.id) == ["сообщение 0", "сообщение 1", "сообщение 2"]  # nothing twice
    assert busy.llm.asked == ["сообщение 0", "сообщение 0\nсообщение 1", "сообщение 2"]
    assert dispatch._queues == {} and engine._turns == {}


def test_the_webhooks_threads_come_back_at_once(business, rt, busy):
    """Fifty deliveries to a busy chat, each in its own thread as the webhook's background tasks are: all fifty threads
    are back while the first message is still with the model."""
    threads = [threading.Thread(target=process_incoming, args=(rt, business.id, message(f"сообщение {i}"), NOW_UTC))
               for i in range(1, 51)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert not any(t.is_alive() for t in threads) and not busy.llm.gate.is_set()
    busy.finish()
    assert sorted(_stored(business.id)) == sorted(f"сообщение {i}" for i in range(51))


# --- review of #275 -------------------------------------------------------------------------------------------------


def test_messages_that_came_together_keep_their_place(business, rt):
    """Meta puts what a person sends in a row into one POST. Answered one call after another, the second waited for
    the first to finish, and a message from a later POST, already in the chat's queue, was answered before it."""
    llm = rt._llm = Gated()
    done: list = []
    together = threading.Thread(target=lambda: done.append(
        dispatch.process_chat(rt, business.id, [message("первое"), message("второе")], NOW_UTC)))
    together.start()
    try:
        assert llm.entered.wait(10)  # «первое» is with the model
        assert process_incoming(rt, business.id, message("третье"), NOW_UTC).skipped == "queued"  # a later POST
    finally:
        llm.gate.set()
        together.join(30)
    assert [text for _, text in rt.tg.sent] == ["ответ на: первое", "ответ на: второе", "ответ на: третье"]
    assert [o.reply for o in done[0]] == ["ответ на: первое", "ответ на: второе"]  # each message's own outcome
    assert dispatch._queues == {} and engine._turns == {}


def test_chats_of_one_webhook_post_do_not_wait_for_each_other(settings, rt, business):
    """A POST of Meta carries messages of several chats, even of several businesses. One after another, a customer
    waited for every chat ahead of theirs in it: for its whole queue when that chat was being flooded."""
    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.wa_phone_number_id, b.wa_access_token = "pn-1", "tok"
        s.add(b)
        s.commit()
    llm = rt._llm = Gated(slow="Долгий вопрос")
    post = {"object": "whatsapp_business_account", "entry": [{"id": "waba", "changes": [{"field": "messages", "value": {
        "messaging_product": "whatsapp", "metadata": {"phone_number_id": "pn-1"},
        "contacts": [{"wa_id": "996555000111", "profile": {"name": "Айгуль"}}, {"wa_id": "996555000222", "profile": {"name": "Бакыт"}}],
        "messages": [{"from": "996555000111", "id": "wamid.a1", "type": "text", "text": {"body": "Долгий вопрос"}},
                     {"from": "996555000222", "id": "wamid.b1", "type": "text", "text": {"body": "Сколько стоит чистка?"}},
                     {"from": "996555000111", "id": "wamid.a2", "type": "text", "text": {"body": "И ещё вопрос"}}],
    }}]}]}
    raw, headers = _signed(post)
    with TestClient(create_app(settings, rt, init=False)) as client:
        posting = threading.Thread(target=lambda: client.post("/webhooks/meta", content=raw, headers=headers))
        posting.start()
        try:
            assert llm.entered.wait(10)  # the first chat is with the model and stays there
            waited = time.monotonic()
            while not any(chat == "996555000222" for chat, _ in rt.wa.sent) and time.monotonic() - waited < 10:
                time.sleep(0.02)
            answered_meanwhile = [text for chat, text in rt.wa.sent if chat == "996555000222"]
        finally:
            llm.gate.set()
            posting.join(30)
    # (a first answer opens with «Я ИИ-помощник…», and the model's words follow with a capital letter)
    assert len(answered_meanwhile) == 1 and answered_meanwhile[0].endswith("Ответ на: Сколько стоит чистка?")
    first_chat = [text for chat, text in rt.wa.sent if chat == "996555000111"]
    assert len(first_chat) == 2 and first_chat[0].endswith("Ответ на: Долгий вопрос")  # its two, in their order
    assert first_chat[1] == "ответ на: И ещё вопрос"
    assert dispatch._queues == {}


def test_a_taken_over_queue_waits_for_the_stuck_turn_once(business, rt, busy, monkeypatch, caplog):
    """The stuck thread still holds the chat's turn. Each message taken over used to wait CHAT_WAIT for it: ten
    waiting messages were twenty-five minutes more."""
    monkeypatch.setattr(engine, "CHAT_WAIT", 0.2)
    for i in (1, 2, 3):
        assert process_incoming(rt, business.id, message(f"сообщение {i}"), NOW_UTC).skipped == "queued"
    monkeypatch.setattr(dispatch, "STUCK_AFTER", 0.0)
    with caplog.at_level("WARNING", logger="joop.agent.engine"):
        assert process_incoming(rt, business.id, message("сообщение 4"), NOW_UTC).reply == "ответ на: сообщение 4"
    assert len([r for r in caplog.records if "goes ahead" in r.getMessage()]) == 1
    assert len([text for chat, text in rt.tg.sent if chat == "800"]) == 4 and dispatch._queues == {}


def test_the_scheduler_takes_over_a_stuck_chat_nobody_writes_to(business, rt, busy, monkeypatch):
    """Messages behind a message that never comes back were answered only when the customer wrote once more."""
    monkeypatch.setattr(engine, "CHAT_WAIT", 0.1)
    for i in (1, 2):
        process_incoming(rt, business.id, message(f"сообщение {i}"), NOW_UTC)
    assert dispatch.take_over_stuck(rt) == []  # in work for a moment: not stuck
    monkeypatch.setattr(dispatch, "STUCK_AFTER", 0.0)
    threads = dispatch.take_over_stuck(rt)
    assert len(threads) == 1
    threads[0].join(30)
    assert not threads[0].is_alive()
    assert [text for _, text in rt.tg.sent] == ["ответ на: сообщение 0\nсообщение 1", "ответ на: сообщение 2"]
    assert dispatch._queues == {} and dispatch.take_over_stuck(rt) == []
    busy.finish()  # the stuck one wakes: nothing is answered twice
    assert _stored(business.id) == ["сообщение 0", "сообщение 1", "сообщение 2"]


def test_a_stuck_message_with_nobody_behind_it_is_left_alone(business, rt, busy, monkeypatch):
    monkeypatch.setattr(dispatch, "STUCK_AFTER", 0.0)
    assert dispatch.take_over_stuck(rt) == [] and (business.id, "telegram", "800") in dispatch._queues


def test_every_tick_of_the_scheduler_looks_for_stuck_chats(business, rt, monkeypatch):
    looked: list = []
    monkeypatch.setattr(dispatch, "take_over_stuck", lambda runtime: looked.append(runtime) or [])
    Scheduler(rt, 60).tick(NOW_UTC)
    assert looked == [rt]
