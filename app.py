"""Auto-Get-PY — application entry point.

Mounts the REST API, the agent integration surface (under every supported
alias), and the single-page web UI, then starts uvicorn.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).parent

logging.basicConfig(
    level=os.environ.get("AUTO_GET_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
logger = logging.getLogger("auto_get_py")

from scraper.task_manager import TaskManager  # noqa: E402

task_manager = TaskManager()

# When set, every /api/** request must present this token. Unset by default so
# a fresh local checkout just works.
API_TOKEN = os.environ.get("AUTO_GET_TOKEN", "").strip()


@asynccontextmanager
async def lifespan(app: FastAPI):
    from db import queries as q
    from db.schema import init_db
    from scraper.decryptors import register_all

    await init_db()
    register_all()

    stuck = await q.reset_stuck_tasks()
    if stuck:
        logger.warning("Marked %d interrupted task(s) as failed on startup", stuck)

    if not API_TOKEN:
        logger.info("No AUTO_GET_TOKEN set — API is unauthenticated (local use only)")
    else:
        logger.info("API token authentication is enabled")

    yield

    await task_manager.shutdown()
    try:
        from scraper.browser import close_browser

        await close_browser()
    except Exception:  # noqa: BLE001 - browser may never have started
        pass


app = FastAPI(
    title="Auto-Get-PY",
    description=(
        "Universal media scraper. The canonical agent API lives under "
        "`/api/agent`; the same routes are also served under `/api/hermes`, "
        "`/api/opencode`, `/api/dsh`, `/api/codex`, `/api/claude` and others."
    ),
    version="1.1.0",
    lifespan=lifespan,
)


# ── Optional token authentication ───────────────────────────────────────────


@app.middleware("http")
async def token_guard(request: Request, call_next):
    if not API_TOKEN:
        return await call_next(request)

    path = request.url.path
    if not path.startswith("/api/") or path == "/api/health":
        return await call_next(request)

    supplied = ""
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        supplied = header[7:].strip()
    if not supplied:
        supplied = request.headers.get("x-api-token", "") or request.query_params.get("token", "")

    if supplied != API_TOKEN:
        return JSONResponse(
            {"detail": "Invalid or missing API token"}, status_code=401)
    return await call_next(request)


# ── Routers ─────────────────────────────────────────────────────────────────

from api.agent import router as agent_router  # noqa: E402
from api.agent_registry import CANONICAL_PREFIX, all_aliases  # noqa: E402
from api.downloads import router as downloads_router  # noqa: E402
from api.files import router as files_router  # noqa: E402
from api.settings import router as settings_router  # noqa: E402
from api.tasks import router as tasks_router  # noqa: E402
from api.websocket import router as ws_router  # noqa: E402

app.include_router(tasks_router)
app.include_router(downloads_router)
app.include_router(settings_router)
app.include_router(files_router)
app.include_router(ws_router)

# Canonical agent API goes in the OpenAPI schema; aliases stay out of it so
# /docs does not show the same operation thirty times.
app.include_router(agent_router, prefix=CANONICAL_PREFIX)
for alias in all_aliases():
    if alias != CANONICAL_PREFIX:
        app.include_router(agent_router, prefix=alias, include_in_schema=False)

logger.info("Agent API aliases: %s", ", ".join(all_aliases()))


# ── Web UI ──────────────────────────────────────────────────────────────────

webui_path = BASE_DIR / "webui"
if webui_path.exists():
    app.mount("/webui", StaticFiles(directory=str(webui_path)), name="webui")

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        from fastapi.responses import Response

        return Response(status_code=204)


@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/webui/index.html")


@app.get("/api/health", tags=["system"])
async def health():
    return {"status": "ok", "version": app.version}


@app.get("/api/system", tags=["system"])
async def system_info():
    """Runtime facts the UI shows in the header and the Settings page."""
    from api.agent_registry import AGENTS

    return {
        "version": app.version,
        "auth_required": bool(API_TOKEN),
        "python": os.sys.version.split()[0],
        "downloads_dir": str(Path("./downloads").resolve()),
        "running_tasks": task_manager.running_task_ids,
        "agent_aliases": all_aliases(),
        "agent_count": len(AGENTS),
    }


if __name__ == "__main__":
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(description="Auto-Get-PY — media scraper")
    parser.add_argument("--host", default="127.0.0.1",
                        help="Bind host (default: 127.0.0.1; use 0.0.0.0 to expose)")
    parser.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000)")
    parser.add_argument("--reload", action="store_true", help="Auto-reload (dev mode)")
    args = parser.parse_args()

    if args.host not in ("127.0.0.1", "localhost") and not API_TOKEN:
        logger.warning(
            "Binding to %s without AUTO_GET_TOKEN set — anyone on the network can "
            "use this scraper. Set AUTO_GET_TOKEN to require a token.", args.host)

    print(f"\n  Auto-Get-PY  →  http://{args.host}:{args.port}\n")
    uvicorn.run("app:app", host=args.host, port=args.port, reload=args.reload)
