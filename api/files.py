from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter(prefix="/api/files", tags=["files"])


async def _get_allowed_base() -> Path:
    from db import queries as q
    try:
        settings = await q.get_settings()
        default_dir = settings.get("default_output_dir", "./downloads")
    except Exception:
        default_dir = "./downloads"
    return Path(default_dir).resolve()


def _resolve_allowed_path(directory: str, allowed_base: Path) -> Path:
    base = Path(directory).resolve()
    try:
        base.relative_to(allowed_base)
    except ValueError:
        base = allowed_base
    return base


@router.get("")
async def list_files(dir: str = None):
    allowed_base = await _get_allowed_base()
    target = dir or str(allowed_base)
    base = _resolve_allowed_path(target, allowed_base)
    if not base.exists():
        return {"files": []}
    files = []
    for f in sorted(base.rglob("*"), key=lambda x: x.stat().st_mtime, reverse=True):
        if f.is_file() and f.name != ".gitkeep":
            stat = f.stat()
            files.append({
                "name": f.name,
                "path": str(f.relative_to(base)),
                "size": stat.st_size,
                "mtime": stat.st_mtime,
            })
    return {"files": files[:200]}


@router.get("/download/{filename:path}")
async def download_file(filename: str, dir: str = None):
    allowed_base = await _get_allowed_base()
    target = dir or str(allowed_base)
    base = _resolve_allowed_path(target, allowed_base)
    filepath = base / filename
    try:
        filepath.relative_to(base)
    except ValueError:
        raise HTTPException(403, "Access denied")
    if not filepath.exists() or not filepath.is_file():
        raise HTTPException(404, "File not found")
    return FileResponse(filepath, filename=filepath.name)