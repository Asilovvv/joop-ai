"""One thread for a chat, however many messages arrive (joop/dispatch.py).

Every webhook message is a task in the server's shared pool of 40 threads, the pool the panel's pages run in too.
A chat is answered one message at a time, so fifty messages sent to one chat used to hold fifty threads, each waiting
its turn for up to 150 seconds: one chat could stop every answer and every page."""

import threading

import pytest
from sqlmodel import select

from joop import db, dispatch
from joop.agent import engine
from joop.agent.llm import AgentReply
from joop.channels.base import IncomingMessage
from joop.dispatch import process_incoming
from joop.models import Business, Message

from .conftest import NOW_UTC, FakeLLM


class Gated(FakeLLM):
    """Answers «ответ на: <the customer's message>». The first call waits for `gate`: the chat is being answered."""

    def __init__(self):
        super().__init__()
        self.entered, self.gate = threading.Event(), threading.Event()
        self.asked: list[str] = []

    def respond(self, system, messages, schema=None):
        text = messages[-1]["content"]
        self.asked.append(text)
        if len(self.asked) == 1:
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
