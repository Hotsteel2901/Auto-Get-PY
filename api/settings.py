from fastapi import APIRouter
from db import queries as q

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("")
async def get_settings():
    settings = await q.get_settings()
    return {"settings": settings}


@router.put("")
async def update_settings(body: dict):
    for key, value in body.items():
        await q.update_setting(key, str(value) if not isinstance(value, str) else value)
    settings = await q.get_settings()
    return {"settings": settings}
