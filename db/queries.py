"""Async data-access helpers.

Every function opens a short-lived connection. Connections run in autocommit
(see :func:`db.schema.get_db`) so a single statement is its own transaction —
which is what almost every function here is. Multi-statement writes open a
transaction explicitly. The ``commit()`` calls that remain are no-ops in
autocommit and are kept so the helpers keep working if that ever changes.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3

from db.schema import get_db

logger = logging.getLogger(__name__)

_VALID_TASK_COLUMNS = {
    "name", "url", "status", "config", "total_files", "done_files",
    "error_msg", "extra_info",
}
_VALID_DOWNLOAD_COLUMNS = {
    "task_id", "url", "filename", "filepath", "file_size", "downloaded",
    "status", "retry_count", "error_msg", "mime_type", "referer", "updated_at",
}

# Task states that mean "no further progress will happen on its own".
TERMINAL_TASK_STATUSES = ("completed", "failed", "cancelled")

# SQLite reports contention through OperationalError. With ``busy_timeout``
# set (see db.schema.get_db) most of these are absorbed inside SQLite itself;
# the ones that still surface are WAL snapshot conflicts, which are retried
# here because the correct response is simply to try again.
_LOCK_HINTS = (
    "database is locked",
    "database table is locked",
    "database schema is locked",
    "database is busy",
)


def _is_lock_error(exc: BaseException) -> bool:
    return (isinstance(exc, sqlite3.OperationalError)
            and any(hint in str(exc).lower() for hint in _LOCK_HINTS))


async def retry_on_lock(operation, *args, attempts: int = 5, **kwargs):
    """Run ``operation``, retrying while SQLite reports contention."""
    delay = 0.05
    for attempt in range(1, attempts + 1):
        try:
            return await operation(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - re-raised when not a lock
            if attempt >= attempts or not _is_lock_error(exc):
                raise
            logger.debug("SQLite busy, retrying %s (%d/%d)",
                         getattr(operation, "__name__", "query"), attempt, attempts)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 1.0)
    return None  # unreachable


def _json_or(raw, fallback):
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return fallback


def _decorate_task(row: dict) -> dict:
    """Attach parsed ``config``/``extra_info`` so the API never re-parses."""
    out = dict(row)
    out["config_parsed"] = _json_or(out.get("config"), {})
    out["extra_info"] = _json_or(out.get("extra_info"), {})
    total = out.get("total_files") or 0
    done = out.get("done_files") or 0
    out["progress"] = round(done / total * 100, 1) if total else 0.0
    return out


def _decorate_download(row: dict) -> dict:
    out = dict(row)
    size = out.get("file_size") or 0
    got = out.get("downloaded") or 0
    if out.get("status") == "completed":
        out["progress"] = 100.0
    elif size > 0:
        out["progress"] = round(min(got / size, 1.0) * 100, 1)
    else:
        out["progress"] = 0.0
    return out


# ── Tasks ───────────────────────────────────────────────────────────────────


async def create_task(name: str, url: str, config: dict | None = None) -> dict:
    db = await get_db()
    try:
        cur = await db.execute(
            "INSERT INTO tasks (name, url, config) VALUES (?, ?, ?)",
            (name, url, json.dumps(config or {})),
        )
        await db.commit()
        row = await db.execute("SELECT * FROM tasks WHERE id = ?", (cur.lastrowid,))
        return _decorate_task(dict(await row.fetchone()))
    finally:
        await db.close()


async def list_tasks(status: str | None = None, offset: int = 0,
                     limit: int = 50) -> list[dict]:
    db = await get_db()
    try:
        if status:
            cur = await db.execute(
                "SELECT * FROM tasks WHERE status = ? "
                "ORDER BY id DESC LIMIT ? OFFSET ?",
                (status, limit, offset),
            )
        else:
            cur = await db.execute(
                "SELECT * FROM tasks ORDER BY id DESC LIMIT ? OFFSET ?",
                (limit, offset),
            )
        return [_decorate_task(dict(r)) for r in await cur.fetchall()]
    finally:
        await db.close()


async def count_tasks_by_status() -> dict:
    db = await get_db()
    try:
        cur = await db.execute("SELECT status, COUNT(*) AS cnt FROM tasks GROUP BY status")
        counts = {r["status"]: r["cnt"] for r in await cur.fetchall()}
        cur = await db.execute("SELECT COUNT(*) AS cnt FROM tasks")
        counts["all"] = (await cur.fetchone())["cnt"]
        return counts
    finally:
        await db.close()


async def get_task(task_id: int) -> dict | None:
    db = await get_db()
    try:
        cur = await db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        row = await cur.fetchone()
        return _decorate_task(dict(row)) if row else None
    finally:
        await db.close()


async def update_task(task_id: int, **kwargs) -> dict | None:
    if not kwargs:
        return await get_task(task_id)
    invalid = set(kwargs) - _VALID_TASK_COLUMNS
    if invalid:
        raise ValueError(f"Invalid column(s) for tasks: {invalid}")
    return await retry_on_lock(_update_task_impl, task_id, kwargs)


async def _update_task_impl(task_id: int, kwargs: dict) -> dict | None:
    db = await get_db()
    try:
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        vals = [json.dumps(v) if k == "extra_info" and isinstance(v, (dict, list)) else v
                for k, v in kwargs.items()]
        vals.append(task_id)
        await db.execute(
            f"UPDATE tasks SET {sets}, updated_at = datetime('now') WHERE id = ?", vals)
        cur = await db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        row = await cur.fetchone()
        return _decorate_task(dict(row)) if row else None
    finally:
        await db.close()


async def delete_task(task_id: int) -> bool:
    db = await get_db()
    try:
        cur = await db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        await db.commit()
        return cur.rowcount > 0
    finally:
        await db.close()


async def reset_stuck_tasks() -> int:
    """Mark tasks left 'running'/'paused' by a crash as failed.

    Called once on startup: no engine can be alive before the app serves.
    """
    db = await get_db()
    try:
        cur = await db.execute(
            "UPDATE tasks SET status = 'failed', "
            "error_msg = COALESCE(error_msg, 'Interrupted by server restart'), "
            "updated_at = datetime('now') "
            "WHERE status IN ('running', 'paused')"
        )
        await db.commit()
        return cur.rowcount
    finally:
        await db.close()


# ── Downloads ───────────────────────────────────────────────────────────────


async def create_download(task_id: int, url: str, filename: str | None = None,
                          referer: str | None = None) -> dict:
    db = await get_db()
    try:
        cur = await db.execute(
            "INSERT INTO downloads (task_id, url, filename, referer) VALUES (?, ?, ?, ?)",
            (task_id, url, filename, referer),
        )
        await db.commit()
        row = await db.execute("SELECT * FROM downloads WHERE id = ?", (cur.lastrowid,))
        return _decorate_download(dict(await row.fetchone()))
    finally:
        await db.close()


async def create_downloads_bulk(task_id: int, items: list[tuple[str, str, str | None]]) -> int:
    """Insert many ``(url, filename, referer)`` rows in one transaction."""
    if not items:
        return 0
    return await retry_on_lock(_create_downloads_bulk_impl, task_id, items)


async def _create_downloads_bulk_impl(task_id: int,
                                      items: list[tuple[str, str, str | None]]) -> int:
    db = await get_db()
    try:
        # Connections are in autocommit, so the batch needs an explicit
        # transaction: one commit for N rows instead of N commits.
        await db.execute("BEGIN IMMEDIATE")
        try:
            await db.executemany(
                "INSERT INTO downloads (task_id, url, filename, referer) VALUES (?, ?, ?, ?)",
                [(task_id, url, fname, ref) for url, fname, ref in items],
            )
        except BaseException:
            await db.execute("ROLLBACK")
            raise
        await db.execute("COMMIT")
        return len(items)
    finally:
        await db.close()


async def list_downloads(task_id: int, status: str | None = None,
                         limit: int | None = None) -> list[dict]:
    db = await get_db()
    try:
        sql = "SELECT * FROM downloads WHERE task_id = ?"
        params: list = [task_id]
        if status:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY id ASC"
        if limit:
            sql += " LIMIT ?"
            params.append(limit)
        cur = await db.execute(sql, params)
        return [_decorate_download(dict(r)) for r in await cur.fetchall()]
    finally:
        await db.close()


async def list_all_downloads(status: str | None = None, limit: int = 500,
                             offset: int = 0) -> list[dict]:
    """Cross-task download listing with the owning task name attached."""
    db = await get_db()
    try:
        sql = (
            "SELECT d.*, t.name AS task_name FROM downloads d "
            "LEFT JOIN tasks t ON t.id = d.task_id"
        )
        params: list = []
        if status:
            sql += " WHERE d.status = ?"
            params.append(status)
        sql += " ORDER BY d.id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        cur = await db.execute(sql, params)
        return [_decorate_download(dict(r)) for r in await cur.fetchall()]
    finally:
        await db.close()


async def get_download(dl_id: int) -> dict | None:
    db = await get_db()
    try:
        cur = await db.execute("SELECT * FROM downloads WHERE id = ?", (dl_id,))
        row = await cur.fetchone()
        return _decorate_download(dict(row)) if row else None
    finally:
        await db.close()


async def update_download(dl_id: int, **kwargs) -> dict | None:
    if not kwargs:
        return await get_download(dl_id)
    invalid = set(kwargs) - _VALID_DOWNLOAD_COLUMNS
    if invalid:
        raise ValueError(f"Invalid column(s) for downloads: {invalid}")
    return await retry_on_lock(_update_download_impl, dl_id, kwargs)


async def _update_download_impl(dl_id: int, kwargs: dict) -> dict | None:
    db = await get_db()
    try:
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        vals = list(kwargs.values()) + [dl_id]
        await db.execute(
            f"UPDATE downloads SET {sets}, updated_at = datetime('now') WHERE id = ?", vals)
        cur = await db.execute("SELECT * FROM downloads WHERE id = ?", (dl_id,))
        row = await cur.fetchone()
        return _decorate_download(dict(row)) if row else None
    finally:
        await db.close()


async def update_download_progress(dl_id: int, downloaded: int,
                                   file_size: int | None = None) -> None:
    """Hot path: only touch the byte counters."""
    await retry_on_lock(_update_download_progress_impl, dl_id, downloaded, file_size)


async def _update_download_progress_impl(dl_id: int, downloaded: int,
                                         file_size: int | None) -> None:
    db = await get_db()
    try:
        if file_size:
            await db.execute(
                "UPDATE downloads SET downloaded = ?, file_size = ? WHERE id = ?",
                (downloaded, file_size, dl_id),
            )
        else:
            await db.execute(
                "UPDATE downloads SET downloaded = ? WHERE id = ?", (downloaded, dl_id))
    finally:
        await db.close()


async def count_downloads_by_status(task_id: int, status: str) -> int:
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT COUNT(*) AS cnt FROM downloads WHERE task_id = ? AND status = ?",
            (task_id, status),
        )
        row = await cur.fetchone()
        return row["cnt"] if row else 0
    finally:
        await db.close()


async def get_download_stats(task_id: int) -> dict:
    """All status counts for a task in a single round trip."""
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT status, COUNT(*) AS cnt, COALESCE(SUM(file_size), 0) AS bytes "
            "FROM downloads WHERE task_id = ? GROUP BY status",
            (task_id,),
        )
        stats = {"pending": 0, "downloading": 0, "completed": 0, "failed": 0}
        total_bytes = 0
        for row in await cur.fetchall():
            stats[row["status"]] = row["cnt"]
            if row["status"] == "completed":
                total_bytes = row["bytes"]
        stats["total"] = sum(stats.values())
        stats["bytes"] = total_bytes
        return stats
    finally:
        await db.close()


async def get_failed_downloads(task_id: int) -> list[dict]:
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM downloads WHERE task_id = ? AND status = 'failed'", (task_id,))
        return [_decorate_download(dict(r)) for r in await cur.fetchall()]
    finally:
        await db.close()


async def get_existing_download_urls(task_id: int) -> set[str]:
    db = await get_db()
    try:
        cur = await db.execute("SELECT url FROM downloads WHERE task_id = ?", (task_id,))
        return {r["url"] for r in await cur.fetchall()}
    finally:
        await db.close()


async def requeue_downloads(task_id: int, statuses: tuple[str, ...] = ("failed",)) -> int:
    """Put downloads back to pending for a retry pass."""
    if not statuses:
        return 0
    placeholders = ", ".join("?" for _ in statuses)
    db = await get_db()
    try:
        cur = await db.execute(
            f"UPDATE downloads SET status = 'pending', retry_count = 0, error_msg = NULL, "
            f"updated_at = datetime('now') "
            f"WHERE task_id = ? AND status IN ({placeholders})",
            (task_id, *statuses),
        )
        await db.commit()
        return cur.rowcount
    finally:
        await db.close()


# ── Settings ────────────────────────────────────────────────────────────────


async def get_settings() -> dict:
    db = await get_db()
    try:
        cur = await db.execute("SELECT key, value FROM settings")
        return {r["key"]: r["value"] for r in await cur.fetchall()}
    finally:
        await db.close()


async def update_setting(key: str, value: str) -> None:
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = ?",
            (key, value, value),
        )
        await db.commit()
    finally:
        await db.close()


async def update_settings(values: dict) -> None:
    if not values:
        return
    db = await get_db()
    try:
        await db.executemany(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = ?",
            [(k, v, v) for k, v in values.items()],
        )
        await db.commit()
    finally:
        await db.close()
