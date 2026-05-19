from fastapi import APIRouter
from db import queries as q

router = APIRouter(prefix="/api/tasks/{task_id}/downloads", tags=["downloads"])


@router.get("")
async def list_downloads(task_id: int, status: str = None):
    downloads = await q.list_downloads(task_id, status=status)
    return {"downloads": downloads}
