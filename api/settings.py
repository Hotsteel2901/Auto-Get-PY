"""Settings routes.

Settings are stored as strings; the API coerces and validates the handful of
keys the application actually understands so a bad value cannot break a task.
"""

from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException

from db import queries as q
from db.schema import DEFAULT_SETTINGS

router = APIRouter(prefix="/api/settings", tags=["settings"])

# key -> (coercer, validator)
KNOWN_SETTINGS = {
    "default_concurrency": (int, lambda v: 1 <= v <= 50),
    "default_output_dir": (str, lambda v: bool(v.strip())),
    "default_decryptors": (str, lambda v: True),
    "aes_key": (str, lambda v: v == "" or _is_hex(v, 16, 32)),
    "aes_iv": (str, lambda v: v == "" or _is_hex(v, 16)),
    "default_crawl_depth": (int, lambda v: 0 <= v <= 50),
    "default_max_pages": (int, lambda v: 1 <= v <= 500000),
    "default_follow_links": (str, lambda v: v in ("true", "false")),
    "user_agent": (str, lambda v: True),
    "proxy": (str, lambda v: True),
}


def _is_hex(value: str, *lengths: int) -> bool:
    try:
        raw = bytes.fromhex(value)
    except ValueError:
        return False
    return len(raw) in lengths


@router.get("")
async def get_settings():
    settings = dict(DEFAULT_SETTINGS)
    settings.update(await q.get_settings())
    return {"settings": settings}


@router.put("")
async def update_settings(payload: dict = Body(...)):
    if not isinstance(payload, dict):
        raise HTTPException(400, "Expected a JSON object of settings")

    coerced: dict[str, str] = {}
    for key, raw in payload.items():
        if key not in KNOWN_SETTINGS:
            # Unknown keys are still stored: they may be used by a decryptor.
            coerced[key] = "" if raw is None else str(raw)
            continue

        caster, validator = KNOWN_SETTINGS[key]
        try:
            value = int(raw) if caster is int else str(raw).strip()
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, f"Invalid value for '{key}': {raw!r}") from exc

        if not validator(value):
            raise HTTPException(400, f"Out-of-range or malformed value for '{key}'")
        coerced[key] = str(value)

    await q.update_settings(coerced)

    settings = dict(DEFAULT_SETTINGS)
    settings.update(await q.get_settings())
    return {"settings": settings}
