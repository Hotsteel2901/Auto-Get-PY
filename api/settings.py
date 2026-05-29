from fastapi import APIRouter, Body
from db import queries as q

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("")
async def get_settings():
    settings = await q.get_settings()
    return {"settings": settings}


@router.put("")
async def update_settings(settings: dict[str, str] = Body(..., embed=False)):
    for key, value in settings.items():
        await q.update_setting(key, value)
    settings_result = await q.get_settings()
    return {"settings": settings_result}
