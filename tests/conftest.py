from __future__ import annotations

import dataclasses
import os
import sqlite3
import traceback
from datetime import datetime

import pytest
from sqlmodel import select

os.environ.setdefault("SESSION_SECRET", "test-session-secret-0123456789abcdef")

from joop import db  # noqa: E402
from joop.agent.llm import AgentReply  # noqa: E402
from joop.config import settings_from_env  # noqa: E402
from joop.models import Business, Slot  # noqa: E402
from joop.presets import create_business  # noqa: E402
from joop.runtime import Runtime  # noqa: E402

# Wednesday 4 November 2026, 23:14 in Bishkek (UTC+6): outside working hours.
NOW_UTC = datetime(2026, 11, 4, 17, 14)


class FakeLLM:
    """Returns scripted replies. An item may be an AgentReply, an exception, or a callable(system, messages).

    `rewrites` scripts the Kyrgyz language guard: strings to return, or None for a failed call.
    """

    model = "claude-haiku-5-5"

    def __init__(self, replies=None, rewrites=None):
        self.replies = list(replies or [])
        self.rewrites = list(rewrites or [])
        self.calls: list[dict] = []
        self.rewrite_calls: list[str] = []

    def remove_false_confirmation(self, text, usage):
        self.unconfirm_calls = getattr(self, "unconfirm_calls", []) + [text]
        fixes = getattr(self, "unconfirm", [])
        return fixes.pop(0) if fixes else None

    def rewrite_in_kyrgyz(self, text, usage):
        self.rewrite_calls.append(text)
        usage["input_tokens"] += 30
        usage["output_tokens"] += 25
        return self.rewrites.pop(0) if self.rewrites else None

    def respond(self, system, messages, schema=None):
        self.calls.append({"system": system, "messages": messages, "schema": schema})
        item = self.replies.pop(0) if self.replies else AgentReply("Здравствуйте! Чем помочь?")
        if callable(item) and not isinstance(item, AgentReply):
            item = item(system, messages)
        if isinstance(item, Exception):
            raise item
        return item


LOCKED_SENDS: list[str] = []  # sends made inside a write transaction: every test must leave this empty


def database_is_free(wait: float = 1.0) -> bool:
    """Whether another connection could write now — and it does write, as another customer's message would.

    SQLite lets one connection write at a time, from its first write to commit; a caller that talks to a messenger or
    the model inside that stops every other writer on the server. `wait`: a write of another thread is over in
    milliseconds, the caller's own lasts as long as this check.

    The write is real (a counter in the file's header) because of the second way to break: a caller that READ inside
    an open transaction (a savepoint) before its network call writes on a stale snapshot afterwards, and SQLite
    refuses at once with «database is locked» if anybody wrote meanwhile. On a busy server somebody always has."""
    eng = db._engine
    path = eng.url.database if eng is not None and eng.url.get_backend_name() == "sqlite" else None
    if not path or path == ":memory:":
        return True
    con = sqlite3.connect(path, timeout=wait, isolation_level=None)
    try:
        con.execute("BEGIN IMMEDIATE")
        (version,) = con.execute("PRAGMA user_version").fetchone()
        con.execute(f"PRAGMA user_version = {version + 1}")
        con.execute("COMMIT")
        return True
    except sqlite3.OperationalError:
        return False
    finally:
        con.close()


def _sending() -> None:
    if not database_is_free():
        chain = [f"{os.path.basename(f.filename)}:{f.name}" for f in traceback.extract_stack() if "/joop/" in f.filename.replace(os.sep, "/")]
        LOCKED_SENDS.append(" > ".join(chain[-4:]) or "called by the test with its own changes not committed")


