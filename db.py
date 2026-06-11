"""SQLite storage for reading sessions."""

import os
import sqlite3
from typing import Optional

import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_date TEXT NOT NULL,      -- calendar date, YYYY-MM-DD
    title TEXT NOT NULL,
    minutes INTEGER NOT NULL CHECK (minutes > 0),
    reader TEXT NOT NULL,
    sender TEXT NOT NULL,            -- sender phone number, E.164
    raw_message TEXT NOT NULL,       -- original SMS body, for auditing
    received_at TEXT NOT NULL        -- ISO 8601 timestamp in the app timezone
);
"""


def get_conn(db_path: Optional[str] = None) -> sqlite3.Connection:
    path = db_path or config.DB_PATH
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Optional[str] = None) -> None:
    with get_conn(db_path) as conn:
        conn.executescript(_SCHEMA)


def insert_session(
    session_date: str,
    title: str,
    minutes: int,
    reader: str,
    sender: str,
    raw_message: str,
    received_at: str,
    db_path: Optional[str] = None,
) -> int:
    with get_conn(db_path) as conn:
        cur = conn.execute(
            """INSERT INTO sessions
               (session_date, title, minutes, reader, sender, raw_message, received_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (session_date, title, minutes, reader, sender, raw_message, received_at),
        )
        return cur.lastrowid


def all_sessions(db_path: Optional[str] = None) -> list:
    """All sessions, most recent first."""
    with get_conn(db_path) as conn:
        return conn.execute(
            "SELECT * FROM sessions ORDER BY received_at DESC, id DESC"
        ).fetchall()


def total_minutes(db_path: Optional[str] = None) -> int:
    with get_conn(db_path) as conn:
        row = conn.execute("SELECT COALESCE(SUM(minutes), 0) AS t FROM sessions").fetchone()
        return row["t"]


def session_count(db_path: Optional[str] = None) -> int:
    with get_conn(db_path) as conn:
        return conn.execute("SELECT COUNT(*) AS c FROM sessions").fetchone()["c"]
