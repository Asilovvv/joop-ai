"""The daily backup also leaves the server: encrypted, to the founder's Telegram (joop/offsite.py)."""

import dataclasses
import sqlite3

import httpx
import pytest

from joop import crypto, offsite, ops
from joop.__main__ import main

from .conftest import NOW_UTC


def _database(tmp_path):
    db_file = tmp_path / "joop.db"
    con = sqlite3.connect(db_file)
    con.execute("CREATE TABLE lead (phone TEXT)")
    con.execute("INSERT INTO lead VALUES ('+996700123456')")
    con.commit()
    con.close()
    return db_file


class Telegram:
    def __init__(self, ok=True):
        self.ok, self.requests = ok, []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(200, json={"ok": self.ok, "result": {}} if self.ok else {"ok": False, "description": "x"})


@pytest.fixture
def setup(settings, tmp_path, monkeypatch):
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", crypto.new_key())
    s = dataclasses.replace(settings, database_url=f"sqlite:///{_database(tmp_path)}", founder_bot_token="123:abc",
                            founder_chat_id="42", telegram_api_base="https://api.telegram.test")
    return s, ops.make_backup(s, NOW_UTC)


def test_the_copy_is_sent_encrypted_and_can_be_restored(setup, tmp_path):
    s, backup = setup
    tg = Telegram()
    assert offsite.send(httpx.Client(transport=httpx.MockTransport(tg)), s, backup)
    request = tg.requests[0]
    assert request.url.path.endswith("/sendDocument")
    body = request.content
    assert b"+996700123456" not in body and b"SQLite format 3" not in body  # customers' data never leaves in the clear
    assert b"joop-2026-" in body and b".db.gz.enc" in body and b'name="disable_notification"' in body

    sealed = body.split(b"application/octet-stream\r\n\r\n", 1)[1].rsplit(b"\r\n--", 1)[0]
    (tmp_path / "copy.enc").write_bytes(sealed)
    out = offsite.restore(tmp_path / "copy.enc", tmp_path / "restored.db")
    assert sqlite3.connect(out).execute("SELECT phone FROM lead").fetchone() == ("+996700123456",)


def test_never_sent_without_a_key_or_founder_bot(setup, monkeypatch):
    s, backup = setup
    tg = Telegram()
    client = httpx.Client(transport=httpx.MockTransport(tg))
    assert not offsite.send(client, dataclasses.replace(s, founder_chat_id=""), backup)
    assert not offsite.send(client, dataclasses.replace(s, backup_to_telegram=False), backup)
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", "")
    assert not offsite.send(client, s, backup)
    assert tg.requests == []


def test_a_rejected_upload_is_reported_not_raised(setup):
    s, backup = setup
    assert not offsite.send(httpx.Client(transport=httpx.MockTransport(Telegram(ok=False))), s, backup)


def test_too_large_for_telegram_tells_the_founder_instead(setup, monkeypatch):
    s, backup = setup
    monkeypatch.setattr(offsite, "MAX_BYTES", 10)
    tg = Telegram()
    assert not offsite.send(httpx.Client(transport=httpx.MockTransport(tg)), s, backup)
    assert [r.url.path.rsplit("/", 1)[1] for r in tg.requests] == ["sendMessage"]
    assert "больше 50 МБ" in tg.requests[0].content.decode()


def test_restore_refuses_a_wrong_key_and_an_existing_file(setup, tmp_path, monkeypatch):
    _, backup = setup
    sealed = tmp_path / "copy.enc"
    sealed.write_bytes(offsite.seal(backup.read_bytes(), offsite._key()))
    with pytest.raises(offsite.CopyError, match="уже есть"):
        offsite.restore(sealed, backup)
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", crypto.new_key())
    with pytest.raises(offsite.CopyError, match="Ключ не подходит"):
        offsite.restore(sealed, tmp_path / "out.db")


def test_restore_copy_command(setup, tmp_path, capsys):
    _, backup = setup
    sealed = tmp_path / "copy.enc"
    sealed.write_bytes(offsite.seal(backup.read_bytes(), offsite._key()))
    assert main(["restore-copy", str(sealed), "--out", str(tmp_path / "back.db")]) == 0
    assert "восстановлена" in capsys.readouterr().out
    assert main(["restore-copy", str(sealed), "--out", str(tmp_path / "back.db")]) == 1  # never overwrites


def test_the_launch_check_names_a_missing_offsite_copy(settings, engine, tmp_path):
    env = {"SESSION_SECRET": "a" * 64, "TOKEN_ENCRYPTION_KEY": crypto.new_key(), "DOMAIN": "joop.kg"}
    name = "Копия базы вне сервера (в Telegram основателя)"
    off = {c.name: c for c in ops.launch_checks(settings, env)}[name]
    on = {c.name: c for c in ops.launch_checks(dataclasses.replace(settings, founder_bot_token="1:a", founder_chat_id="4"), env)}[name]
    assert not off.ok and not off.required and on.ok


def test_the_scheduler_sends_each_new_daily_copy_once(engine, settings, rt, tmp_path, monkeypatch):
    from joop.scheduler import Scheduler

    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", crypto.new_key())
    rt.settings = dataclasses.replace(settings, database_url=f"sqlite:///{_database(tmp_path)}", backup_keep=3,
                                      founder_bot_token="1:a", founder_chat_id="42")
    sent: list = []
    monkeypatch.setattr(offsite, "send", lambda http, s, path: sent.append(path.name) or True)
    sched = Scheduler(rt, interval=60)
    sched.tick(NOW_UTC)
    sched.tick(NOW_UTC)  # the same day: the copy exists, nothing sent again
    assert sent == [f"joop-{NOW_UTC:%Y-%m-%d}.db"]
