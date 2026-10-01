"""Persistência: comentários vistos, rascunhos e fila de aprovação."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .config import DATA_DIR

SCHEMA = """
CREATE TABLE IF NOT EXISTS comments (
    id            TEXT PRIMARY KEY,
    media_id      TEXT,
    author        TEXT,
    text          TEXT,
    sentiment     TEXT,
    sentiment_conf REAL,
    created_at    TEXT,
    processed_at  TEXT,
    status        TEXT DEFAULT 'new'
);

CREATE TABLE IF NOT EXISTS drafts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    comment_id    TEXT UNIQUE,
    media_id      TEXT,
    author        TEXT,
    comment_text  TEXT,
    sentiment     TEXT,
    sentiment_conf REAL,
    reply_text    TEXT,
    action        TEXT,
    confidence    REAL,
    motivo        TEXT,
    engine        TEXT,
    decision      TEXT,
    decision_reason TEXT,
    state         TEXT DEFAULT 'pending',   -- pending|approved|rejected|published|failed|skipped
    created_at    TEXT,
    decided_at    TEXT,
    published_at  TEXT,
    published_id  TEXT,
    error         TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: Path | None = None):
        self.path = Path(path or (DATA_DIR / "responder.sqlite3"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # ------------------------------------------------------------ comments
    def seen(self, comment_id: str) -> bool:
        cur = self.conn.execute("SELECT 1 FROM comments WHERE id=?", (comment_id,))
        return cur.fetchone() is not None

    def save_comment(self, c, sentiment, media_id: str = "") -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO comments
               (id, media_id, author, text, sentiment, sentiment_conf, created_at, processed_at, status)
               VALUES (?,?,?,?,?,?,?,?, 'processed')""",
            (c.id, media_id or c.media_id or "", c.username, c.text,
             sentiment.label, sentiment.confidence, _now(), _now()),
        )
        self.conn.commit()

    # -------------------------------------------------------------- drafts
    def save_draft(self, draft, decision, media_id: str = "") -> int:
        cur = self.conn.execute(
            """INSERT OR REPLACE INTO drafts
               (comment_id, media_id, author, comment_text, sentiment, sentiment_conf,
                reply_text, action, confidence, motivo, engine, decision, decision_reason,
                state, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (draft.comment_id, media_id, draft.author, draft.comment_text,
             draft.sentiment, draft.sentiment_confidence, draft.text, draft.action,
             draft.confidence, draft.motivo, draft.engine, decision.kind,
             decision.reason, "pending", _now()),
        )
        self.conn.commit()
        return int(cur.lastrowid or 0)

    def pending(self, limit: int = 50) -> list[sqlite3.Row]:
        cur = self.conn.execute(
            "SELECT * FROM drafts WHERE state='pending' ORDER BY confidence ASC, id ASC LIMIT ?",
            (limit,),
        )
        return cur.fetchall()

    def get_draft(self, draft_id: int) -> sqlite3.Row | None:
        cur = self.conn.execute("SELECT * FROM drafts WHERE id=?", (draft_id,))
        return cur.fetchone()

    def set_state(self, draft_id: int, state: str, **extra) -> None:
        fields = {"state": state, "decided_at": _now()}
        fields.update(extra)
        sets = ", ".join(f"{k}=?" for k in fields)
        self.conn.execute(
            f"UPDATE drafts SET {sets} WHERE id=?", (*fields.values(), draft_id)
        )
        self.conn.commit()

    def mark_published(self, draft_id: int, published_id: str) -> None:
        self.set_state(draft_id, "published",
                       published_at=_now(), published_id=published_id, error=None)

    def mark_failed(self, draft_id: int, error: str) -> None:
        self.set_state(draft_id, "failed", error=str(error)[:500])

    def stats(self) -> dict:
        out = {}
        for row in self.conn.execute("SELECT state, COUNT(*) n FROM drafts GROUP BY state"):
            out[row["state"]] = row["n"]
        out["comments"] = self.conn.execute(
            "SELECT COUNT(*) n FROM comments").fetchone()["n"]
        return out

    # ------------------------------------------------------------ settings
    def get_setting(self, key: str, default: str = "") -> str:
        row = self.conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        self.conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)",
                          (key, str(value)))
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
