"""Optional collection of question TYPES: scrubbed text + category, no identity.

Keeps what a customer asked about so the classifier can be measured and the FAQ
written. It never stores who asked: no user id, no conversation id, no case id.
Fixed-format identifiers (phone, e-mail, links, LINE ids, long numbers) are
replaced before writing; names and addresses cannot be detected, so exported
files still need a human read. Off unless ASSIST_STORE_TEXT=1; rows older than
the retention period are deleted.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from phase8.tools.anonymize import scrub

_MAX_CHARS = 2000


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class TextCollector:
    def __init__(self, db_path: str, retention_days: int = 90) -> None:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.retention_days = retention_days
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(db_path, check_same_thread=False, timeout=10)
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS collected_text ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, collected_at TEXT NOT NULL, channel TEXT NOT NULL, "
            "text TEXT NOT NULL, predicted_intent TEXT, route TEXT)"
        )
        self.conn.commit()

    def add(self, account: str, text: str, predicted_intent: str | None, route: str | None,
            now: datetime | None = None) -> bool:
        clean = scrub((text or "").strip())[:_MAX_CHARS]
        if not clean:
            return False
        now = now or datetime.now(timezone.utc)
        channel = (account or "").split(":", 1)[0] or "unknown"
        with self._lock:
            self.conn.execute(
                "INSERT INTO collected_text(collected_at,channel,text,predicted_intent,route) VALUES(?,?,?,?,?)",
                (_iso(now), channel, clean, predicted_intent, route),
            )
            self.conn.execute("DELETE FROM collected_text WHERE collected_at<?",
                              (_iso(now - timedelta(days=self.retention_days)),))
            self.conn.commit()
        return True

    def rows(self) -> list[tuple]:
        with self._lock:
            return self.conn.execute(
                "SELECT collected_at,channel,text,predicted_intent,route FROM collected_text ORDER BY id"
            ).fetchall()
