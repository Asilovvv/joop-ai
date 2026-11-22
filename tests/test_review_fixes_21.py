"""Fixes from the independent review of #285–#289 (22 November 2026), each with the case the reviewer reproduced."""

import dataclasses
import os
import re
import sqlite3
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from joop import db, ops
from joop.agent.llm import AgentReply
from joop.models import Business, PanelUser
from joop.security import hash_password
from joop.web import demo, webchat
from joop.web.app import create_app

from .conftest import FakeLLM, database_is_free
from .test_event_loop import at_once
from .test_mobile import auth, client, sign_in  # noqa: F401
from .test_web import csrf_of, login


class Slow(FakeLLM):
    def respond(self, system, messages, schema=None):
        time.sleep(0.3)
        return AgentReply("Здравствуйте!")


def burst(n, send):
    codes = []
    at_once([lambda: codes.append(send())] * n)
    return sorted(codes)


@pytest.fixture
def site_chat(settings, rt, business):
    def make(llm):
        rt.get_llm = lambda: llm
        return TestClient(create_app(settings, rt, init=False))
    webchat.reset_limits()
    yield make
    webchat.reset_limits()


def say(c, text="Здравствуйте", visitor="a" * 24):
    return c.post("/c/aktish/chat", json={"text": text, "visitor": visitor}).status_code


def test_a_burst_from_one_visitor_gets_no_more_than_the_limit(site_chat, monkeypatch):
    """The limit was checked on the event loop and counted after the model answered: eight at once all passed."""
    monkeypatch.setattr(webchat, "PER_VISITOR", 2)
    with site_chat(Slow()) as c:
        assert burst(8, lambda: say(c)) == [200, 200] + [429] * 6


def test_a_burst_to_one_business_gets_no_more_than_its_day(site_chat, monkeypatch):
    monkeypatch.setattr(webchat, "PER_BUSINESS", 3)
    with site_chat(Slow()) as c:
        codes = burst(8, lambda: say(c, visitor=os.urandom(12).hex()))  # eight visitors: the business's limit holds
    assert codes == [200] * 3 + [429] * 5


def test_messages_the_ai_did_not_answer_do_not_count(site_chat, monkeypatch):
    monkeypatch.setattr(webchat, "PER_VISITOR", 2)
    real = webchat.handle_incoming

    def broken(*args, **kwargs):
        raise RuntimeError("the database is gone")

    monkeypatch.setattr(webchat, "handle_incoming", broken)
    with site_chat(Slow()) as c:
        assert [say(c) for _ in range(3)] == [503, 503, 503]  # not 429: none of them was answered
        monkeypatch.setattr(webchat, "handle_incoming", real)
        assert [say(c) for _ in range(3)] == [200, 200, 429]


@pytest.fixture
def site(settings, rt, engine):
    demo._by_address.clear()
    demo._refreshed.clear()
    s = dataclasses.replace(settings, anthropic_api_key="test-key", site_demo_daily_limit=300)
    rt.settings = s
    rt.get_llm = lambda: Slow()
    with TestClient(create_app(s, rt, init=False)) as c:
        c.csrf = re.search(r'<meta name="csrf" content="([^"]+)"', c.get("/").text).group(1)
        yield c
    demo._by_address.clear()


def ask_demo(c, key="salon"):
    return c.post("/demo/chat", json={"key": key, "text": "Сколько стоит?", "csrf": c.csrf}).status_code


def test_a_burst_from_one_address_gets_no_more_than_the_demo_allows(site, monkeypatch):
    monkeypatch.setattr(demo, "PER_ADDRESS", 2)
    assert burst(8, lambda: ask_demo(site)) == [200, 200] + [429] * 6


def test_the_first_visitors_of_a_demo_are_all_answered(site):
    """Each made the demo business at the same moment: one got it, the others a 500 (UNIQUE business.slug)."""
    assert burst(4, lambda: ask_demo(site, "hotel")) == [200] * 4
    with db.new_session() as s:
        assert len(s.exec(select(Business).where(Business.slug == demo.DEMO_PREFIX + "hotel")).all()) == 1


