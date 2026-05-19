import aiosqlite
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "scraper.db"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    url         TEXT NOT NULL,
    status      TEXT DEFAULT 'pending',
    config      TEXT DEFAULT '{}',
    total_files INTEGER DEFAULT 0,
    done_files  INTEGER DEFAULT 0,
    error_msg   TEXT,
    created_at  TEXT DEFAULT (datetime('now')),
    updated_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS downloads (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    url         TEXT NOT NULL,
    filename    TEXT,
    file_size   INTEGER DEFAULT 0,
    downloaded  INTEGER DEFAULT 0,
    status      TEXT DEFAULT 'pending',
    retry_count INTEGER DEFAULT 0,
    error_msg   TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

INSERT OR IGNORE INTO settings (key, value) VALUES
    ('default_concurrency', '5'),
    ('default_output_dir', './downloads'),
    ('default_decryptors', '["base64","hex"]');
"""


async def get_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(str(DB_PATH))
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    return db


async def init_db():
    db = await get_db()
    try:
        await db.executescript(SCHEMA_SQL)
        await db.commit()
    finally:
        await db.close()
