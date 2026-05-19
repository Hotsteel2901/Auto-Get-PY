from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pathlib import Path

BASE_DIR = Path(__file__).parent

from scraper.task_manager import TaskManager

task_manager = TaskManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    from db.schema import init_db
    from scraper.decryptors import register_all
    await init_db()
    register_all()
    yield
    await task_manager.shutdown()


app = FastAPI(title="Web Scraper", lifespan=lifespan)

from api.tasks import router as tasks_router
from api.downloads import router as downloads_router
from api.settings import router as settings_router
from api.files import router as files_router
from api.websocket import router as ws_router

app.include_router(tasks_router)
app.include_router(downloads_router)
app.include_router(settings_router)
app.include_router(files_router)
app.include_router(ws_router)

webui_path = BASE_DIR / "webui"
if webui_path.exists():
    app.mount("/webui", StaticFiles(directory=str(webui_path)), name="webui")


@app.get("/")
async def root():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/webui/index.html")


@app.get("/api/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(description="Web Scraper + Media Downloader")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000)")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload (dev mode)")
    args = parser.parse_args()

    print(f"Web Scraper starting at http://{args.host}:{args.port}")
    uvicorn.run("app:app", host=args.host, port=args.port, reload=args.reload)
