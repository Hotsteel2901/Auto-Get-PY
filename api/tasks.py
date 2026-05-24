from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from db import queries as q

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


class TaskCreateBody(BaseModel):
    name: str
    url: str
    config: dict = {}


class TaskUpdateBody(BaseModel):
    name: str = None
    url: str = None
    config: dict = None


@router.get("")
async def list_tasks(status: str = None, offset: int = 0, limit: int = 20):
    tasks = await q.list_tasks(status=status, offset=offset, limit=limit)
    return {"tasks": tasks}


@router.post("")
async def create_task(body: TaskCreateBody):
    task = await q.create_task(body.name, body.url, body.config)
    return {"task": task}


@router.get("/{task_id}")
async def get_task(task_id: int):
    task = await q.get_task(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    return {"task": task}


@router.put("/{task_id}")
async def update_task(task_id: int, body: TaskUpdateBody):
    kwargs = {k: v for k, v in body.model_dump().items() if v is not None}
    if "config" in kwargs:
        import json
        kwargs["config"] = json.dumps(kwargs["config"])
    task = await q.update_task(task_id, **kwargs)
    if not task:
        raise HTTPException(404, "Task not found")
    return {"task": task}


@router.delete("/{task_id}")
async def delete_task(task_id: int):
    deleted = await q.delete_task(task_id)
    if not deleted:
        raise HTTPException(404, "Task not found")
    return {"ok": True}


@router.post("/{task_id}/start")
async def start_task(task_id: int):
    from app import task_manager
    task = await q.get_task(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    import json
    config = json.loads(task["config"]) if task["config"] else {}
    await task_manager.start_task(task_id, config)
    return {"ok": True}


@router.post("/{task_id}/pause")
async def pause_task(task_id: int):
    from app import task_manager
    await task_manager.pause_task(task_id)
    return {"ok": True}


@router.post("/{task_id}/resume")
async def resume_task(task_id: int):
    from app import task_manager
    await task_manager.resume_task(task_id)
    return {"ok": True}


@router.post("/{task_id}/retry")
async def retry_task(task_id: int):
    from app import task_manager
    await task_manager.retry_task(task_id)
    return {"ok": True}
