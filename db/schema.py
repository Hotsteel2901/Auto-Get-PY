"""SQLite schema definition, connection handling and lightweight migrations.

The database is created and upgraded in place: :func:`init_db` creates any
missing tables, then adds any columns that were introduced after the database
file was first written.  That keeps old installs working without a manual
reset.
"""

from __future__ import annotations

import logging
from pathlib import Path

import aiosqlite

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent / "scraper.db"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS tasks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL,
    url          TEXT NOT NULL,
    status       TEXT DEFAULT 'pending',
    config       TEXT DEFAULT '{}',
    total_files  INTEGER DEFAULT 0,
    done_files   INTEGER DEFAULT 0,
    error_msg    TEXT,
    extra_info   TEXT DEFAULT '{}',
    created_at   TEXT DEFAULT (datetime('now')),
    updated_at   TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS downloads (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    url         TEXT NOT NULL,
    filename    TEXT,
    filepath    TEXT,
    file_size   INTEGER DEFAULT 0,
    downloaded  INTEGER DEFAULT 0,
    status      TEXT DEFAULT 'pending',
    retry_count INTEGER DEFAULT 0,
    mime_type   TEXT,
    referer     TEXT,
    error_msg   TEXT,
    created_at  TEXT DEFAULT (datetime('now')),
    updated_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE INDEX IF NOT EXISTS idx_downloads_task_id ON downloads(task_id);
CREATE INDEX IF NOT EXISTS idx_downloads_status  ON downloads(task_id, status);
CREATE INDEX IF NOT EXISTS idx_tasks_status      ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_created     ON tasks(created_at DESC);

INSERT OR IGNORE INTO settings (key, value) VALUES
    ('default_concurrency', '5'),
    ('default_output_dir', './downloads'),
    ('default_decryptors', '["base64","hex"]');
"""

# Columns added after the first public release.  ``init_db`` adds any of these
# that are missing from an existing database file.
_MIGRATIONS: dict[str, dict[str, str]] = {
    "tasks": {
        "extra_info": "TEXT DEFAULT '{}'",
    },
    "downloads": {
        "filepath": "TEXT",
        "mime_type": "TEXT",
        "referer": "TEXT",
        "updated_at": "TEXT",
    },
}

DEFAULT_SETTINGS = {
    "default_concurrency": "5",
    "default_output_dir": "./downloads",
    "default_decryptors": '["base64","hex"]',
}

# How long SQLite waits for a competing writer before giving up. The download
# workers write progress from several tasks at once, so contention is normal.
DB_TIMEOUT_SEC = 30.0


async def get_db() -> aiosqlite.Connection:
    """Open a connection tuned for many short-lived concurrent writers.

    Three details matter here, and getting any of them wrong shows up as
    ``sqlite3.OperationalError: database is locked`` under load:

    * ``busy_timeout`` is set **first**. Setting the journal mode takes a lock,
      and while the timeout is still 0 that lock attempt fails instantly
      instead of waiting for the other writer.
    * ``isolation_level=None`` puts the connection in autocommit. The default
      defers a transaction until the first write, which in WAL mode acquires a
      read snapshot and then has to upgrade — an upgrade that returns
      ``SQLITE_BUSY_SNAPSHOT``, which ``busy_timeout`` does not retry. Every
      statement here is self-contained, so autocommit is both correct and
      cheaper. Multi-statement work opens a transaction explicitly.
    * ``timeout`` is the sqlite3 driver's own busy timeout, which applies even
      before the pragma is executed.
    """
    db = await aiosqlite.connect(
        str(DB_PATH), timeout=DB_TIMEOUT_SEC, isolation_level=None)
    db.row_factory = aiosqlite.Row
    await db.execute(f"PRAGMA busy_timeout={int(DB_TIMEOUT_SEC * 1000)}")
    await db.execute("PRAGMA foreign_keys=ON")
    return db


async def _existing_columns(db: aiosqlite.Connection, table: str) -> set[str]:
    rows = await db.execute(f"PRAGMA table_info({table})")
    return {r["name"] for r in await rows.fetchall()}


async def _apply_migrations(db: aiosqlite.Connection) -> list[str]:
    applied: list[str] = []
    for table, columns in _MIGRATIONS.items():
        existing = await _existing_columns(db, table)
        if not existing:
            continue
        for column, ddl in columns.items():
            if column not in existing:
                await db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
                applied.append(f"{table}.{column}")
    if applied:
        logger.info("Applied schema migrations: %s", ", ".join(applied))
    return applied


async def init_db() -> None:
    """Create the schema if needed and migrate an existing database in place.

    This is the only place the journal mode is set: WAL is a property of the
    database file, and switching it needs an exclusive lock, so it must not
    race with the worker connections. Nothing else is connected at startup.
    """
    db = await get_db()
    try:
        await db.execute("PRAGMA journal_mode=WAL")
        # WAL + NORMAL is the documented safe pairing: durable across process
        # crashes, and far fewer fsyncs than FULL under a write-heavy load.
        await db.execute("PRAGMA synchronous=NORMAL")
        await db.executescript(SCHEMA_SQL)
        await _apply_migrations(db)
    finally:
        await db.close()


async def reset_db() -> None:
    """Drop every table. Only used by tests."""
    db = await get_db()
    try:
        await db.executescript(
            "DROP TABLE IF EXISTS downloads;"
            "DROP TABLE IF EXISTS tasks;"
            "DROP TABLE IF EXISTS settings;"
        )
    finally:
        await db.close()
