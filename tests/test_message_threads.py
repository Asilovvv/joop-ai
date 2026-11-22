"""Customers are answered in threads of their own; the panel keeps its threads (joop/workers.py).

Starlette serves every sync page and runs every background task in one pool of 40 threads. A burst of customer chats
took all of them while the model thought: with 150 chats at once and a 3-second model, the login page took 9 s.
"""

import time

import anyio.from_thread
import anyio.to_thread
import pytest
from fastapi.testclient import TestClient

from joop import db, workers
from joop.agent.llm import AgentReply
from joop.models import Business
from joop.web import webchat
from joop.web.app import create_app

from .conftest import FakeLLM
from .test_event_loop import at_once
from .test_web import _signed

MODEL_SECONDS = 0.5


def lent() -> tuple[int, int]:
    """Threads lent right now by the pool of pages and by the pool of customers (read on the event loop)."""
    def read():
        return int(anyio.to_thread.current_default_thread_limiter().borrowed_tokens), int(workers.limiter().borrowed_tokens)
    return anyio.from_thread.run_sync(read)


class Watching(FakeLLM):
    """A model that notes, while it thinks, whose thread it holds."""

    def __init__(self, seconds=0.0):
        super().__init__()
        self.seconds, self.seen = seconds, []

    def respond(self, system, messages, schema=None):
        self.seen.append(lent())
        time.sleep(self.seconds)
        return AgentReply("Здравствуйте! Чем помочь?")


@pytest.fixture
def app_with(settings, rt, business):
    def make(llm):
        rt.get_llm = lambda: llm
        rt._llm = llm
        with db.new_session() as s:
            b = s.get(Business, business.id)
            b.wa_phone_number_id, b.wa_access_token = "pn-1", "tok"
            s.add(b)
            s.commit()
        return TestClient(create_app(settings, rt, init=False))
    webchat.reset_limits()
    yield make
    webchat.reset_limits()


def telegram(client, business, chat):
    update = {"update_id": chat, "message": {"message_id": chat, "chat": {"id": chat, "type": "private"},
                                             "from": {"id": chat, "first_name": "Айбек"}, "text": "Сколько стоит чистка?"}}
    assert client.post("/webhooks/telegram/aktish", json=update,
                       headers={"X-Telegram-Bot-Api-Secret-Token": business.telegram_secret}).status_code == 200


def whatsapp(client):
    raw, headers = _signed({"object": "whatsapp_business_account", "entry": [{"id": "waba", "changes": [{"field": "messages", "value": {
        "messaging_product": "whatsapp", "metadata": {"phone_number_id": "pn-1"},
        "contacts": [{"wa_id": "996555000111", "profile": {"name": "Айгуль"}}],
        "messages": [{"from": "996555000111", "id": "wamid.1", "type": "text", "text": {"body": "Здравствуйте"}}],
    }}]}]})
    assert client.post("/webhooks/meta", content=raw, headers=headers).text == "EVENT_RECEIVED"


def test_every_channel_answers_in_the_customers_threads(app_with, business):
    llm = Watching()
    with app_with(llm) as c:
        telegram(c, business, 1001)
        whatsapp(c)
        assert c.post("/c/aktish/chat", json={"text": "Здравствуйте", "visitor": "a" * 24}).json()["reply"]
    assert llm.seen == [(0, 1)] * 3  # the pages' pool lent nothing; the customers' pool lent the one thread


def page_meanwhile(client):
    def job():
        time.sleep(MODEL_SECONDS / 3)  # while the customers wait for the model
        assert client.get("/login").status_code == 200
    return job


def test_pages_open_while_customers_hold_more_threads_than_pages_have(app_with, business):
    with app_with(Watching(MODEL_SECONDS)) as c:
        async def two_threads_for_pages():
            anyio.to_thread.current_default_thread_limiter().total_tokens = 2
        c.portal.call(two_threads_for_pages)
        ended = at_once([lambda n=n: telegram(c, business, 2000 + n) for n in range(4)] + [page_meanwhile(c)])
    assert ended[4] < min(ended[:4])  # before: the page waited for two of the four answers
    assert max(ended[:4]) < MODEL_SECONDS * 2  # four customers, two page threads: all four answered at once


def test_the_customers_threads_have_their_own_limit(app_with, business, monkeypatch):
    monkeypatch.setattr(workers, "THREADS", 2)
    llm = Watching(MODEL_SECONDS)
    with app_with(llm) as c:
        ended = at_once([lambda n=n: telegram(c, business, 3000 + n) for n in range(4)])
    assert max(ended) >= MODEL_SECONDS * 2  # two at a time: the last two waited for a free thread
    assert max(n for _, n in llm.seen) == 2 and {pages for pages, _ in llm.seen} == {0}
