"""Hermes Agent Integration API.

Provides endpoints for Hermes Agent (or any AI agent) to programmatically:
- Trigger a scraping task and wait for results
- Get task status and progress
- List discovered media URLs
- Download results summary

Usage from Hermes Agent:
    POST /api/hermes/scrape  — Start scrape, optionally wait for completion
    GET  /api/hermes/status/{task_id}  — Check task status
    GET  /api/hermes/results/{task_id}  — Get download results
    POST /api/hermes/quick  — One-shot: scrape URL + return media list (no download)
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional
import asyncio
import json
import time

from db import queries as q

router = APIRouter(prefix="/api/hermes", tags=["hermes"])


# ── Request/Response models ─────────────────────────────────────────────────

class ScrapeRequest(BaseModel):
    """Full scraping request with all options."""
    url: str = Field(..., description="Target URL to scrape")
    name: str = Field(default="Hermes Agent Task", description="Task name")

    # Crawling
    crawl_depth: int = Field(default=0, ge=0, le=20,
                             description="0=single page, 1+=follow links")
    max_pages: int = Field(default=200, ge=1, le=100000,
                           description="Max pages to crawl")
    follow_pagination: bool = Field(default=True, description="Auto-follow next page")
    follow_links: bool = Field(default=False, description="Follow <a href> links")
    allowed_paths: Optional[list[str]] = Field(default=None,
                                                description="Restrict crawl to these path prefixes")

    # Smart extraction
    use_browser: bool = Field(default=False,
                              description="Use Playwright for JS-heavy sites")
    crawl_css: bool = Field(default=True, description="Crawl CSS files for URLs")
    crawl_iframes: bool = Field(default=True, description="Crawl iframe content")
    site_discovery: bool = Field(default=False,
                                 description="Discover via sitemap.xml/robots.txt/RSS")
    extract_base64: bool = Field(default=False,
                                 description="Extract inline base64 images")

    # Filtering
    file_types: Optional[list[str]] = Field(
        default=None,
        description="File extensions to include (e.g. ['jpg', 'mp4']). None = all media"
    )

    # Network
    concurrency: int = Field(default=5, ge=1, le=50)
    request_delay_sec: float = Field(default=0.5, ge=0)
    request_timeout_sec: int = Field(default=30, ge=5)
    max_retries: int = Field(default=3, ge=0)
    proxy: Optional[str] = Field(default=None,
                                  description="Proxy URL (http/https/socks5)")
    custom_headers: Optional[dict] = Field(default=None)

    # Decryption
    decryptors: Optional[list[str]] = Field(default=None,
                                             description="Decryptor names to enable")
    decryptor_opts: Optional[dict] = Field(default=None)

    # Output
    output_dir: str = Field(default="./downloads")
    max_file_size_mb: int = Field(default=500)

    # Control
    wait: bool = Field(default=False,
                       description="Wait for task to complete before responding")
    wait_timeout: int = Field(default=300, ge=10, le=3600,
                              description="Max seconds to wait (if wait=true)")


class QuickScrapeRequest(BaseModel):
    """Lightweight request: just discover media URLs without downloading."""
    url: str = Field(..., description="Target URL")
    crawl_depth: int = Field(default=1, ge=0, le=5)
    max_pages: int = Field(default=50, ge=1, le=500)
    follow_pagination: bool = Field(default=True)
    use_browser: bool = Field(default=False)
    site_discovery: bool = Field(default=False)
    file_types: Optional[list[str]] = Field(default=None)
    proxy: Optional[str] = Field(default=None)
    custom_headers: Optional[dict] = Field(default=None)


# ── Endpoints ───────────────────────────────────────────────────────────────

@router.post("/scrape")
async def hermes_scrape(req: ScrapeRequest):
    """Start a full scraping task. Optionally wait for completion.

    Returns task info immediately, or waits and returns final results.
    """
    config = {
        "concurrency": req.concurrency,
        "output_dir": req.output_dir,
        "request_delay_sec": req.request_delay_sec,
        "request_timeout_sec": req.request_timeout_sec,
        "max_retries": req.max_retries,
        "max_file_size_mb": req.max_file_size_mb,
        "crawl_depth": req.crawl_depth,
        "max_pages": req.max_pages,
        "follow_pagination": req.follow_pagination,
        "follow_links": req.follow_links,
        "crawl_css": req.crawl_css,
        "crawl_iframes": req.crawl_iframes,
        "use_browser": req.use_browser,
        "site_discovery": req.site_discovery,
        "extract_base64": req.extract_base64,
    }

    if req.file_types:
        config["url_filters"] = {"include": [f"*.{ext}" for ext in req.file_types]}
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

    # Create task
    task = await q.create_task(req.name, req.url, config)

    # Start task
    from app import task_manager
    await task_manager.start_task(task["id"])

    if not req.wait:
        return {
            "task_id": task["id"],
            "status": "running",
            "message": f"Task started. Poll /api/hermes/status/{task['id']} for progress.",
            "status_url": f"/api/hermes/status/{task['id']}",
            "results_url": f"/api/hermes/results/{task['id']}",
        }

    # Wait for completion with polling
    deadline = time.time() + req.wait_timeout
    while time.time() < deadline:
        await asyncio.sleep(2)
        t = await q.get_task(task["id"])
        if not t:
            raise HTTPException(500, "Task disappeared")
        if t["status"] in ("completed", "failed"):
            return await _build_results_response(t)

    return {
        "task_id": task["id"],
        "status": "timeout",
        "message": f"Task did not complete within {req.wait_timeout}s. Continue polling.",
        "status_url": f"/api/hermes/status/{task['id']}",
        "results_url": f"/api/hermes/results/{task['id']}",
    }


@router.get("/status/{task_id}")
async def hermes_status(task_id: int):
    """Get task status with progress info."""
    t = await q.get_task(task_id)
    if not t:
        raise HTTPException(404, "Task not found")

    downloads = await q.list_downloads(task_id)
    completed = sum(1 for d in downloads if d["status"] == "completed")
    failed = sum(1 for d in downloads if d["status"] == "failed")
    downloading = sum(1 for d in downloads if d["status"] == "downloading")
    pending = sum(1 for d in downloads if d["status"] == "pending")

    extra_info = {}
    if t.get("extra_info"):
        try:
            extra_info = json.loads(t["extra_info"])
        except (json.JSONDecodeError, TypeError):
            pass

    return {
        "task_id": task_id,
        "status": t["status"],
        "url": t.get("url", ""),
        "total_files": t.get("total_files", 0),
        "done_files": t.get("done_files", 0),
        "downloads": {
            "completed": completed,
            "failed": failed,
            "downloading": downloading,
            "pending": pending,
            "total": len(downloads),
        },
        "pages_crawled": extra_info.get("pages_crawled", 0),
        "total_media_found": extra_info.get("total_media_found", 0),
        "error_msg": t.get("error_msg"),
    }


@router.get("/results/{task_id}")
async def hermes_results(task_id: int):
    """Get final download results for a completed task."""
    t = await q.get_task(task_id)
    if not t:
        raise HTTPException(404, "Task not found")
    return await _build_results_response(t)


@router.post("/quick")
async def hermes_quick_scrape(req: QuickScrapeRequest):
    """Quick scrape: discover media URLs without downloading.

    Returns a list of all media URLs found. Useful for:
    - Previewing what would be downloaded
    - Getting media URLs for further processing
    - Feeding URLs into other tools
    """
    from scraper.extractor import (
        extract_media_urls, find_next_page_url, extract_page_links,
        extract_iframe_urls, extract_noscript_template_urls,
        find_meta_refresh_url, canonicalize_url,
    )
    from scraper.site_crawler import discover_site
    import aiohttp

    headers = (req.custom_headers or {}).copy()
    headers.setdefault("User-Agent",
                       "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/131.0.0.0 Safari/537.36")

    all_urls = set()
    visited = set()
    pages_crawled = 0

    include_filters = [f"*.{ext}" for ext in req.file_types] if req.file_types else None

    # Site discovery
    if req.site_discovery:
        try:
            discovery = await discover_site(req.url, headers=headers, proxy=req.proxy)
            all_urls.update(discovery.get("feed_media_urls", []))
        except Exception:
            pass

    # Crawl pages
    async def crawl(url, depth):
        nonlocal pages_crawled
        if url in visited or depth > req.crawl_depth:
            return
        if pages_crawled >= req.max_pages:
            return
        visited.add(url)
        pages_crawled += 1

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, headers=headers,
                    timeout=aiohttp.ClientTimeout(total=req.request_timeout_sec),
                    proxy=req.proxy,
                ) as resp:
                    if resp.status != 200:
                        return
                    raw = await resp.read()
                    from scraper.extractor import detect_encoding
                    enc = detect_encoding(dict(resp.headers), raw)
                    try:
                        html = raw.decode(enc, errors='replace')
                    except Exception:
                        html = raw.decode('utf-8', errors='replace')
        except Exception:
            return

        # Extract media
        found = extract_media_urls(html, url, include_filters=include_filters)
        all_urls.update(found)

        # Noscript/template
        ns = extract_noscript_template_urls(html, url)
        all_urls.update(ns)

        # Meta refresh
        refresh = find_meta_refresh_url(html, url)
        if refresh and refresh not in visited:
            await crawl(refresh, depth)

        # Follow links
        if depth < req.crawl_depth:
            if req.follow_pagination:
                next_url = find_next_page_url(html, url)
                if next_url and next_url not in visited:
                    await crawl(next_url, depth + 1)

            links = extract_page_links(html, url, same_domain=True)
            for link in links[:10]:
                if link not in visited:
                    await crawl(link, depth + 1)

    await crawl(req.url, 0)

    # Deduplicate with canonicalization
    seen = set()
    unique = []
    for u in all_urls:
        canon = canonicalize_url(u)
        if canon not in seen:
            seen.add(canon)
            unique.append(u)

    return {
        "url": req.url,
        "pages_crawled": pages_crawled,
        "media_urls_found": len(unique),
        "urls": unique,
    }


@router.post("/cancel/{task_id}")
async def hermes_cancel(task_id: int):
    """Cancel a running task."""
    from app import task_manager
    t = await q.get_task(task_id)
    if not t:
        raise HTTPException(404, "Task not found")
    await task_manager.pause_task(task_id)
    await q.update_task(task_id, status="cancelled")
    return {"task_id": task_id, "status": "cancelled"}


# ── Helpers ─────────────────────────────────────────────────────────────────

async def _build_results_response(task: dict) -> dict:
    """Build a rich results response from a task."""
    task_id = task["id"]
    downloads = await q.list_downloads(task_id)

    completed_dl = [d for d in downloads if d["status"] == "completed"]
    failed_dl = [d for d in downloads if d["status"] == "failed"]

    extra_info = {}
    if task.get("extra_info"):
        try:
            extra_info = json.loads(task["extra_info"])
        except (json.JSONDecodeError, TypeError):
            pass

    config = {}
    if task.get("config"):
        try:
            config = json.loads(task["config"])
        except (json.JSONDecodeError, TypeError):
            pass

    return {
        "task_id": task_id,
        "status": task["status"],
        "url": task.get("url", ""),
        "output_dir": config.get("output_dir", "./downloads"),
        "stats": {
            "total_files": task.get("total_files", 0),
            "completed": len(completed_dl),
            "failed": len(failed_dl),
            "total_size_bytes": sum(d.get("file_size", 0) or 0 for d in completed_dl),
            "pages_crawled": extra_info.get("pages_crawled", 0),
            "total_media_found": extra_info.get("total_media_found", 0),
            "css_files_crawled": extra_info.get("css_files_crawled", 0),
        },
        "completed_files": [
            {
                "filename": d["filename"],
                "url": d["url"],
                "size_bytes": d.get("file_size", 0),
                "filepath": d.get("filepath"),
            }
            for d in completed_dl
        ],
        "failed_files": [
            {
                "filename": d["filename"],
                "url": d["url"],
                "error": d.get("error_msg", "unknown"),
            }
            for d in failed_dl
        ],
        "error_msg": task.get("error_msg"),
    }


# ── Direct mode (bypasses engine, uses Playwright + Downloader directly) ────

class DirectScrapeRequest(BaseModel):
    """Direct scrape: render with Playwright + download immediately."""
    url: str = Field(..., description="Target URL")
    output_dir: str = Field(default="./downloads")
    max_scrolls: int = Field(default=3, ge=0, le=20)
    timeout: int = Field(default=20, ge=5, le=60)
    concurrency: int = Field(default=10, ge=1, le=50)
    proxy: Optional[str] = None
    file_types: Optional[list[str]] = Field(
        default=None,
        description="File extensions to filter (e.g. ['jpg','mp4']). None = all"
    )


@router.post("/direct")
async def hermes_direct_scrape(req: DirectScrapeRequest):
    """Direct scrape: Playwright render → collect URLs → download immediately.

    Bypasses the engine entirely for reliable execution.
    Returns results synchronously.
    """
    from scraper.browser import render_page
    from scraper.extractor import extract_media_urls, canonicalize_url
    from scraper.downloader import Downloader
    import asyncio as _aio

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36"
    }

    # Phase 1: Render with Playwright
    result = await render_page(
        req.url, headers=headers, timeout=req.timeout, proxy=req.proxy,
        scroll=req.max_scrolls > 0, max_scrolls=req.max_scrolls,
        scroll_delay=1.0, wait_after_load=2.0,
    )

    # Phase 2: Collect all URLs
    network_urls = result.get("network_urls", set())
    html = result.get("html", "")
    html_urls = set(extract_media_urls(html, req.url)) if html else set()
    all_urls = network_urls | html_urls

    # Filter by file types
    if req.file_types:
        exts = tuple(f".{e.lstrip('.')}" for e in req.file_types)
        all_urls = {u for u in all_urls
                    if any(u.lower().split('?')[0].split('#')[0].endswith(e)
                           for e in exts)}

    # Deduplicate
    seen = set()
    unique = []
    for u in all_urls:
        c = canonicalize_url(u)
        if c not in seen:
            seen.add(c)
            unique.append(u)

    if not unique:
        return {
            "url": req.url,
            "status": "completed",
            "media_found": 0,
            "completed": 0,
            "failed": 0,
            "files": [],
            "message": "No media URLs found. Try use_browser=true or increase max_scrolls.",
        }

    # Phase 3: Download all
    dl = Downloader(output_dir=req.output_dir)
    sem = _aio.Semaphore(req.concurrency)
    completed = []
    failed = []

    async def _download(url):
        async with sem:
            try:
                r = await dl.download_file(
                    url, output_dir=req.output_dir, timeout=req.timeout,
                    proxy=proxy, headers=headers)
                if r["status"] == "completed":
                    completed.append({
                        "filename": r["filename"],
                        "url": url,
                        "size_bytes": r.get("file_size", 0),
                        "filepath": r.get("filepath"),
                    })
                else:
                    failed.append({"url": url, "error": r.get("error_msg", "unknown")})
            except Exception as e:
                failed.append({"url": url, "error": str(e)})

    proxy = req.proxy
    await _aio.gather(*[_download(u) for u in unique], return_exceptions=True)

    return {
        "url": req.url,
        "status": "completed",
        "media_found": len(unique),
        "completed": len(completed),
        "failed": len(failed),
        "total_size_bytes": sum(f.get("size_bytes", 0) for f in completed),
        "output_dir": req.output_dir,
        "files": completed,
        "errors": failed if failed else None,
    }
