import asyncio
import json
from scraper.decryptors import register_all


class TaskManager:
    def __init__(self, max_global_concurrency: int = 20):
        self._semaphore = asyncio.Semaphore(max_global_concurrency)
        self._running_tasks: dict[int, asyncio.Task] = {}
        self._pause_events: dict[int, asyncio.Event] = {}
        self._progress_callbacks: list = []

    def register_progress_callback(self, cb):
        self._progress_callbacks.append(cb)

    def unregister_progress_callback(self, cb):
        if cb in self._progress_callbacks:
            self._progress_callbacks.remove(cb)

    async def broadcast_progress(self, task_id: int, done: int, total: int,
                                 current_file: str = "", speed: float = 0):
        for cb in self._progress_callbacks:
            try:
                await cb(task_id, done, total, current_file, speed)
            except Exception:
                pass

    async def start_task(self, task_id: int, task_config: dict):
        from db import queries as q
        from scraper.engine import ScraperEngine

        task = await q.get_task(task_id)
        if not task or task["status"] != "pending":
            return

        await q.update_task(task_id, status="running")
        config = json.loads(task["config"]) if task["config"] else {}
        config.update(task_config)

        register_all()

        self._pause_events[task_id] = asyncio.Event()
        self._pause_events[task_id].set()

        engine = ScraperEngine(
            task_id=task_id,
            semaphore=self._semaphore,
            pause_event=self._pause_events[task_id],
            progress_cb=self._broadcast_task_progress,
        )
        coro = engine.run()
        t = asyncio.create_task(coro)
        self._running_tasks[task_id] = t

    async def _broadcast_task_progress(self, task_id, done, total, current_file="", speed=0):
        await self.broadcast_progress(task_id, done, total, current_file, speed)
        from db import queries as q
        await q.update_task(task_id, done_files=done, total_files=total)

    async def pause_task(self, task_id: int):
        if task_id in self._pause_events:
            self._pause_events[task_id].clear()
        from db import queries as q
        await q.update_task(task_id, status="paused")

    async def resume_task(self, task_id: int):
        from db import queries as q
        task = await q.get_task(task_id)
        if not task or task["status"] != "paused":
            return
        if task_id not in self._running_tasks:
            await q.update_task(task_id, status="pending")
            await self.start_task(task_id, json.loads(task["config"]))
        else:
            self._pause_events[task_id].set()
            await q.update_task(task_id, status="running")

    async def retry_task(self, task_id: int):
        from db import queries as q
        failed = await q.get_failed_downloads(task_id)
        for dl in failed:
            await q.update_download(dl["id"], status="pending", retry_count=0, error_msg=None)
        await q.update_task(task_id, status="pending")
        task = await q.get_task(task_id)
        if task:
            config = json.loads(task["config"]) if task["config"] else {}
            await self.start_task(task_id, config)

    async def shutdown(self):
        for task_id in list(self._running_tasks.keys()):
            await self.pause_task(task_id)
        for t in self._running_tasks.values():
            t.cancel()
        for t in self._running_tasks.values():
            try:
                await t
            except asyncio.CancelledError:
                pass
        self._running_tasks.clear()
        self._pause_events.clear()
