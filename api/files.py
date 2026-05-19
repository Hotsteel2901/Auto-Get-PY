from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter(prefix="/api/files", tags=["files"])


@router.get("")
async def list_files(dir: str = "./downloads"):
    allowed_base = Path("./downloads").resolve()
    base = Path(dir).resolve()
    if not str(base).startswith(str(allowed_base)):
        base = allowed_base
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
async def download_file(filename: str, dir: str = "./downloads"):
    allowed_base = Path("./downloads").resolve()
    base = Path(dir).resolve()
    if not str(base).startswith(str(allowed_base)):
        base = allowed_base
    filepath = base / filename
    if not filepath.exists() or not filepath.is_file():
        raise HTTPException(404, "File not found")
    return FileResponse(filepath, filename=filepath.name)
