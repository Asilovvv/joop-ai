"""Pre-launch check and database backups (joop/ops.py)."""

import dataclasses
import sqlite3
from datetime import timedelta

from joop import crypto, ops

from .conftest import NOW_UTC

GOOD_ENV = {"SESSION_SECRET": "a" * 64, "TOKEN_ENCRYPTION_KEY": crypto.new_key(), "DOMAIN": "joop.kg"}


def ready_settings(settings, tmp_path):
    return dataclasses.replace(settings, anthropic_api_key="key", public_base_url="https://joop.kg", secure_cookies=True,
                               owner_password="long-owner-password", database_url=f"sqlite:///{tmp_path / 'test.db'}")


def by_name(checks):
    return {c.name.split(" (")[0]: c for c in checks}


def test_a_configured_server_is_ready(settings, engine, tmp_path):
    checks = ops.launch_checks(ready_settings(settings, tmp_path), GOOD_ENV, live=lambda: None)
    text, ready = ops.report(checks)
    assert ready, text
    assert by_name(checks)["Схема базы данных"].ok and by_name(checks)["Модель отвечает"].ok
    assert "Готово к запуску." in text
    assert "a" * 64 not in text and GOOD_ENV["TOKEN_ENCRYPTION_KEY"] not in text  # secrets never printed


def test_missing_settings_are_named_with_the_fix(settings, engine, tmp_path):
    s = dataclasses.replace(ready_settings(settings, tmp_path), public_base_url="http://1.2.3.4", anthropic_api_key="",
                            owner_password="")
    env = {"SESSION_SECRET": "short", "TOKEN_ENCRYPTION_KEY": "not-a-key", "DOMAIN": "joop.kg"}
    checks = by_name(ops.launch_checks(s, env))
    assert not checks["Ключ Anthropic"].ok and checks["Ключ Anthropic"].required
    assert not checks["Секрет сессий"].ok and "token_hex" in checks["Секрет сессий"].detail
    assert not checks["Шифрование токенов"].ok and "gen-key" in checks["Шифрование токенов"].detail
    assert not checks["Публичный адрес"].ok
    assert not checks["Домен совпадает с адресом"].ok and "1.2.3.4" in checks["Домен совпадает с адресом"].detail
    assert not checks["Консоль основателя"].ok and not checks["Консоль основателя"].required  # optional
    text, ready = ops.report(list(checks.values()))
    assert not ready and "[НУЖНО]" in text and "[МОЖНО]" in text and "Не готово" in text


def test_live_check_explains_an_empty_balance(settings, engine, tmp_path):
    problem = "Claude API call failed — Your credit balance is too low to access the Anthropic API."
    checks = by_name(ops.launch_checks(ready_settings(settings, tmp_path), GOOD_ENV, live=lambda: problem))
    assert not checks["Модель отвечает"].ok and "пополните баланс" in checks["Модель отвечает"].detail


def test_an_old_schema_is_reported(settings, engine, tmp_path):
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(text("update alembic_version set version_num = '0015'"))
    check = by_name(ops.launch_checks(ready_settings(settings, tmp_path), GOOD_ENV))["Схема базы данных"]
    assert not check.ok and "python -m joop migrate" in check.detail


def _wal_db(path):
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("create table t (x int)")
    conn.executemany("insert into t values (?)", [(i,) for i in range(100)])
    conn.commit()
    return conn  # left open: the server keeps writing while the backup runs


def test_backup_is_a_consistent_copy_and_old_ones_rotate(settings, tmp_path):
    db_file = tmp_path / "live.db"
    live = _wal_db(db_file)
    s = dataclasses.replace(settings, database_url=f"sqlite:///{db_file}", backup_keep=2)
    assert ops.backup_dir(s) == tmp_path / "backups" and ops.backup_due(s, NOW_UTC)
    paths = [ops.make_backup(s, NOW_UTC + timedelta(days=d)) for d in range(3)]
    live.close()
    folder = tmp_path / "backups"
    assert sorted(p.name for p in folder.iterdir()) == [paths[1].name, paths[2].name]  # the oldest was removed
    copy = sqlite3.connect(paths[2])
    assert copy.execute("select count(*) from t").fetchone()[0] == 100 and copy.execute("pragma integrity_check").fetchone()[0] == "ok"
    copy.close()
    assert not ops.backup_due(s, NOW_UTC + timedelta(days=2))  # today's copy exists
    assert ops.backup_due(s, NOW_UTC + timedelta(days=3))


def test_no_backup_for_memory_databases_or_when_switched_off(settings, tmp_path):
    assert ops.make_backup(dataclasses.replace(settings, database_url="sqlite://"), NOW_UTC) is None
    assert not ops.backup_due(dataclasses.replace(settings, database_url=f"sqlite:///{tmp_path / 'x.db'}", backup_keep=0), NOW_UTC)


def test_scheduler_makes_the_daily_backup(settings, engine, tmp_path, rt):
    from joop.scheduler import Scheduler

    rt.settings = dataclasses.replace(settings, database_url=f"sqlite:///{tmp_path / 'test.db'}")
    Scheduler(rt, 60).tick(NOW_UTC)
    assert (tmp_path / "backups" / f"joop-{NOW_UTC:%Y-%m-%d}.db").exists()
