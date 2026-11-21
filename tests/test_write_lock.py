"""A model call never holds the database's write lock.

SQLite lets one connection write at a time, from its first write until commit. The engine stored the customer's
message, then waited seconds for the model inside the same transaction: every other customer of every business, the
panel and the scheduler waited too. Ten customers writing at once with a 3-second model call were answered one after
another, and five of the ten got nothing: «database is locked» after the 15-second wait, their messages rolled back."""

import sqlite3
import threading
import time

from sqlmodel import select

from joop import db
from joop.agent.engine import handle_incoming
from joop.agent.llm import AgentReply
from joop.channels.base import IncomingMessage
from joop.dispatch import process_incoming
from joop.models import Business, Message
from joop.presets import create_business

from .conftest import NOW_UTC, FakeLLM, FakeRuntime


def _db_path() -> str:
    return db.get_engine().url.database


def _can_write() -> bool:
    """Whether another connection could start writing right now (it waits at most 0.2 s)."""
    con = sqlite3.connect(_db_path(), timeout=0.2)
    try:
        con.execute("BEGIN IMMEDIATE")
        con.execute("ROLLBACK")
        return True
    except sqlite3.OperationalError:
        return False
    finally:
        con.close()


class ProbingLLM(FakeLLM):
    """Records, at each model call, whether the rest of the server could still write."""

    def __init__(self, replies=None, rewrites=None):
        super().__init__(replies, rewrites)
        self.free: list[bool] = []

    def respond(self, system, messages, schema=None):
        self.free.append(_can_write())
        return super().respond(system, messages, schema)

    def rewrite_in_kyrgyz(self, text, usage):
        self.free.append(_can_write())
        return super().rewrite_in_kyrgyz(text, usage)

    def remove_false_confirmation(self, text, usage):
        self.free.append(_can_write())
        return super().remove_false_confirmation(text, usage)


class OverlapLLM(FakeLLM):
    """A one-second model call that records how many calls ran at the same time (no wall-clock limit: CI is slow)."""

    def __init__(self):
        super().__init__()
        self.running = self.most = 0
        self._guard = threading.Lock()

    def respond(self, system, messages, schema=None):
        with self._guard:
            self.running += 1
            self.most = max(self.most, self.running)
        time.sleep(1.0)
        with self._guard:
            self.running -= 1
        return AgentReply("Здравствуйте! Чем помочь?")


def _say(business_id: int, text: str, llm, ext: str, chat: str = "1001"):
    with db.new_session() as s:
        b = s.get(Business, business_id)
        out = handle_incoming(s, b, IncomingMessage("telegram", chat, "text", text, "Айбек", ext), lambda: llm, NOW_UTC)
        s.commit()
        return out


def test_the_model_call_leaves_the_database_free(business):
    llm = ProbingLLM([AgentReply("Чистка — 2 500 сом. Записать вас?")])
    out = _say(business.id, "Сколько стоит чистка?", llm, "tg:1001:1")
    assert out.reply.startswith("Чистка") and llm.free == [True]
    with db.new_session() as s:  # the customer's message and the reply are both kept
        texts = s.exec(select(Message.text).where(Message.business_id == business.id).order_by(Message.id)).all()
    assert texts == ["Сколько стоит чистка?", "Чистка — 2 500 сом. Записать вас?"]


def test_the_guard_calls_leave_it_free_too(business):
    llm = ProbingLLM([AgentReply("Вы записаны!")], rewrites=[None])  # a false «записаны», and a Kyrgyz customer
    _say(business.id, "Салам, эртең тиш тазалоо канча турат?", llm, "tg:1001:2")
    assert len(llm.free) == 3 and all(llm.free)  # the reply, the confirmation guard, the language guard


def test_a_failed_model_call_keeps_the_customers_message(business):
    llm = ProbingLLM([RuntimeError("overloaded")])
    out = _say(business.id, "Есть время завтра?", llm, "tg:1001:3")
    assert out.lead_id is not None and llm.free == [True]
    with db.new_session() as s:
        assert s.exec(select(Message).where(Message.business_id == business.id, Message.role == "customer")).first().text \
            == "Есть время завтра?"


