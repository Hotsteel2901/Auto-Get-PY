"""Task lifecycle: start, pause, resume, cancel, retry.

One :class:`TaskManager` instance owns every running scrape.  Its job is to
keep the database honest: a task that crashes must end up ``failed`` rather
than sitting in ``running`` forever, and a task that is cancelled must stop
without leaving orphan work behind.
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


class TaskManager:
    def __init__(self, max_global_concurrency: int = 20):
        self._semaphore = asyncio.Semaphore(max_global_concurrency)
        self._running_tasks: dict[int, asyncio.Task] = {}
        self._pause_events: dict[int, asyncio.Event] = {}
        self._engines: dict[int, object] = {}
        self._listeners: list = []

    # ── Progress fan-out ────────────────────────────────────────────────────

    def register_progress_callback(self, cb) -> None:
        """Subscribe to progress payloads (dicts)."""
        if cb not in self._listeners:
            self._listeners.append(cb)

    def unregister_progress_callback(self, cb) -> None:
        try:
            self._listeners.remove(cb)
        except ValueError:
            pass

    @property
    def listener_count(self) -> int:
        return len(self._listeners)

    async def broadcast(self, payload: dict) -> None:
        """Send a payload to every subscriber, dropping dead ones."""
        if not self._listeners:
            return
        results = await asyncio.gather(
            *(self._safe_call(cb, payload) for cb in self._listeners),
            return_exceptions=True)
        dead = [cb for cb, ok in zip(list(self._listeners), results) if ok is False]
        for cb in dead:
            self.unregister_progress_callback(cb)

    @staticmethod
    async def _safe_call(cb, payload):
        try:
            result = await cb(payload)
        except Exception:  # noqa: BLE001 - a broken socket is not a fatal error
            return False
        return False if result is False else True

    async def broadcast_progress(self, task_id: int, done: int, total: int,
                                 current_file: str = "", speed: float = 0.0) -> None:
        await self.broadcast({
            "type": "progress",
            "task_id": task_id,
            "done": done,
            "total": total,
            "current_file": current_file,
            "speed": round(speed, 2),
            "percent": round(done / total * 100, 1) if total else 0.0,
        })

    async def broadcast_file_progress(self, task_id: int, dl_id: int,
                                      downloaded: int, total: int | None) -> None:
        await self.broadcast({
            "type": "file_progress",
            "task_id": task_id,
            "download_id": dl_id,
            "downloaded": downloaded,
            "total": total,
            "percent": round(downloaded / total * 100, 1) if total else None,
        })

    async def broadcast_task_status(self, task_id: int, status: str,
                                    error: str | None = None) -> None:
        await self.broadcast({
            "type": "task_status",
            "task_id": task_id,
            "status": status,
            "error": error,
        })

    # ── Introspection ───────────────────────────────────────────────────────

    def is_running(self, task_id: int) -> bool:
        task = self._running_tasks.get(task_id)
        return bool(task and not task.done())

    @property
    def running_task_ids(self) -> list[int]:
        return [tid for tid, t in self._running_tasks.items() if not t.done()]

    # ── Lifecycle ───────────────────────────────────────────────────────────

    async def start_task(self, task_id: int, force: bool = False) -> bool:
        """Launch the engine for a task. Returns True when it was started."""
        from db import queries as q
        from scraper.decryptors import register_all
        from scraper.engine import ScraperEngine

        if self.is_running(task_id):
            logger.debug("Task %s is already running", task_id)
            return False

        task = await q.get_task(task_id)
        if not task:
            logger.warning("Cannot start task %s: not found", task_id)
            return False
        if not force and task["status"] not in ("pending", "paused", "failed", "cancelled"):
            return False

        register_all()
        await q.update_task(task_id, status="running", error_msg=None)
        await self.broadcast_task_status(task_id, "running")

        pause_event = asyncio.Event()
        pause_event.set()
        self._pause_events[task_id] = pause_event

        engine = ScraperEngine(
            task_id=task_id,
            semaphore=self._semaphore,
            pause_event=pause_event,
            progress_cb=self.broadcast_progress,
            file_progress_cb=self.broadcast_file_progress,
        )
        self._engines[task_id] = engine

        runner = asyncio.create_task(self._run_engine(task_id, engine))
        self._running_tasks[task_id] = runner
        return True

    async def _run_engine(self, task_id: int, engine) -> None:
        """Run the engine, mapping any outcome onto a terminal task status."""
        from db import queries as q

        status, error = "completed", None
        try:
            await engine.run()
        except asyncio.CancelledError:
            status, error = "cancelled", "Task cancelled"
            raise
        except Exception as exc:  # noqa: BLE001 - never leave a task "running"
            logger.exception("Task %s crashed", task_id)
            status, error = "failed", f"{type(exc).__name__}: {exc}"
        finally:
            self._running_tasks.pop(task_id, None)
            self._pause_events.pop(task_id, None)
            self._engines.pop(task_id, None)

            fresh = await q.get_task(task_id)
            if fresh and fresh["status"] in ("running", "pending"):
                await q.update_task(task_id, status=status, error_msg=error)
                try:
                    await self.broadcast_task_status(task_id, status, error)
                except Exception:  # noqa: BLE001
                    pass

    async def pause_task(self, task_id: int) -> None:
        from db import queries as q

        event = self._pause_events.get(task_id)
        if event is not None:
            event.clear()
        await q.update_task(task_id, status="paused")
        await self.broadcast_task_status(task_id, "paused")

    async def resume_task(self, task_id: int) -> bool:
        from db import queries as q

        task = await q.get_task(task_id)
        if not task:
            return False

        if task_id in self._pause_events and self.is_running(task_id):
            self._pause_events[task_id].set()
            await q.update_task(task_id, status="running")
            await self.broadcast_task_status(task_id, "running")
            return True

        # Nothing is running: restart from the persisted state.
        await q.requeue_downloads(task_id, ("failed",))
        await q.update_task(task_id, status="pending")
        return await self.start_task(task_id, force=True)

    async def cancel_task(self, task_id: int) -> None:
        from db import queries as q

        engine = self._engines.get(task_id)
        if engine is not None:
            engine.cancel()

        runner = self._running_tasks.get(task_id)
        if runner and not runner.done():
            runner.cancel()
            try:
                await runner
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

        self._pause_events.pop(task_id, None)
        self._engines.pop(task_id, None)
        self._running_tasks.pop(task_id, None)

        await q.requeue_downloads(task_id, ("downloading", "pending"))
        await q.update_task(task_id, status="cancelled")
        await self.broadcast_task_status(task_id, "cancelled")

    async def retry_task(self, task_id: int) -> bool:
        from db import queries as q

        if self.is_running(task_id):
            logger.debug("Task %s still running; not retrying", task_id)
            return False

        await q.requeue_downloads(task_id, ("failed", "downloading"))
        await q.update_task(task_id, status="pending", error_msg=None)
        return await self.start_task(task_id, force=True)

    async def shutdown(self) -> None:
        """Pause and cancel everything. Called on application shutdown."""
        snapshot = list(self._running_tasks.items())
        for task_id, _ in snapshot:
            event = self._pause_events.get(task_id)
            if event is not None:
                event.clear()
            engine = self._engines.get(task_id)
            if engine is not None:
                engine.cancel()

        for _, runner in snapshot:
            runner.cancel()
        for _, runner in snapshot:
            try:
                await runner
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

        self._running_tasks.clear()
        self._pause_events.clear()
        self._engines.clear()
        self._listeners.clear()
