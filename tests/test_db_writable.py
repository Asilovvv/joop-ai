"""A database file the app cannot write is reported, not hidden (joop/ops.py: db_write_problem).

Found in the launch rehearsal of 22 November: the restore steps of docs/deploy.md copy the file into the container
as root, the app runs as another user, and every message after that fails to save while /health said ok.
"""

import os
import sqlite3

import pytest
from fastapi.testclient import TestClient

from joop import ops
from joop.web.app import create_app

needs_permissions = pytest.mark.skipif(os.geteuid() == 0, reason="root writes any file: the case cannot be built")


def make_db(path):
    sqlite3.connect(path).execute("create table t (x)").connection.commit()
    return f"sqlite:///{path}"


def test_a_writable_database_is_fine(tmp_path):
    assert ops.db_write_problem(make_db(tmp_path / "joop.db")) is None
    assert ops.db_write_problem("sqlite://") is None and ops.db_write_problem("postgresql://x/y") is None
    assert ops.db_write_problem(f"sqlite:///{tmp_path / 'not-yet.db'}") is None  # migrate creates it


def test_a_file_the_app_cannot_write(tmp_path, monkeypatch):
    url = make_db(tmp_path / "joop.db")
    real = os.access
    monkeypatch.setattr(ops.os, "access", lambda p, mode: False if str(p).endswith("joop.db") and mode == os.W_OK else real(p, mode))
    problem = ops.db_write_problem(url)
    assert problem.startswith("нет записи в файл базы") and "chown" in problem


def test_a_folder_the_app_cannot_write(tmp_path, monkeypatch):
    """SQLite writes its -wal and -journal files beside the database."""
    url = make_db(tmp_path / "joop.db")
    real = os.access
    monkeypatch.setattr(ops.os, "access", lambda p, mode: False if str(p) == str(tmp_path) and mode == os.W_OK else real(p, mode))
    assert ops.db_write_problem(url).startswith("нет записи в папку базы")


@needs_permissions
def test_a_real_read_only_file(tmp_path):
    path = tmp_path / "joop.db"
    url = make_db(path)
    path.chmod(0o444)
    try:
        assert ops.db_write_problem(url).startswith("нет записи в файл базы")
    finally:
        path.chmod(0o644)


def test_health_says_so(settings, rt, engine, monkeypatch):
    with TestClient(create_app(settings, rt, init=False)) as c:
        assert c.get("/health").json() == {"ok": True}
        monkeypatch.setattr(ops, "db_write_problem", lambda url: "нет записи в файл базы /data/joop.db")
        r = c.get("/health")
    assert r.status_code == 503 and r.json() == {"ok": False, "error": "нет записи в файл базы /data/joop.db"}


def test_the_launch_check_says_so(settings, engine, monkeypatch):
    monkeypatch.setattr(ops, "db_write_problem", lambda url: "нет записи в файл базы /data/joop.db")
    (row,) = [c for c in ops._database_checks(settings) if c.name == "Запись в базу"]
    assert not row.ok and row.required and row.detail == "нет записи в файл базы /data/joop.db"