def staff_login(client, business):
    with db.new_session() as s:
        s.add(PanelUser(business_id=business.id, login="admin1", name="Администратор", password_hash=hash_password("staff-pass-123")))
        s.commit()
    token = sign_in(client, user="admin1", password="staff-pass-123").json()
    assert token["role"] == "staff"
    return auth(token["token"])


def test_only_the_owner_changes_contacts_and_hours_from_the_app(client, business):
    """As «Настройки» in the panel: an administrator's login could change the hours and the days off."""
    h = staff_login(client, business)
    before = client.get("/api/mobile/contacts", headers=h).json()  # seeing them is fine
    r = client.post("/api/mobile/contacts", headers=h, json={**before, "work_start": "03:00", "work_end": "04:00"})
    assert r.status_code == 403 and r.json()["error"] == "Настройки компании меняет владелец."
    with db.new_session() as s:
        assert s.get(Business, business.id).work_start == before["work_start"]


def test_a_field_not_sent_keeps_its_value(client, business):
    h = auth(sign_in(client).json()["token"])
    before = client.get("/api/mobile/contacts", headers=h).json()
    after = client.post("/api/mobile/contacts", headers=h, json={"address": "ул. Киевская, 1"}).json()
    assert after["address"] == "ул. Киевская, 1"
    assert {k: v for k, v in after.items() if k not in ("address", "example")} == \
        {k: v for k, v in before.items() if k not in ("address", "example")}
    assert client.post("/api/mobile/contacts", headers=h, json={"work_end": "06:00"}).status_code == 422  # before the start


def test_instagram_is_asked_with_the_database_free(settings, rt, business):
    """The duplicate-account check wrote the change first, and the lock was held while Instagram answered."""
    seen = []

    def get_me():
        seen.append(database_is_free(wait=0.3))
        return {"username": "salon"}

    rt.ig.get_me = get_me
    with TestClient(create_app(settings, rt, init=False)) as c:
        token = login(c)
        csrf = csrf_of(c.get("/panel/channels").text) or token
        r = c.post("/panel/channels", data={"csrf": csrf, "ig_account_id": "17840000", "ig_access_token": "IGQ-new"},
                   follow_redirects=False)
    assert r.status_code == 303 and seen == [True]
    with db.new_session() as s:
        assert s.get(Business, business.id).ig_username == "salon"


def test_a_wal_file_the_app_cannot_write_is_reported(tmp_path, monkeypatch):
    """Left by a process run as root: every write fails while the database file itself is writable."""
    path = tmp_path / "joop.db"
    con = sqlite3.connect(path)
    con.execute("pragma journal_mode=wal")
    con.execute("create table t (x)")
    con.commit()
    assert (tmp_path / "joop.db-wal").exists()
    real = os.access
    monkeypatch.setattr(ops.os, "access", lambda p, mode: False if str(p).endswith("-wal") and mode == os.W_OK else real(p, mode))
    try:
        assert ops.db_write_problem(f"sqlite:///{path}") == \
            f"нет записи в файл базы {path}-wal; выполните: docker compose run --rm --user root app chown -R joop /data"
    finally:
        con.close()


def test_a_folder_the_app_cannot_enter_is_reported_not_a_500(tmp_path, monkeypatch):
    def closed(self):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(Path, "exists", closed)
    assert ops.db_write_problem(f"sqlite:///{tmp_path / 'joop.db'}").startswith(f"нет доступа к папке базы {tmp_path}")


def test_database_urls_with_options_are_checked(tmp_path):
    path = tmp_path / "joop.db"
    sqlite3.connect(path).close()
    assert ops.sqlite_path(f"sqlite:///{path}?timeout=15") == path
    assert ops.sqlite_path(f"sqlite+pysqlite:///{path}") == path
    assert ops.sqlite_path("sqlite://") is None and ops.sqlite_path("postgresql://x/y") is None
