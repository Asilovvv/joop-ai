from __future__ import annotations

import dataclasses
import os
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


class FakeSender:
    def __init__(self, ok: bool = True):
        self.ok = ok
        self.sent: list[tuple[str, str]] = []
        self.templates: list[tuple[str, str, str, list[str]]] = []
        self.private: list[tuple[str, str]] = []
        self.public: list[tuple[str, str]] = []

    def send_text(self, chat_id, text):
        self.sent.append((str(chat_id), text))
        return self.ok

    def send_template(self, to, name, lang, params):
        self.templates.append((to, name, lang, list(params)))
        return self.ok

    def send_private_reply(self, comment_id, text):  # Instagram: Direct opened through a comment
        self.private = getattr(self, "private", [])
        self.private.append((comment_id, text))
        return self.ok

    def reply_to_comment(self, comment_id, text):
        self.public = getattr(self, "public", [])
        self.public.append((comment_id, text))
        return self.ok

    def refresh_token(self):
        self.refreshes = getattr(self, "refreshes", 0) + 1
        return "refreshed-token" if self.ok else None

    def get_me(self):  # Telegram getMe / Instagram /me: tests set `me` when the username matters
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
    )


@pytest.fixture(autouse=True)
def frozen_clock(monkeypatch):
    """Every test sees the same "now" (NOW_UTC) wherever the code asks for the time, so fixtures with fixed dates
    (tomorrow's slots, yesterday's visits) do not rot as the real calendar moves past them."""
    from joop import timeutil

    monkeypatch.setattr(timeutil, "clock", lambda: NOW_UTC)


@pytest.fixture(autouse=True)
def fresh_counters():
    """In-memory daily counters (signature clicks per address, comment openings, lead cooldown) start empty for every test."""
    from joop.agent import engine as agent_engine
    from joop.web import app as web_app, audit as web_audit

    web_app._daily.clear()
    web_audit._lead_by_ip.clear()
    agent_engine._admin_misses.clear()
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
