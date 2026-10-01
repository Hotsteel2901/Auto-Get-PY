"""Database concurrency.

The download workers write progress from several tasks at once, and CI hit
``sqlite3.OperationalError: database is locked`` on Windows as a result. These
tests hammer the write path hard enough to reproduce that class of failure, so
a regression in the connection settings is caught locally rather than in CI.
"""

from __future__ import annotations

import asyncio

import pytest

from db import queries as q
from db.schema import get_db

pytestmark = pytest.mark.asyncio

WRITERS = 24
ROUNDS = 15


async def test_connection_settings_are_lock_safe():
    """busy_timeout must be active before anything that takes a lock."""
    db = await get_db()
    try:
        timeout = (await (await db.execute("PRAGMA busy_timeout")).fetchone())[0]
        assert timeout >= 5000, f"busy_timeout is only {timeout}ms"

        journal = (await (await db.execute("PRAGMA journal_mode")).fetchone())[0]
        assert journal.lower() == "wal", f"journal_mode is {journal}"

        # Autocommit: the default deferred mode can fail with
        # SQLITE_BUSY_SNAPSHOT when a reader upgrades to a writer.
        assert db.isolation_level is None, (
            "connections must run in autocommit; deferred write transactions "
            "cannot recover from a WAL snapshot conflict")
    finally:
        await db.close()


async def test_concurrent_progress_writes_never_lock():
    """The exact pattern the engine uses: many workers updating progress."""
    task = await q.create_task("concurrency", "http://example.test/", {})
    task_id = task["id"]

    items = [(f"http://example.test/f{i}.jpg", f"f{i}.jpg", None) for i in range(WRITERS)]
    await q.create_downloads_bulk(task_id, items)
    downloads = await q.list_downloads(task_id)
    assert len(downloads) == WRITERS

    errors: list[str] = []

    async def hammer(download: dict) -> None:
        try:
            for round_index in range(ROUNDS):
                await q.update_download(download["id"], status="downloading")
                await q.update_download_progress(
                    download["id"], (round_index + 1) * 1024, 1024 * ROUNDS)
                if round_index % 4 == 0:
                    await q.update_download(download["id"], status="pending")
        except Exception as exc:  # noqa: BLE001 - the failure IS the assertion
            errors.append(f"{type(exc).__name__}: {exc}")

    await asyncio.gather(*(hammer(d) for d in downloads))

    assert not errors, f"{len(errors)} concurrent write(s) failed: {errors[:5]}"

    final = await q.get_download_stats(task_id)
    assert final["total"] == WRITERS
    assert final["pending"] + final["downloading"] == WRITERS


async def test_concurrent_writers_across_many_tasks():
    """Several tasks finishing at once must not deadlock each other."""
    tasks = [await q.create_task(f"task-{i}", f"http://example.test/{i}", {})
             for i in range(8)]

    errors: list[str] = []

    async def writer(task: dict) -> None:
        try:
            for i in range(10):
                await q.create_download(task["id"], f"http://example.test/{i}.jpg", f"{i}.jpg")
                await q.update_task(task["id"], done_files=i, total_files=10)
            await q.update_task(task["id"], status="completed", error_msg=None)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{type(exc).__name__}: {exc}")

    await asyncio.gather(*(writer(t) for t in tasks))

    assert not errors, f"concurrent tasks failed: {errors[:5]}"
    for task in tasks:
        fresh = await q.get_task(task["id"])
        assert fresh["status"] == "completed"
        assert len(await q.list_downloads(task["id"])) == 10


async def test_bulk_insert_is_atomic():
    """A failed batch must not leave half its rows behind."""
    task = await q.create_task("atomic", "http://example.test/", {})

    # A NULL task_id cannot satisfy the NOT NULL constraint, so the whole
    # batch must roll back rather than committing the rows before it.
    with pytest.raises(Exception):
        await q.create_downloads_bulk(task["id"], [
            ("http://example.test/ok.jpg", "ok.jpg", None),
        ] + [(None, "bad.jpg", None)])

    assert await q.list_downloads(task["id"]) == []


async def test_repeated_open_close_under_load():
    """Connections are opened per call; that must stay cheap and safe."""
    task = await q.create_task("churn", "http://example.test/", {})
    download = await q.create_download(task["id"], "http://example.test/a.jpg", "a.jpg")

    async def churn() -> None:
        for _ in range(30):
            await q.get_task(task["id"])
            await q.count_downloads_by_status(task["id"], "pending")

    await asyncio.gather(*(churn() for _ in range(10)))
    assert (await q.get_download(download["id"]))["status"] == "pending"
