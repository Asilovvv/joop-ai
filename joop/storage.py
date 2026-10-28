"""SQLite storage for conversation history, leads and handoff state."""

from __future__ import annotations

import csv
import io
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Lead:
    id: int
    chat_id: int
    name: str
    phone: str
    service: str
    preferred_time: str
    comment: str
    created_at: str


SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages(chat_id, id);

CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    phone TEXT NOT NULL,
    service TEXT NOT NULL,
    preferred_time TEXT NOT NULL DEFAULT '',
    comment TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cache_write_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chats (
    chat_id INTEGER PRIMARY KEY,
    display_name TEXT NOT NULL DEFAULT '',
    handoff INTEGER NOT NULL DEFAULT 0,
    handoff_reason TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);
"""


class Storage:
    """Thin synchronous wrapper around SQLite. Calls are short, so it is
    safe to use from async handlers for MVP-scale traffic."""

    def __init__(self, path: str = "joop.db") -> None:
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    # --- conversation history -------------------------------------------
    def add_message(self, chat_id: int, role: str, content: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO messages (chat_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                (chat_id, role, content, _now()),
            )
            self._conn.commit()

    def history(self, chat_id: int, limit: int = 20) -> list[dict]:
        """Return the last `limit` messages in chronological order,
        trimmed so the list starts with a user turn (API requirement)."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT role, content FROM messages WHERE chat_id = ? ORDER BY id DESC LIMIT ?",
                (chat_id, limit),
            ).fetchall()
        msgs = [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]
        while msgs and msgs[0]["role"] != "user":
            msgs.pop(0)
        return msgs

    def clear_history(self, chat_id: int) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))
            self._conn.commit()

    # --- leads -----------------------------------------------------------
    def add_lead(
        self,
        chat_id: int,
        name: str,
        phone: str,
        service: str,
        preferred_time: str = "",
        comment: str = "",
    ) -> Lead:
        created = _now()
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO leads (chat_id, name, phone, service, preferred_time, comment, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (chat_id, name, phone, service, preferred_time, comment, created),
            )
            self._conn.commit()
            lead_id = cur.lastrowid
        return Lead(lead_id, chat_id, name, phone, service, preferred_time, comment, created)

    def recent_leads(self, limit: int = 20) -> list[Lead]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM leads ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [Lead(**dict(r)) for r in rows]

    def leads_csv(self) -> bytes:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM leads ORDER BY id").fetchall()
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["id", "chat_id", "name", "phone", "service", "preferred_time", "comment", "created_at"])
        for r in rows:
            writer.writerow([r[k] for k in r.keys()])
        # BOM so Excel opens Cyrillic correctly
        return ("﻿" + buf.getvalue()).encode("utf-8")

    # --- token usage -----------------------------------------------------
    def add_usage(self, chat_id: int, model: str, usage: dict, cost_usd: Optional[float]) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO usage (chat_id, model, input_tokens, output_tokens, cache_write_tokens,"
                " cache_read_tokens, cost_usd, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    chat_id,
                    model,
                    usage.get("input_tokens", 0),
                    usage.get("output_tokens", 0),
                    usage.get("cache_creation_input_tokens", 0),
                    usage.get("cache_read_input_tokens", 0),
                    cost_usd,
                    _now(),
                ),
            )
            self._conn.commit()

    # --- chats / handoff -------------------------------------------------
    def _upsert_chat(self, chat_id: int) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO chats (chat_id, updated_at) VALUES (?, ?)", (chat_id, _now())
        )

    def set_display_name(self, chat_id: int, name: str) -> None:
        with self._lock:
            self._upsert_chat(chat_id)
            self._conn.execute(
                "UPDATE chats SET display_name = ?, updated_at = ? WHERE chat_id = ?",
                (name, _now(), chat_id),
            )
            self._conn.commit()

    def set_handoff(self, chat_id: int, on: bool, reason: str = "") -> None:
        with self._lock:
            self._upsert_chat(chat_id)
            self._conn.execute(
                "UPDATE chats SET handoff = ?, handoff_reason = ?, updated_at = ? WHERE chat_id = ?",
                (1 if on else 0, reason, _now(), chat_id),
            )
            self._conn.commit()

    def is_handoff(self, chat_id: int) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT handoff FROM chats WHERE chat_id = ?", (chat_id,)
            ).fetchone()
        return bool(row and row["handoff"])

    def stats(self) -> dict:
        with self._lock:
            q = lambda sql: self._conn.execute(sql).fetchone()[0]  # noqa: E731
            return {
                "chats": q("SELECT COUNT(DISTINCT chat_id) FROM messages"),
                "messages": q("SELECT COUNT(*) FROM messages"),
                "leads": q("SELECT COUNT(*) FROM leads"),
                "handoffs_open": q("SELECT COUNT(*) FROM chats WHERE handoff = 1"),
                "replies": q("SELECT COUNT(*) FROM usage"),
                "input_tokens": q("SELECT COALESCE(SUM(input_tokens), 0) FROM usage"),
                "output_tokens": q("SELECT COALESCE(SUM(output_tokens), 0) FROM usage"),
                "cost_usd": q("SELECT COALESCE(SUM(cost_usd), 0) FROM usage"),
            }
