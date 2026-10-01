"""The canonical agent-facing API.

This router declares its paths *without* a prefix so it can be mounted under
every supported alias — ``/api/agent``, ``/api/hermes``, ``/api/opencode``,
``/api/dsh``, ``/api/codex``, ``/api/claude`` … — with ``app.include_router``.
One implementation, many front doors.

Everything here is designed for a program (an AI coding agent) to drive:
predictable JSON, no hidden state, and enough metadata
(:func:`api.agent_docs.build_manifest`) for a client to configure itself.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

from api.agent_docs import build_manifest, render_agent_doc, render_skill
from api.agent_registry import (
    AGENTS,
    AGENTS_BY_ID,
    CANONICAL_PREFIX,
    registry_payload,
    resolve_agent,
)
from db import queries as q

router = APIRouter(tags=["agent"])

TERMINAL_STATUSES = ("completed", "failed", "cancelled")


# ── Request models ──────────────────────────────────────────────────────────


class ScrapeRequest(BaseModel):
    url: str = Field(..., description="Target URL to scrape")
    name: str = Field(default="Agent task", max_length=200)

    crawl_depth: int = Field(default=0, ge=0, le=50)
    max_pages: int = Field(default=500, ge=1, le=500000)
    max_media: int = Field(default=20000, ge=1, le=500000)
    max_links_per_page: int = Field(default=20, ge=1, le=500)
    follow_pagination: bool = True
    follow_links: bool = False
    allowed_paths: Optional[list[str]] = None

    use_browser: bool = False
    crawl_css: bool = True
    crawl_iframes: bool = True
    site_discovery: bool = False
    extract_base64: bool = False
    probe_links: bool = False

    file_types: Optional[list[str]] = None

    concurrency: int = Field(default=5, ge=1, le=50)
    request_delay_sec: float = Field(default=0.5, ge=0)
    request_timeout_sec: int = Field(default=30, ge=3, le=600)
    max_retries: int = Field(default=3, ge=0, le=10)
    proxy: Optional[str] = None
    custom_headers: Optional[dict] = None

    decryptors: Optional[list[str]] = None
    decryptor_opts: Optional[dict] = None

    output_dir: str = "./downloads"
    max_file_size_mb: int = Field(default=500, ge=0)

    wait: bool = False
    wait_timeout: int = Field(default=300, ge=10, le=3600)


class QuickRequest(BaseModel):
    url: str
    crawl_depth: int = Field(default=1, ge=0, le=10)
    max_pages: int = Field(default=50, ge=1, le=1000)
    follow_pagination: bool = True
    follow_links: bool = False
    use_browser: bool = False
    site_discovery: bool = False
    file_types: Optional[list[str]] = None
    proxy: Optional[str] = None
    custom_headers: Optional[dict] = None
    concurrency: int = Field(default=8, ge=1, le=32)


class DirectRequest(BaseModel):
    url: str
    output_dir: str = "./downloads"
    max_scrolls: int = Field(default=3, ge=0, le=50)
    timeout: int = Field(default=20, ge=5, le=120)
    concurrency: int = Field(default=10, ge=1, le=50)
    proxy: Optional[str] = None
    file_types: Optional[list[str]] = None


class FetchRequest(BaseModel):
    url: str
    output_dir: str = "./downloads"
    filename: Optional[str] = None
    headers: Optional[dict] = None
    proxy: Optional[str] = None
    referer: Optional[str] = None
    timeout: int = Field(default=60, ge=5, le=3600)
    max_file_size_mb: int = Field(default=0, ge=0)


# ── Discovery endpoints ─────────────────────────────────────────────────────


@router.get("/health")
async def agent_health():
    return {"status": "ok", "service": "auto-get-py"}


@router.get("/manifest")
async def agent_manifest(request: Request):
    base = str(request.base_url).rstrip("/")
    return build_manifest(base)


@router.get("/agents")
async def agent_list():
    return {"agents": registry_payload(), "canonical_prefix": CANONICAL_PREFIX}


@router.get("/agents/{agent_id:path}")
async def agent_detail(agent_id: str):
    agent = resolve_agent(agent_id)
    if not agent:
        raise HTTPException(404, f"Unknown agent '{agent_id}'. See GET /agents")
    payload = next(item for item in registry_payload() if item["id"] == agent.id)
    payload["skill_url"] = f"{agent.primary_prefix}/skill?agent={agent.id}"
    return payload


@router.get("/skill")
async def agent_skill(request: Request, agent: str = Query("generic"),
                      format: str = Query("md")):
    """The instructions document for an agent, ready to drop into a prompt."""
    descriptor = resolve_agent(agent) or AGENTS_BY_ID["generic"]
    base = str(request.base_url).rstrip("/")
    markdown = render_skill(descriptor, base)

    if format == "json":
        return JSONResponse({
            "agent": descriptor.id,
            "name": descriptor.name,
            "alias": descriptor.primary_prefix,
            "markdown": markdown,
        })
    return PlainTextResponse(markdown, media_type="text/markdown; charset=utf-8")


@router.get("/docs/{agent_id:path}", response_class=PlainTextResponse)
async def agent_docs(request: Request, agent_id: str):
    descriptor = resolve_agent(agent_id)
    if not descriptor:
        raise HTTPException(404, f"Unknown agent '{agent_id}'")
    base = str(request.base_url).rstrip("/")
    return PlainTextResponse(
        render_agent_doc(descriptor, base), media_type="text/markdown; charset=utf-8")


# ── Scrape endpoints ────────────────────────────────────────────────────────


def _config_from(req: ScrapeRequest) -> dict[str, Any]:
    config: dict[str, Any] = {
        "concurrency": req.concurrency,
        "output_dir": req.output_dir,
        "request_delay_sec": req.request_delay_sec,
        "request_timeout_sec": req.request_timeout_sec,
        "max_retries": req.max_retries,
        "max_file_size_mb": req.max_file_size_mb,
        "crawl_depth": req.crawl_depth,
        "max_pages": req.max_pages,
        "max_media": req.max_media,
        "max_links_per_page": req.max_links_per_page,
        "follow_pagination": req.follow_pagination,
        "follow_links": req.follow_links,
        "crawl_css": req.crawl_css,
        "crawl_iframes": req.crawl_iframes,
        "use_browser": req.use_browser,
        "site_discovery": req.site_discovery,
        "extract_base64": req.extract_base64,
        "probe_links": req.probe_links,
    }
    if req.file_types:
        exts = [e.lstrip(".").lower() for e in req.file_types if e]
        config["url_filters"] = {"include": [f"*.{ext}" for ext in exts]}
    if req.allowed_paths:
        config["allowed_paths"] = req.allowed_paths
    if req.proxy:
        config["proxy"] = req.proxy
    if req.custom_headers:
        config["custom_headers"] = req.custom_headers
    if req.decryptors:
        config["decryptors"] = req.decryptors
    if req.decryptor_opts:
        config["decryptor_opts"] = req.decryptor_opts
    return config


@router.post("/scrape")
async def agent_scrape(req: ScrapeRequest):
    """Crawl and download. Returns a task handle, or the result when waiting."""
    from app import task_manager

    task = await q.create_task(req.name, req.url, _config_from(req))
    task_id = task["id"]
    await task_manager.start_task(task_id)

    if not req.wait:
        return {
            "task_id": task_id,
            "status": "running",
            "status_url": f"/api/agent/status/{task_id}",
            "results_url": f"/api/agent/results/{task_id}",
        }

    deadline = time.monotonic() + req.wait_timeout
    while time.monotonic() < deadline:
        await asyncio.sleep(1.0)
        fresh = await q.get_task(task_id)
        if not fresh:
            raise HTTPException(500, "Task disappeared while waiting")
        if fresh["status"] in TERMINAL_STATUSES:
            return await results_for(fresh)

    return {
        "task_id": task_id,
        "status": "timeout",
        "message": f"Not finished within {req.wait_timeout}s; keep polling.",
        "status_url": f"/api/agent/status/{task_id}",
        "results_url": f"/api/agent/results/{task_id}",
    }


@router.post("/quick")
async def agent_quick(req: QuickRequest):
    """Discover media URLs without downloading. Cheap, safe, idempotent."""
    from scraper.engine import CrawlConfig, ScraperEngine

    config = CrawlConfig.from_dict(req.url, {
        "crawl_depth": req.crawl_depth,
        "max_pages": req.max_pages,
        "follow_pagination": req.follow_pagination,
        "follow_links": req.follow_links,
        "use_browser": req.use_browser,
        "site_discovery": req.site_discovery,
        "crawl_css": True,
        "crawl_iframes": True,
        "concurrency": req.concurrency,
        "proxy": req.proxy,
        "custom_headers": req.custom_headers,
        "request_timeout_sec": 30,
        "url_filters": ({"include": [f"*.{e.lstrip('.')}" for e in req.file_types]}
                        if req.file_types else None),
    })

    pause = asyncio.Event()
    pause.set()
    engine = ScraperEngine(0, asyncio.Semaphore(1), pause)
    await engine.discover(config)

    urls = engine.discovered_urls
    return {
        "url": req.url,
        "pages_crawled": engine.pages_fetched,
        "media_urls_found": len(urls),
        "urls": urls,
        "truncated": len(urls) >= config.max_media,
    }


@router.post("/direct")
async def agent_direct(req: DirectRequest):
    """Playwright render then download, synchronously. Best for SPA pages."""
    from scraper.browser import render_page
    from scraper.downloader import Downloader
    from scraper.extractor import canonicalize_url, extract_media_urls

    headers = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
    }

    rendered = await render_page(
        req.url, headers=headers, timeout=req.timeout, proxy=req.proxy,
        scroll=req.max_scrolls > 0, max_scrolls=req.max_scrolls,
        scroll_delay=1.0, wait_after_load=2.0)

    html = rendered.get("html") or ""
    candidates: set[str] = set(rendered.get("network_urls") or set())
    if html:
        candidates.update(extract_media_urls(html, req.url))

    if req.file_types:
        wanted = tuple(f".{e.lstrip('.').lower()}" for e in req.file_types)
        candidates = {u for u in candidates
                      if u.lower().split("?")[0].split("#")[0].endswith(wanted)}

    seen: set[str] = set()
    unique: list[str] = []
    for url in candidates:
        key = canonicalize_url(url)
        if key not in seen:
            seen.add(key)
            unique.append(url)

    if not unique:
        return {
            "url": req.url, "status": "completed", "media_found": 0,
            "completed": 0, "failed": 0, "files": [],
            "message": ("No media found. Try a larger max_scrolls, or use "
                        "/scrape with site_discovery=true."),
        }

    downloader = Downloader(output_dir=req.output_dir)
    semaphore = asyncio.Semaphore(req.concurrency)
    session = Downloader.create_session()
    completed: list[dict] = []
    failed: list[dict] = []

    async def fetch(url: str) -> None:
        async with semaphore:
            outcome = await downloader.download_file(
                url, output_dir=req.output_dir, timeout=req.timeout,
                proxy=req.proxy, headers=headers, session=session)
            if outcome.ok:
                completed.append({
                    "filename": outcome.get("filename"),
                    "url": url,
                    "size_bytes": outcome.get("file_size", 0),
                    "filepath": outcome.get("filepath"),
                })
            else:
                failed.append({"url": url,
                               "error": outcome.get("error_msg", "unknown")})

    try:
        await asyncio.gather(*(fetch(u) for u in unique), return_exceptions=True)
    finally:
        await session.close()

    return {
        "url": req.url,
        "status": "completed",
        "media_found": len(unique),
        "completed": len(completed),
        "failed": len(failed),
        "total_size_bytes": sum(f.get("size_bytes", 0) for f in completed),
        "output_dir": req.output_dir,
        "files": completed,
        "errors": failed or None,
    }


@router.post("/fetch")
async def agent_fetch(req: FetchRequest):
    """Download exactly one URL. No crawling, no discovery."""
    from scraper.downloader import Downloader

    downloader = Downloader(output_dir=req.output_dir)
    session = Downloader.create_session()
    try:
        outcome = await downloader.download_file(
            req.url, output_dir=req.output_dir, filename=req.filename,
            headers=req.headers, proxy=req.proxy, referer=req.referer,
            timeout=req.timeout, session=session,
            max_file_size_mb=req.max_file_size_mb or None)
    finally:
        await session.close()

    if not outcome.ok:
        raise HTTPException(502, outcome.get("error_msg") or "Download failed")
    return {
        "status": "completed",
        "filename": outcome.get("filename"),
        "filepath": outcome.get("filepath"),
        "size_bytes": outcome.get("file_size", 0),
        "mime_type": outcome.get("mime_type"),
        "segments": outcome.get("segments"),
    }


# ── Task inspection ─────────────────────────────────────────────────────────


@router.get("/status/{task_id}")
async def agent_status(task_id: int):
    task = await q.get_task(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    stats = await q.get_download_stats(task_id)
    extra = task.get("extra_info") or {}
    return {
        "task_id": task_id,
        "status": task["status"],
        "name": task.get("name", ""),
        "url": task.get("url", ""),
        "progress": task.get("progress", 0.0),
        "total_files": task.get("total_files", 0),
        "done_files": task.get("done_files", 0),
        "downloads": stats,
        "pages_crawled": extra.get("pages_crawled", 0),
        "total_media_found": extra.get("total_media_found", 0),
        "css_files_crawled": extra.get("css_files_crawled", 0),
        "error_msg": task.get("error_msg"),
        "created_at": task.get("created_at"),
        "updated_at": task.get("updated_at"),
    }


@router.get("/results/{task_id}")
async def agent_results(task_id: int):
    task = await q.get_task(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    return await results_for(task)


@router.post("/cancel/{task_id}")
async def agent_cancel(task_id: int):
    from app import task_manager

    if not await q.get_task(task_id):
        raise HTTPException(404, "Task not found")
    await task_manager.cancel_task(task_id)
    return {"task_id": task_id, "status": "cancelled"}


@router.get("/tasks")
async def agent_tasks(status: str | None = None,
                      limit: int = Query(20, ge=1, le=200)):
    tasks = await q.list_tasks(status=status, limit=limit)
    return {"tasks": tasks, "count": len(tasks)}


@router.get("/files")
async def agent_files(limit: int = Query(200, ge=1, le=2000)):
    from api.files import _allowed_base, _confine

    base = await _allowed_base()
    target = _confine(base, base)
    if not target.exists():
        return {"files": [], "total": 0, "directory": str(base)}

    entries: list[dict] = []
    for path in target.rglob("*"):
        try:
            if not path.is_file() or path.name == ".gitkeep":
                continue
            stat = path.stat()
        except OSError:
            continue
        entries.append({
            "name": path.name,
            "path": str(path.relative_to(target)),
            "size": stat.st_size,
            "mtime": stat.st_mtime,
        })
    entries.sort(key=lambda item: item["mtime"], reverse=True)
    return {"files": entries[:limit], "total": len(entries), "directory": str(base)}


# ── Shared helper ───────────────────────────────────────────────────────────


async def results_for(task: dict) -> dict:
    """Full result payload for a finished (or in-flight) task."""
    task_id = task["id"]
    downloads = await q.list_downloads(task_id)

    completed = [d for d in downloads if d["status"] == "completed"]
    failed = [d for d in downloads if d["status"] == "failed"]
    extra = task.get("extra_info") or {}
    config = task.get("config_parsed") or {}

    return {
        "task_id": task_id,
        "status": task["status"],
        "name": task.get("name", ""),
        "url": task.get("url", ""),
        "output_dir": config.get("output_dir", "./downloads"),
        "stats": {
            "total_files": task.get("total_files", 0),
            "completed": len(completed),
            "failed": len(failed),
            "total_size_bytes": sum(d.get("file_size") or 0 for d in completed),
            "pages_crawled": extra.get("pages_crawled", 0),
            "total_media_found": extra.get("total_media_found", 0),
            "css_files_crawled": extra.get("css_files_crawled", 0),
        },
        "completed_files": [
            {
                "filename": d.get("filename"),
                "url": d["url"],
                "size_bytes": d.get("file_size") or 0,
                "filepath": d.get("filepath"),
                "mime_type": d.get("mime_type"),
            }
            for d in completed
        ],
        "failed_files": [
            {"filename": d.get("filename"), "url": d["url"],
             "error": d.get("error_msg") or "unknown"}
            for d in failed
        ],
        "error_msg": task.get("error_msg"),
    }
