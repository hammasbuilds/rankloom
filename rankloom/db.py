"""SQLite storage. One connection per request thread; WAL so readers never block the writer."""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id               INTEGER PRIMARY KEY,
    email            TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name             TEXT NOT NULL,
    pw_hash          TEXT NOT NULL,
    created_at       INTEGER NOT NULL,
    totp_secret      BLOB,            -- sealed with the app key
    totp_pending     BLOB,            -- sealed; set during setup, cleared on enable
    totp_last_step   INTEGER NOT NULL DEFAULT 0,
    recovery_codes   TEXT NOT NULL DEFAULT '[]',  -- JSON list of sha256 hex
    github_login     TEXT,
    github_token     BLOB             -- sealed
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash   TEXT PRIMARY KEY,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at   INTEGER NOT NULL,
    expires_at   INTEGER NOT NULL,
    last_seen    INTEGER NOT NULL,
    mfa_pending  INTEGER NOT NULL DEFAULT 0,
    user_agent   TEXT NOT NULL DEFAULT '',
    ip           TEXT NOT NULL DEFAULT '',
    oauth_state  TEXT
);
CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);
CREATE TABLE IF NOT EXISTS reset_tokens (
    token_hash  TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at  INTEGER NOT NULL,
    used        INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS attempts (
    bucket  TEXT NOT NULL,
    at      INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS attempts_bucket ON attempts(bucket, at);
CREATE TABLE IF NOT EXISTS events (
    id       INTEGER PRIMARY KEY,
    user_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tool     TEXT NOT NULL,
    subtool  TEXT NOT NULL DEFAULT '',
    kind     TEXT NOT NULL,          -- open | run
    at       INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS events_user_tool ON events(user_id, tool, at);
CREATE TABLE IF NOT EXISTS runs (
    id           INTEGER PRIMARY KEY,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tool         TEXT NOT NULL,
    subtool      TEXT NOT NULL DEFAULT '',
    created_at   INTEGER NOT NULL,
    status       TEXT NOT NULL,      -- ok | error
    duration_ms  INTEGER NOT NULL,
    summary      TEXT NOT NULL DEFAULT '',
    score        INTEGER,
    input_json   TEXT NOT NULL,
    output_json  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS runs_user_tool ON runs(user_id, tool, created_at);
CREATE TABLE IF NOT EXISTS imports (
    id              INTEGER PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    repo            TEXT NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    default_branch  TEXT NOT NULL DEFAULT '',
    languages_json  TEXT NOT NULL DEFAULT '{}',
    file_count      INTEGER NOT NULL DEFAULT 0,
    private         INTEGER NOT NULL DEFAULT 0,
    imported_at     INTEGER NOT NULL,
    UNIQUE(user_id, repo)
);
CREATE TABLE IF NOT EXISTS leads (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    category    TEXT NOT NULL DEFAULT '',
    website     TEXT NOT NULL DEFAULT '',
    phone       TEXT NOT NULL DEFAULT '',
    email       TEXT NOT NULL DEFAULT '',
    address     TEXT NOT NULL DEFAULT '',
    city        TEXT NOT NULL DEFAULT '',
    source      TEXT NOT NULL DEFAULT '',
    score       INTEGER,                 -- higher = more to gain from our help
    problems    TEXT NOT NULL DEFAULT '[]',
    status      TEXT NOT NULL DEFAULT 'new',
    notes       TEXT NOT NULL DEFAULT '',
    created_at  INTEGER NOT NULL,
    updated_at  INTEGER NOT NULL,
    UNIQUE(user_id, name, website)
);
CREATE TABLE IF NOT EXISTS gsc_datasets (
    id           INTEGER PRIMARY KEY,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    site         TEXT NOT NULL,
    label        TEXT NOT NULL,
    uploaded_at  INTEGER NOT NULL,
    data_json    TEXT NOT NULL           -- {"queries": [...], "pages": [...], "compare": bool}
);
CREATE TABLE IF NOT EXISTS clients (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    website     TEXT NOT NULL DEFAULT '',
    contact     TEXT NOT NULL DEFAULT '',
    brand       TEXT NOT NULL DEFAULT '',
    city        TEXT NOT NULL DEFAULT '',
    niche       TEXT NOT NULL DEFAULT '',
    notes       TEXT NOT NULL DEFAULT '',
    gsc_dataset INTEGER,
    created_at  INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS outbox (
    id          INTEGER PRIMARY KEY,
    to_email    TEXT NOT NULL,
    subject     TEXT NOT NULL,
    body        TEXT NOT NULL,
    created_at  INTEGER NOT NULL
);
"""


def now() -> int:
    return int(time.time())


class Database:
    def __init__(self, path: Path | str):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._shared: sqlite3.Connection | None = None
        if self.path == ":memory:":
            # An in-memory database exists per connection, so tests share one.
            self._shared = self._open()
        with self.connect() as c:
            self._migrate(c)
            c.executescript(SCHEMA)

    @staticmethod
    def _migrate(c: sqlite3.Connection) -> None:
        """Columns added after a database was first created."""
        for table, column in (("runs", "subtool"), ("events", "subtool")):
            cols = {r[1] for r in c.execute(f"PRAGMA table_info({table})")}
            if cols and column not in cols:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")

    def _open(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        if self.path != ":memory:":
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    def connect(self) -> sqlite3.Connection:
        if self._shared is not None:
            return self._shared
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = self._local.conn = self._open()
        return conn

    def one(self, sql: str, *args) -> sqlite3.Row | None:
        return self.connect().execute(sql, args).fetchone()

    def all(self, sql: str, *args) -> list[sqlite3.Row]:
        return self.connect().execute(sql, args).fetchall()

    def run(self, sql: str, *args) -> sqlite3.Cursor:
        return self.connect().execute(sql, args)
