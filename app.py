from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from scraper.task_manager import TaskManager

BASE_DIR = Path(__file__).parent

task_manager = TaskManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    from db.schema import init_db
    await init_db()
    yield


app = FastAPI(title="Web Scraper", lifespan=lifespan)


@app.get("/api/health")
async def health():
    return {"status": "ok"}