class FakeSender:
    """A channel client that records what was sent. Every send also checks that the database is free (LOCKED_SENDS)."""

    def __init__(self, ok: bool = True):
        self.ok = ok
        self.sent: list[tuple[str, str]] = []
        self.templates: list[tuple[str, str, str, list[str]]] = []
        self.private: list[tuple[str, str]] = []
        self.public: list[tuple[str, str]] = []

    def send_text(self, chat_id, text):
        _sending()
        self.sent.append((str(chat_id), text))
        return self.ok

    def send_template(self, to, name, lang, params):
        _sending()
        self.templates.append((to, name, lang, list(params)))
        return self.ok

    def send_private_reply(self, comment_id, text):  # Instagram: Direct opened through a comment
        _sending()
        self.private = getattr(self, "private", [])
        self.private.append((comment_id, text))
        return self.ok

    def reply_to_comment(self, comment_id, text):
        _sending()
        self.public = getattr(self, "public", [])
        self.public.append((comment_id, text))
        return self.ok

    def refresh_token(self):
        self.refreshes = getattr(self, "refreshes", 0) + 1
        return "refreshed-token" if self.ok else None

    def get_me(self):  # Telegram getMe / Instagram /me: tests set `me` when the username matters
        _sending()
        return dict(getattr(self, "me", {}) or {})


class FakeRuntime(Runtime):
    def __init__(self, settings, llm=None):
        super().__init__(settings, llm=llm or FakeLLM())
        self.tg = FakeSender()
        self.wa = FakeSender()
        self.ig = FakeSender()

    def telegram(self, business):
        return self.tg if business.telegram_bot_token else None

    def whatsapp(self, business):
        return self.wa if (business.wa_phone_number_id and business.wa_access_token) else None

    def instagram(self, business):
        return self.ig if (business.ig_account_id and business.ig_access_token) else None


@pytest.fixture
def settings():
    return dataclasses.replace(
        settings_from_env(),
        database_url="sqlite://",
        meta_verify_token="verify-me",
        meta_app_secret="app-secret",
        public_base_url="https://joop.test",
        scheduler_enabled=False,
        anthropic_api_key="",
        llm_provider="anthropic",
        llm_base_url="",
        llm_api_key="",
    )


@pytest.fixture(autouse=True)
def frozen_clock(monkeypatch):
    """Every test sees the same "now" (NOW_UTC) wherever the code asks for the time, so fixtures with fixed dates
    (tomorrow's slots, yesterday's visits) do not rot as the real calendar moves past them."""
    from joop import timeutil

    monkeypatch.setattr(timeutil, "clock", lambda: NOW_UTC)


@pytest.fixture(autouse=True)
def no_send_inside_a_write_transaction():
    """Store, then send (db.free): a message sent while its caller holds the database's write lock stops every other
    customer's message, the panel and the scheduler until the messenger answers. Checked for every send of every test."""
    LOCKED_SENDS.clear()
    yield
    if LOCKED_SENDS:
        found = "; ".join(sorted(set(LOCKED_SENDS)))
        LOCKED_SENDS.clear()
        pytest.fail(f"Sent while the database was write-locked (commit first: db.free): {found}")


@pytest.fixture(autouse=True)
def fresh_counters():
    """In-memory daily counters (signature clicks per address, comment openings, lead cooldown) start empty for every test."""
    from joop.agent import engine as agent_engine
    from joop.web import app as web_app, audit as web_audit

    from joop.web import booking_page

    web_app._daily.clear()
    web_audit._lead_by_ip.clear()
    booking_page.reset_limits()
    from joop.web import mobile as web_mobile

    web_mobile._signups.clear()
    agent_engine._admin_misses.clear()
    from joop import altegio, health

    altegio._on_the_way.clear()  # slot ids repeat from test to test (a fresh database each)
    health.use_provider("Anthropic API")  # the last Runtime made names the provider: not the previous test's
    yield


@pytest.fixture
def engine(tmp_path):
    eng = db.make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    db.set_engine(eng)
    db.init_db()
    yield eng
    eng.dispose()
    db.set_engine(None)


@pytest.fixture
def business(engine) -> Business:
    with db.new_session() as s:
        b = create_business(s, slug="aktish", name="Ак-Тиш Дент", password="secret-pass", demo=True, now_utc=NOW_UTC)
        b.example_ok = True  # this clinic's price list, doctors and answers are its own (they equal the dental example)
        b.telegram_bot_token = "123:TEST"
        s.add(b)
        s.commit()
        return b


@pytest.fixture
def llm():
    return FakeLLM()


@pytest.fixture
def rt(settings, llm):
    return FakeRuntime(settings, llm)


def first_free_slot(business_id: int) -> Slot:
    with db.new_session() as s:
        return s.exec(
            select(Slot).where(Slot.business_id == business_id, Slot.status == "free").order_by(Slot.start)
        ).first()
