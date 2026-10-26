"""SQLite storage for unanswered questions (content gaps) and quote requests (leads)."""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS unanswered (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    question TEXT NOT NULL,
    standalone_question TEXT,
    language TEXT,
    reason TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    message TEXT,
    conversation TEXT
);
"""


class Storage:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as conn:
            conn.executescript(SCHEMA)

    def log_unanswered(self, question: str, standalone_question: str | None,
                       language: str | None, reason: str) -> None:
        with self._connection() as conn:
            conn.execute(
                "INSERT INTO unanswered (created_at, question, standalone_question, language, reason)"
                " VALUES (?, ?, ?, ?, ?)",
                (_now(), question, standalone_question, language, reason),
            )

    def list_unanswered(self, limit: int = 200) -> list[dict]:
        return self._select("SELECT * FROM unanswered ORDER BY id DESC LIMIT ?", limit)

    def add_lead(self, name: str, email: str, message: str | None, conversation: list[dict]) -> int:
        with self._connection() as conn:
            cursor = conn.execute(
                "INSERT INTO leads (created_at, name, email, message, conversation)"
                " VALUES (?, ?, ?, ?, ?)",
                (_now(), name, email, message, json.dumps(conversation, ensure_ascii=False)),
            )
            return cursor.lastrowid

    def list_leads(self, limit: int = 200) -> list[dict]:
        return self._select("SELECT * FROM leads ORDER BY id DESC LIMIT ?", limit)

    def _select(self, sql: str, *params) -> list[dict]:
        with self._connection() as conn:
            return [dict(row) for row in conn.execute(sql, params)]

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