def test_customers_of_different_businesses_are_answered_side_by_side(business, settings, engine):
    """Four model calls of one second at once run side by side, not one after another."""
    ids = [business.id]
    with db.new_session() as s:
        for i in range(3):
            b = create_business(s, slug=f"side-{i}", name=f"Клиника {i}", password="pass-12345", niche="dental", now_utc=NOW_UTC)
            b.example_ok = True
            s.add(b)
            s.commit()
            ids.append(b.id)
    llm = OverlapLLM()
    rt = FakeRuntime(settings, llm)
    outcomes: list = [None] * len(ids)

    def one(i: int) -> None:
        outcomes[i] = process_incoming(rt, ids[i], IncomingMessage("telegram", f"77{i}", "text", "Здравствуйте", "", f"tg:77{i}:1"),
                                       NOW_UTC)

    threads = [threading.Thread(target=one, args=(i,)) for i in range(len(ids))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert all(o.reply == "Здравствуйте! Чем помочь?" for o in outcomes), [o.skipped for o in outcomes]
    assert llm.most >= 2  # one after another, it would stay 1


def test_an_atomic_session_stays_one_unit(business):
    """The founder's pitch demo is rolled back whole when it fails (joop/web/saas.py sets the flag)."""
    llm = ProbingLLM([AgentReply("Ок.")])
    with db.new_session() as s:
        s.info["atomic"] = True
        b = s.get(Business, business.id)
        handle_incoming(s, b, IncomingMessage("console", "pitch", "text", "Здравствуйте", "", "pitch:1"), lambda: llm, NOW_UTC)
        s.rollback()
    assert llm.free == [False]
    with db.new_session() as s:
        assert s.exec(select(Message).where(Message.business_id == business.id)).first() is None


# --- one chat's messages take turns ------------------------------------------------------------------------------
# The global lock used to give this by accident. Without it, two messages sent in a row would be answered side by
# side: the second without the first reply in its history, and a repeated webhook delivery answered twice.


def _together(rt, business_id: int, messages: list[IncomingMessage], gap: float = 0.15) -> list:
    """Deliver the messages `gap` seconds apart, each in its own thread, as the webhook's background tasks do."""
    outcomes: list = [None] * len(messages)

    def one(i: int) -> None:
        outcomes[i] = process_incoming(rt, business_id, messages[i], NOW_UTC)

    threads = [threading.Thread(target=one, args=(i,)) for i in range(len(messages))]
    for t in threads:
        t.start()
        time.sleep(gap)
    for t in threads:
        t.join()
    return outcomes


class SlowFirstLLM(FakeLLM):
    """The first call takes half a second: long enough for the next message to arrive meanwhile."""

    def respond(self, system, messages, schema=None):
        first = not self.calls
        self.calls.append({"messages": [dict(m) for m in messages]})
        if first:
            time.sleep(0.5)
            return AgentReply("Чистка — 2 500 сом.")
        return AgentReply("Завтра свободно в 10:00.")


def test_the_second_message_of_a_chat_reads_the_first_reply(business, settings):
    """A new customer writes «Сколько стоит?» and at once «А завтра есть время?». Before, the second message was lost:
    its handler did not see the conversation the first was still creating, inserted it again, hit the unique
    constraint and was rolled back — not stored, not answered, nobody told."""
    llm = SlowFirstLLM()
    rt = FakeRuntime(settings, llm)
    outcomes = _together(rt, business.id, [
        IncomingMessage("telegram", "500", "text", "Сколько стоит чистка?", "Айбек", "tg:500:1"),
        IncomingMessage("telegram", "500", "text", "А завтра есть время?", "Айбек", "tg:500:2")])
    assert outcomes[0].reply == "Чистка — 2 500 сом." and outcomes[1].skipped == "queued"  # left to the first one's thread
    assert llm.calls[1]["messages"] == [
        {"role": "user", "content": "Сколько стоит чистка?"},
        {"role": "assistant", "content": "Чистка — 2 500 сом."},
        {"role": "user", "content": "А завтра есть время?"}]
    assert [text for _, text in rt.tg.sent] == ["Чистка — 2 500 сом.", "Завтра свободно в 10:00."]  # sent in order too


def test_a_repeated_delivery_gets_one_answer(business, settings):
    """Telegram and Meta deliver a webhook again when they are unsure: the same message id, moments apart."""
    llm = SlowFirstLLM()
    rt = FakeRuntime(settings, llm)
    same = IncomingMessage("telegram", "501", "text", "Сколько стоит чистка?", "Айбек", "tg:501:7")
    outcomes = _together(rt, business.id, [same, same, same], gap=0.05)
    assert sorted(o.skipped for o in outcomes) == ["", "queued", "queued"]  # the repeats wait, then are dropped as seen
    assert len(llm.calls) == 1 and len(rt.tg.sent) == 1
    with db.new_session() as s:
        assert len(s.exec(select(Message).where(Message.business_id == business.id, Message.role == "customer")).all()) == 1


def test_other_chats_of_the_same_business_do_not_wait(business, settings):
    llm = OverlapLLM()
    rt = FakeRuntime(settings, llm)
    outcomes = _together(rt, business.id, [IncomingMessage("telegram", f"60{i}", "text", "Здравствуйте", "", f"tg:60{i}:1")
                                           for i in range(4)], gap=0.0)
    assert all(o.reply for o in outcomes) and llm.most >= 2  # four in turn would never overlap


def test_turns_leave_nothing_behind_and_a_stuck_chat_does_not_block_forever(business, monkeypatch):
    from joop.agent import engine

    _say(business.id, "Здравствуйте", FakeLLM(), "tg:1001:20")
    assert engine._turns == {}  # no lock kept per chat that ever wrote
    monkeypatch.setattr(engine, "CHAT_WAIT", 0.2)
    with engine.chat_turn(business.id, "telegram", "1001"):  # an answer to this chat that never finishes
        done: list = []
        t = threading.Thread(target=lambda: done.append(_say(business.id, "Вы тут?", FakeLLM(), "tg:1001:21")))
        t.start()
        t.join(timeout=5)
        assert done and done[0].reply  # went ahead after the wait
    assert engine._turns == {}


def test_replies_go_out_in_order_even_when_the_first_send_is_slow(business, settings):
    """The first reply's send took longer than the whole second answer: the customer saw the answers swapped."""
    llm = SlowFirstLLM()
    rt = FakeRuntime(settings, llm)
    plain = rt.tg.send_text

    def slow_first(chat_id, text):
        if text.startswith("Чистка"):
            time.sleep(0.6)
        return plain(chat_id, text)

    rt.tg.send_text = slow_first
    _together(rt, business.id, [
        IncomingMessage("telegram", "502", "text", "Сколько стоит чистка?", "Айбек", "tg:502:1"),
        IncomingMessage("telegram", "502", "text", "А завтра есть время?", "Айбек", "tg:502:2")])
    assert [text for _, text in rt.tg.sent] == ["Чистка — 2 500 сом.", "Завтра свободно в 10:00."]
