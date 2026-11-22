"""A route that waits on the model or a messenger does not stop the rest of the server.

FastAPI runs an `async def` route on the event loop itself: a slow call made straight from one freezes every other
request, webhook and page until it returns. Found on 22 November: the site chat called the model that way, and with
three visitors writing at once and a 3-second model, /health took 8.9 s and the third visitor waited 9.2 s.
"""

import ast
import dataclasses
import pathlib
import re
import threading
import time

import pytest
from fastapi.testclient import TestClient

from joop.agent.llm import AgentReply
from joop.web import demo, webchat
from joop.web.app import create_app

from .conftest import FakeLLM

WEB = pathlib.Path(__file__).resolve().parent.parent / "joop" / "web"
# Calls that wait on the model, a messenger, Instagram or Altegio. In an `async def` they go through run_in_threadpool.
SLOW = {"handle_incoming", "respond", "draft_site", "propose", "send_text", "get_me", "notify_admins", "offer_freed",
        "connect", "channel_client"}
MODEL_SECONDS = 0.6


class Slow(FakeLLM):
    def respond(self, system, messages, schema=None):
        time.sleep(MODEL_SECONDS)
        return AgentReply("Здравствуйте! Чем помочь?")


def slow_calls(source: str, where: str) -> list[str]:
    found = []
    for fn in ast.walk(ast.parse(source)):
        if not isinstance(fn, ast.AsyncFunctionDef):
            continue
        for node in ast.walk(fn):
            if isinstance(node, ast.Call):
                f = node.func
                name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
                if name in SLOW:
                    found.append(f"{where}:{node.lineno} {fn.name} calls {name}")
    return found


def test_no_async_route_calls_the_model_or_a_messenger_itself():
    assert [c for path in sorted(WEB.glob("*.py")) for c in slow_calls(path.read_text(), path.name)] == []


def test_the_check_finds_such_a_call():
    route = ("async def chat(request):\n    data = await request.json()\n    return handle_incoming(s, b, data, rt.get_llm)\n\n"
             "async def fine(request):\n    return await run_in_threadpool(_answer, request)\n\n"
             "def _answer(request):\n    return handle_incoming(s, b, 1, rt.get_llm)\n")
    assert slow_calls(route, "x.py") == ["x.py:3 chat calls handle_incoming"]


def at_once(jobs):
    """Runs every job in its own thread at the same moment; returns how long each took, in order."""
    took = [0.0] * len(jobs)
    start = threading.Barrier(len(jobs))

    def run(i, job):
        start.wait()
        t = time.perf_counter()
        job()
        took[i] = time.perf_counter() - t

    threads = [threading.Thread(target=run, args=(i, job)) for i, job in enumerate(jobs)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    return took


def health_after(client, delay=MODEL_SECONDS / 3):
    def check():
        time.sleep(delay)  # while the visitors wait for the model
        assert client.get("/health").status_code == 200
    return check


def test_site_chat_visitors_are_answered_side_by_side(settings, rt, business):
    rt.get_llm = lambda: Slow()
    webchat.reset_limits()
    with TestClient(create_app(settings, rt, init=False)) as c:
        replies = []

        def visitor(n):
            def job():
                r = c.post("/c/aktish/chat", json={"text": "Сколько стоит чистка?", "visitor": f"{n:024x}"})
                replies.append(r.json().get("reply"))
            return job

        took = at_once([visitor(n) for n in range(3)] + [health_after(c)])
    webchat.reset_limits()
    assert replies == ["Здравствуйте! Чем помочь?"] * 3
    assert max(took[:3]) < MODEL_SECONDS * 2  # one after another it would be three model times
    assert took[3] < MODEL_SECONDS  # the server answered others meanwhile


@pytest.fixture
def site(settings, rt, engine):
    demo._by_address.clear()
    s = dataclasses.replace(settings, anthropic_api_key="test-key", site_demo_daily_limit=300)
    rt.settings = s
    rt.get_llm = lambda: Slow()
    with TestClient(create_app(s, rt, init=False)) as c:
        yield c
    demo._by_address.clear()


def test_the_site_demo_does_not_stop_the_server(site):
    csrf = re.search(r'<meta name="csrf" content="([^"]+)"', site.get("/").text).group(1)
    replies = []

    def talk():
        r = site.post("/demo/chat", json={"key": "salon", "text": "Сколько стоит стрижка?", "csrf": csrf})
        replies.append(r.status_code)

    took = at_once([talk, health_after(site)])
    assert replies == [200]
    assert took[1] < MODEL_SECONDS
