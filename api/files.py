"""Serving downloaded files to the browser.

Every path is resolved and confined to the configured output directory, so a
crafted ``..``/absolute filename cannot escape it.
"""

from __future__ import annotations

import mimetypes
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

router = APIRouter(prefix="/api/files", tags=["files"])

MAX_LISTING = 2000


async def _allowed_base() -> Path:
    """The one directory file browsing is permitted inside."""
    from db import queries as q

    try:
        settings = await q.get_settings()
        configured = settings.get("default_output_dir") or "./downloads"
    except Exception:  # noqa: BLE001 - fall back to the default location
        configured = "./downloads"
    return Path(configured).expanduser().resolve()


def _confine(candidate: Path, base: Path) -> Path:
    """Resolve ``candidate`` and refuse anything outside ``base``."""
    resolved = candidate.resolve()
    if resolved != base and base not in resolved.parents:
        raise HTTPException(403, "Access denied: outside the download directory")
    return resolved


def _human_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


@router.get("")
async def list_files(dir: str | None = None, sort: str = Query("mtime"),
                     search: str | None = None):
    base = await _allowed_base()
    target = _confine(Path(dir).expanduser() if dir else base, base)

    if not target.exists() or not target.is_dir():
        return {"files": [], "total": 0, "directory": str(target),
                "base_directory": str(base), "total_size": 0}

    entries: list[dict] = []
    total_size = 0
    needle = (search or "").lower()

    for path in target.rglob("*"):
        if path.name == ".gitkeep":
            continue
        try:
            if not path.is_file():
                continue
            stat = path.stat()
        except OSError:
            # The file vanished between listing and stat: skip it.
            continue

        relative = str(path.relative_to(target))
        if needle and needle not in relative.lower():
            continue

        total_size += stat.st_size
        entries.append({
            "name": path.name,
            "path": relative,
            "size": stat.st_size,
            "size_human": _human_size(stat.st_size),
            "mtime": stat.st_mtime,
            "mime": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        })

    if sort == "name":
        entries.sort(key=lambda e: e["name"].lower())
    elif sort == "size":
        entries.sort(key=lambda e: e["size"], reverse=True)
    else:
        entries.sort(key=lambda e: e["mtime"], reverse=True)

    return {
        "files": entries[:MAX_LISTING],
        "total": len(entries),
        "total_size": total_size,
        "directory": str(target),
        "base_directory": str(base),
    }


@router.get("/download/{filename:path}")
async def download_file(filename: str, dir: str | None = None,
                        inline: bool = False):
    base = await _allowed_base()
    target_dir = _confine(Path(dir).expanduser() if dir else base, base)
    filepath = _confine(target_dir / filename, base)

    if not filepath.exists() or not filepath.is_file():
        raise HTTPException(404, "File not found")

    content_type = mimetypes.guess_type(filepath.name)[0] or "application/octet-stream"
    return FileResponse(
        filepath,
        filename=filepath.name,
        media_type=content_type,
        content_disposition_type="inline" if inline else "attachment",
    )


@router.delete("/{filename:path}")
async def delete_file(filename: str, dir: str | None = None):
    base = await _allowed_base()
    target_dir = _confine(Path(dir).expanduser() if dir else base, base)
    filepath = _confine(target_dir / filename, base)

    if not filepath.exists() or not filepath.is_file():
        raise HTTPException(404, "File not found")
    try:
        os.remove(filepath)
    except OSError as exc:
        raise HTTPException(500, f"Could not delete the file: {exc}") from exc
    return {"ok": True, "deleted": filepath.name}
