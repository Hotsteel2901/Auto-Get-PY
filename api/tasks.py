"""Task CRUD and control routes."""

from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from db import queries as q

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


class TaskCreateBody(BaseModel):
    name: str = Field(default="Untitled task", max_length=200)
    url: str
    config: dict[str, Any] = Field(default_factory=dict)

    @field_validator("url")
    @classmethod
    def _validate_url(cls, value: str) -> str:
        value = (value or "").strip()
        if not value:
            raise ValueError("url must not be empty")
        if not value.startswith(("http://", "https://")):
            value = f"https://{value}"
        return value


class TaskUpdateBody(BaseModel):
    name: Optional[str] = None
    url: Optional[str] = None
    config: Optional[dict[str, Any]] = None


async def _task_or_404(task_id: int) -> dict:
    task = await q.get_task(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    return task


@router.get("")
async def list_tasks(status: str | None = None,
                     offset: int = Query(0, ge=0),
                     limit: int = Query(50, ge=1, le=500)):
    tasks = await q.list_tasks(status=status, offset=offset, limit=limit)
    return {"tasks": tasks, "count": len(tasks)}


@router.get("/stats")
async def task_stats():
    """Status counts for the dashboard cards, in one query."""
    return {"stats": await q.count_tasks_by_status()}


@router.post("")
async def create_task(body: TaskCreateBody):
    task = await q.create_task(body.name, body.url, body.config)
    return {"task": task}


@router.get("/{task_id}")
async def get_task(task_id: int):
    return {"task": await _task_or_404(task_id)}


@router.get("/{task_id}/summary")
async def task_summary(task_id: int):
    """Everything the UI needs for one task, in a single round trip."""
    task = await _task_or_404(task_id)
    return {
        "task": task,
        "stats": await q.get_download_stats(task_id),
    }


@router.put("/{task_id}")
async def update_task(task_id: int, body: TaskUpdateBody):
    await _task_or_404(task_id)
    kwargs = {k: v for k, v in body.model_dump().items() if v is not None}
    if "config" in kwargs:
        kwargs["config"] = json.dumps(kwargs["config"])
    task = await q.update_task(task_id, **kwargs)
    return {"task": task}


@router.delete("/{task_id}")
async def delete_task(task_id: int):
    from app import task_manager

    if task_manager.is_running(task_id):
        await task_manager.cancel_task(task_id)
    if not await q.delete_task(task_id):
        raise HTTPException(404, "Task not found")
    return {"ok": True}


@router.post("/{task_id}/start")
async def start_task(task_id: int):
    from app import task_manager

    task = await _task_or_404(task_id)
    if task_manager.is_running(task_id):
        raise HTTPException(409, "Task is already running")
    if not await task_manager.start_task(task_id, force=True):
        raise HTTPException(409, f"Task cannot start from status '{task['status']}'")
    return {"ok": True, "status": "running"}


@router.post("/{task_id}/pause")
async def pause_task(task_id: int):
    from app import task_manager

    await _task_or_404(task_id)
    await task_manager.pause_task(task_id)
    return {"ok": True, "status": "paused"}


@router.post("/{task_id}/resume")
async def resume_task(task_id: int):
    from app import task_manager

    await _task_or_404(task_id)
    await task_manager.resume_task(task_id)
    return {"ok": True, "status": "running"}


@router.post("/{task_id}/cancel")
async def cancel_task(task_id: int):
    from app import task_manager

    await _task_or_404(task_id)
    await task_manager.cancel_task(task_id)
    return {"ok": True, "status": "cancelled"}


@router.post("/{task_id}/retry")
async def retry_task(task_id: int):
    from app import task_manager

    await _task_or_404(task_id)
    await task_manager.retry_task(task_id)
    return {"ok": True, "status": "running"}
