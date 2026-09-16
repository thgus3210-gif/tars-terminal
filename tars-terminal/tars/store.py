"""SQLite persistence: users, watchlist, notes. Per-account isolation.

Kept intentionally tiny (stdlib sqlite3). All watchlist/note rows are scoped
by username, so accounts never see each other's data — the same isolation
promise the reference site makes ("계정별로 관리됩니다").
"""

from __future__ import annotations
import os
import sqlite3
import threading
from datetime import datetime, timezone

_DB_PATH = os.getenv("TARS_DB", os.path.join(os.path.dirname(__file__), "tars.db"))
_local = threading.local()


def _conn() -> sqlite3.Connection:
    c = getattr(_local, "conn", None)
    if c is None:
        c = sqlite3.connect(_DB_PATH)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        _local.conn = c
    return c


def init_db():
    c = _conn()
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            username   TEXT PRIMARY KEY,
            pw_hash    TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS watchlist (
            username TEXT NOT NULL,
            ticker   TEXT NOT NULL,
            added_at TEXT NOT NULL,
            PRIMARY KEY (username, ticker)
        );
        CREATE TABLE IF NOT EXISTS notes (
            username   TEXT NOT NULL,
            ticker     TEXT NOT NULL,
            body       TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (username, ticker)
        );
        """
    )
    c.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---- users ----
def create_user(username: str, pw_hash: str) -> bool:
    try:
        _conn().execute(
            "INSERT INTO users(username, pw_hash, created_at) VALUES(?,?,?)",
            (username, pw_hash, _now()),
        )
        _conn().commit()
        return True
    except sqlite3.IntegrityError:
        return False


def get_user(username: str):
    row = _conn().execute(
        "SELECT username, pw_hash FROM users WHERE username=?", (username,)
    ).fetchone()
    return dict(row) if row else None


# ---- watchlist ----
def list_watchlist(username: str) -> list[str]:
    rows = _conn().execute(
        "SELECT ticker FROM watchlist WHERE username=? ORDER BY added_at", (username,)
    ).fetchall()
    return [r["ticker"] for r in rows]


def add_watch(username: str, ticker: str):
    _conn().execute(
        "INSERT OR IGNORE INTO watchlist(username, ticker, added_at) VALUES(?,?,?)",
        (username, ticker.upper(), _now()),
    )
    _conn().commit()


def remove_watch(username: str, ticker: str):
    _conn().execute(
        "DELETE FROM watchlist WHERE username=? AND ticker=?",
        (username, ticker.upper()),
    )
    _conn().commit()


# ---- notes ----
def get_note(username: str, ticker: str) -> dict | None:
    row = _conn().execute(
        "SELECT ticker, body, updated_at FROM notes WHERE username=? AND ticker=?",
        (username, ticker.upper()),
    ).fetchone()
    return dict(row) if row else None


def upsert_note(username: str, ticker: str, body: str):
    _conn().execute(
        """INSERT INTO notes(username, ticker, body, updated_at) VALUES(?,?,?,?)
           ON CONFLICT(username, ticker) DO UPDATE SET body=excluded.body,
           updated_at=excluded.updated_at""",
        (username, ticker.upper(), body, _now()),
    )
    _conn().commit()


def list_notes(username: str) -> list[dict]:
    rows = _conn().execute(
        "SELECT ticker, body, updated_at FROM notes WHERE username=? ORDER BY updated_at DESC",
        (username,),
    ).fetchall()
    return [dict(r) for r in rows]
