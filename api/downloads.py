"""Download listing routes."""

from __future__ import annotations

from fastapi import APIRouter, Query

from db import queries as q

router = APIRouter(prefix="/api", tags=["downloads"])


@router.get("/downloads")
async def list_all_downloads(status: str | None = None,
                             limit: int = Query(500, ge=1, le=5000),
                             offset: int = Query(0, ge=0)):
    """Every download across every task, newest first."""
    downloads = await q.list_all_downloads(status=status, limit=limit, offset=offset)
    return {"downloads": downloads, "count": len(downloads)}


@router.get("/tasks/{task_id}/downloads")
async def list_task_downloads(task_id: int, status: str | None = None):
    downloads = await q.list_downloads(task_id, status=status)
    return {
        "downloads": downloads,
        "count": len(downloads),
        "stats": await q.get_download_stats(task_id),
    }
