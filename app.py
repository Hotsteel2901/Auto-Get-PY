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
