"""Shared pytest fixtures.

The database path is redirected to a temporary file for the whole session so
tests never touch the real ``scraper.db``, and every test gets a clean schema.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import db.schema as schema  # noqa: E402
from db import queries as q  # noqa: E402
from scraper.decryptors import register_all  # noqa: E402
from scraper.engine import ScraperEngine  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def isolated_database(tmp_path_factory):
    """Point every query at a throwaway database for the entire session."""
    schema.DB_PATH = tmp_path_factory.mktemp("db") / "test.db"
    register_all()
    asyncio.run(schema.init_db())
    yield schema.DB_PATH


@pytest.fixture(autouse=True)
async def clean_database(isolated_database):
    """Truncate the tables between tests so ids and counts are predictable."""
    db = await schema.get_db()
    try:
        await db.executescript(
            "DELETE FROM downloads; DELETE FROM tasks;"
            "DELETE FROM sqlite_sequence WHERE name IN ('tasks','downloads');"
        )
        await db.commit()
    finally:
        await db.close()
    yield


@pytest.fixture
async def local_site():
    """A running fake website covering every discovery path."""
    from tests.local_site import LocalSite

    async with LocalSite() as site:
        yield site


@pytest.fixture
def site_resolver(local_site):
    """Map a test-site path onto the live origin."""
    from urllib.parse import urljoin

    def resolve(path: str) -> str:
        return urljoin(local_site.url, path)

    return resolve


def make_pause_event() -> asyncio.Event:
    event = asyncio.Event()
    event.set()
    return event


@pytest.fixture
def run_task(tmp_path):
    """Create a task and run the engine to completion.

    Returns ``(task, downloads, output_dir)`` so tests can assert on the
    database state and the files that landed on disk.
    """
    counter = {"n": 0}

    async def _run(url: str, config: dict | None = None, name: str = "test"):
        counter["n"] += 1
        output_dir = tmp_path / f"out{counter['n']}"
        output_dir.mkdir(parents=True, exist_ok=True)

        full_config = {
            "output_dir": str(output_dir),
            "concurrency": 5,
            "request_delay_sec": 0,
            "request_timeout_sec": 10,
            "max_retries": 2,
        }
        full_config.update(config or {})

        task = await q.create_task(name, url, full_config)
        engine = ScraperEngine(
            task_id=task["id"],
            semaphore=asyncio.Semaphore(20),
            pause_event=make_pause_event(),
        )
        await engine.run()

        fresh = await q.get_task(task["id"])
        downloads = await q.list_downloads(task["id"])
        return fresh, downloads, output_dir

    return _run


def files_on_disk(directory: Path) -> set[str]:
    return {p.name for p in directory.rglob("*") if p.is_file()}
