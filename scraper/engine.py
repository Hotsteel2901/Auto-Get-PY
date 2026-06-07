import asyncio
import json
import logging
import random
import shutil
import time
import aiohttp
from pathlib import Path
from urllib.parse import urlparse
from scraper.extractor import (
    extract_media_urls, MEDIA_EXTENSIONS,
    find_next_page_url, extract_page_links, extract_iframe_urls,
    extract_css_urls, extract_inline_base64_images,
    find_meta_refresh_url, extract_noscript_template_urls,
    detect_encoding, guess_extension_from_content_type,
)
from scraper.decryptors import run_pipeline
from scraper.downloader import Downloader
from scraper.site_crawler import discover_site

logger = logging.getLogger(__name__)

_BINARY_CONTENT_TYPES = {
    "application/octet-stream", "application/pdf", "application/zip",
    "application/x-rar-compressed", "application/x-7z-compressed",
    "application/x-tar", "application/gzip", "application/x-bzip2",
    "application/x-xz", "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/epub+zip",
}
_BINARY_CONTENT_PREFIXES = ("video/", "audio/", "image/", "font/")

# ── User-Agent rotation pool ────────────────────────────────────────────────

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.2 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:133.0) Gecko/20100101 Firefox/133.0",
]


def _get_ua(config: dict) -> str:
    """Get User-Agent: use custom if set, else random from pool."""
    custom_ua = config.get("custom_headers", {}).get("User-Agent")
    if custom_ua:
        return custom_ua
    return random.choice(_USER_AGENTS)


def _build_headers(config: dict, referer: str = None) -> dict:
    """Build request headers with UA rotation and optional referer."""
    headers = config.get("custom_headers", {}).copy()
    if "User-Agent" not in headers:
        headers["User-Agent"] = _get_ua(headers)
    if referer:
        headers.setdefault("Referer", referer)
    headers.setdefault("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8")
    headers.setdefault("Accept-Language", "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7")
    return headers


def _check_disk_space(path: str, min_mb: int = 100) -> bool:
    """Check if there's enough disk space."""
    try:
        usage = shutil.disk_usage(path)
        free_mb = usage.free / (1024 * 1024)
        return free_mb > min_mb
    except Exception:
        return True  # can't check, assume OK


class ScraperEngine:
    def __init__(self, task_id: int, semaphore: asyncio.Semaphore,
                 pause_event: asyncio.Event, progress_cb=None):
        self.task_id = task_id
        self._semaphore = semaphore
        self._pause_event = pause_event
        self._progress_cb = progress_cb
        self._downloader = Downloader()
        self._visited_pages: set[str] = set()
        self._all_media_urls: set[str] = set()
        self._css_files_crawled: set[str] = set()
        self._cookie_jar: dict = {}  # domain -> cookies

    # ── Download with retry + 429 handling ──

    async def _download_item(self, dl, output_dir, headers, timeout, max_retries,
                             request_delay, proxy=None, max_file_size_mb=None):
        from db import queries as q

        async with self._semaphore:
            await self._pause_event.wait()
            await asyncio.sleep(request_delay)

            retries = 0
            while True:
                await q.update_download(dl["id"], status="downloading")

                try:
                    resume_from = Path(output_dir, dl["filename"]).stat().st_size
                except FileNotFoundError:
                    resume_from = 0

                # Disk space check before each download
                if not _check_disk_space(output_dir):
                    return {"status": "failed", "error_msg": "Disk space critically low"}

                # Rotate UA per request
                req_headers = _build_headers({"custom_headers": headers})

                dl_result = await self._downloader.download_file(
                    url=dl["url"],
                    output_dir=output_dir,
                    filename=dl["filename"],
                    task_id=self.task_id,
                    dl_id=dl["id"],
                    progress_callback=self._on_progress,
                    headers=req_headers,
                    timeout=timeout,
                    resume_from=resume_from,
                    proxy=proxy,
                    max_file_size_mb=max_file_size_mb,
                )

                if dl_result["status"] == "completed":
                    await q.update_download(dl["id"], status="completed",
                                            file_size=dl_result["file_size"])
                    return dl_result

                # Handle 429 Too Many Requests with smart backoff
                error_msg = dl_result.get("error_msg", "")
                if "429" in error_msg:
                    wait = 30 + random.uniform(5, 15)
                    logger.warning("Rate limited (429) on %s, waiting %.0fs", dl["url"], wait)
                    await asyncio.sleep(wait)
                    retries += 1
                else:
                    retries += 1

                if retries < max_retries:
                    backoff = min(2 ** retries, 60) + random.uniform(0, 2)
                    await q.update_download(dl["id"], status="pending",
                                            retry_count=retries,
                                            error_msg=error_msg)
                    await asyncio.sleep(backoff)
                else:
                    await q.update_download(dl["id"], status="failed",
                                            error_msg=error_msg)
                    return dl_result

    # ── Page fetching with retry + anti-crawl ──

    async def _fetch_page(self, url: str, headers: dict, timeout: int,
                          proxy: str = None) -> tuple[str | None, bool, str | None]:
        """Fetch a page. Returns (html, is_direct_file, error)."""
        for attempt in range(3):
            try:
                # Rotate UA on each attempt
                actual_headers = headers.copy() if headers else {}
                if "User-Agent" not in actual_headers:
                    actual_headers["User-Agent"] = _get_ua({})

                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        url, headers=actual_headers,
                        timeout=aiohttp.ClientTimeout(total=timeout),
                        proxy=proxy,
                        allow_redirects=True,
                    ) as resp:
                        if resp.status == 429:
                            wait = 30 + random.uniform(5, 15)
                            logger.warning("429 on %s, waiting %.0fs", url, wait)
                            await asyncio.sleep(wait)
                            continue

                        if resp.status == 403:
                            # Try with different UA
                            actual_headers["User-Agent"] = random.choice(_USER_AGENTS)
                            continue

                        if resp.status not in (200, 301, 302):
                            return (None, False, f"HTTP {resp.status}")

                        content_type = resp.headers.get('Content-Type', '').lower()
                        content_disposition = resp.headers.get('Content-Disposition', '')
                        parsed_path = urlparse(url).path.lower()

                        is_file = (
                            any(ct in content_type for ct in _BINARY_CONTENT_TYPES) or
                            any(content_type.startswith(prefix) for prefix in _BINARY_CONTENT_PREFIXES) or
                            'attachment' in content_disposition or
                            any(parsed_path.endswith(ext) for ext in MEDIA_EXTENSIONS)
                        )
                        if is_file:
                            return (None, True, None)

                        # Detect encoding properly (supports Chinese sites)
                        raw_body = await resp.read()
                        encoding = detect_encoding(dict(resp.headers), raw_body)
                        try:
                            text = raw_body.decode(encoding, errors='replace')
                        except (LookupError, UnicodeDecodeError):
                            text = raw_body.decode('utf-8', errors='replace')
                        return (text, False, None)
            except Exception as e:
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)
                    continue
                logger.warning("Failed to fetch %s: %s", url, e)
                return (None, False, str(e))

    # ── CSS file crawling ──

    async def _crawl_css_file(self, css_url: str, config: dict,
                               headers: dict, timeout: int, proxy: str = None):
        """Fetch a CSS file and extract media URLs + nested @import CSS."""
        if css_url in self._css_files_crawled:
            return
        self._css_files_crawled.add(css_url)

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    css_url, headers=headers,
                    timeout=aiohttp.ClientTimeout(total=timeout),
                    proxy=proxy,
                ) as resp:
                    if resp.status != 200:
                        return
                    ct = resp.headers.get('content-type', '').lower()
                    if 'css' not in ct and 'text' not in ct:
                        return
                    css_text = await resp.text()
        except Exception:
            return

        media_urls, import_urls = extract_css_urls(css_text, css_url)
        include_filters = config.get("url_filters", {}).get("include")
        exclude_filters = config.get("url_filters", {}).get("exclude")

        for url in media_urls:
            if include_filters and not any(
                fnmatch(urlparse(url).path.lower(), f.lower()) for f in include_filters
            ):
                continue
            if exclude_filters and any(
                fnmatch(urlparse(url).path.lower(), f.lower()) for f in exclude_filters
            ):
                continue
            self._all_media_urls.add(url)

        # Recurse into @import CSS files
        for import_url in import_urls[:5]:  # limit depth
            await self._crawl_css_file(import_url, config, headers, timeout, proxy)

    # ── Core crawl logic ──

    async def _crawl_page(self, url: str, config: dict, depth: int,
                          headers: dict, timeout: int, proxy: str = None) -> None:
        """Recursively crawl a page: extract media URLs + follow links/pages."""
        if url in self._visited_pages:
            return
        if depth > config.get("crawl_depth", 0):
            return
        if len(self._all_media_urls) >= config.get("max_pages", 200):
            return

        self._visited_pages.add(url)
        logger.info("[Crawl depth=%d] Fetching %s", depth, url)

        # Build headers with referer chain
        req_headers = _build_headers(config, referer=url if depth > 0 else None)

        page_html, is_direct_file, fetch_error = await self._fetch_page(
            url, req_headers, timeout, proxy)

        if is_direct_file:
            self._all_media_urls.add(url)
            return

        if page_html is None:
            logger.warning("Skipping %s: %s", url, fetch_error)
            return

        # Decryptors
        decryptors_enabled = config.get("decryptors", [])
        decryptor_opts = config.get("decryptor_opts", {})
        if decryptors_enabled and page_html:
            result = await run_pipeline(
                page_html.encode("utf-8"),
                decryptors_enabled,
                decryptor_opts,
                max_passes=3,
            )
            page_html = result.data.decode("utf-8", errors="ignore")

        # Extract media URLs
        include_filters = config.get("url_filters", {}).get("include")
        exclude_filters = config.get("url_filters", {}).get("exclude")
        media_urls = extract_media_urls(page_html, url, include_filters, exclude_filters)
        self._all_media_urls.update(media_urls)

        # Also extract from <noscript> and <template> tags (Pinterest/Instagram pattern)
        ns_urls = extract_noscript_template_urls(page_html, url)
        if ns_urls:
            self._all_media_urls.update(ns_urls)
            logger.info("[depth=%d] Found %d noscript/template URLs", depth, len(ns_urls))

        # Follow meta refresh redirects
        refresh_url = find_meta_refresh_url(page_html, url)
        if refresh_url and refresh_url not in self._visited_pages:
            logger.info("[depth=%d] Following meta refresh → %s", depth, refresh_url)
            await self._crawl_page(refresh_url, config, depth, req_headers, timeout, proxy)

        # Crawl linked CSS files for hidden URLs
        if config.get("crawl_css", True):
            from scraper.extractor import CSS_IMPORT_PATTERN
            for match in re.finditer(r'(?i)href\s*=\s*["\']([^"\']+\.css[^"\']*)["\']', page_html):
                css_url = match.group(1)
                if not css_url.startswith('http'):
                    css_url = urljoin(url, css_url)
                if css_url not in self._css_files_crawled:
                    await self._crawl_css_file(css_url, config, req_headers, timeout, proxy)

        # Crawl iframes
        if config.get("crawl_iframes", True):
            iframe_urls = extract_iframe_urls(page_html, url)
            for iframe_url in iframe_urls[:5]:
                if iframe_url not in self._visited_pages:
                    await self._crawl_page(iframe_url, config, depth + 1,
                                           req_headers, timeout, proxy)

        logger.info("[depth=%d] Found %d media URLs on %s (total: %d)",
                     depth, len(media_urls), url, len(self._all_media_urls))

        # Discover more pages
        if depth < config.get("crawl_depth", 0) and len(self._all_media_urls) < config.get("max_pages", 200):
            follow_tasks = []

            # Auto-pagination
            if config.get("follow_pagination", True):
                next_url = find_next_page_url(page_html, url)
                if next_url and next_url not in self._visited_pages:
                    follow_tasks.append(
                        self._crawl_page(next_url, config, depth + 1, req_headers, timeout, proxy)
                    )

            # Link following
            if config.get("follow_links", False):
                allowed_paths = config.get("allowed_paths", None)
                page_links = extract_page_links(
                    page_html, url, same_domain=True, allowed_paths=allowed_paths)
                max_links = config.get("max_links_per_page", 10)
                for link in page_links[:max_links]:
                    if link not in self._visited_pages:
                        follow_tasks.append(
                            self._crawl_page(link, config, depth + 1, req_headers, timeout, proxy)
                        )

            if follow_tasks:
                await asyncio.gather(*follow_tasks, return_exceptions=True)

    # ── Browser-enhanced crawl ──

    async def _crawl_with_browser(self, url: str, config: dict,
                                   headers: dict, timeout: int,
                                   proxy: str = None) -> None:
        """Use Playwright to render JS-heavy pages and capture network media."""
        try:
            from scraper.browser import render_page
        except RuntimeError as e:
            logger.warning("Browser rendering unavailable: %s", e)
            return

        logger.info("[Browser] Rendering %s", url)
        result = await render_page(
            url, headers=headers, timeout=timeout, proxy=proxy,
            scroll=config.get("scroll_page", True),
            max_scrolls=config.get("max_scrolls", 30),
            scroll_delay=config.get("scroll_delay", 1.5),
        )

        # Add network-captured media URLs
        network_urls = result.get("network_urls", set())
        self._all_media_urls.update(network_urls)
        logger.info("[Browser] Captured %d network media URLs", len(network_urls))

        # Also extract from rendered HTML
        html = result.get("html", "")
        if html:
            include_filters = config.get("url_filters", {}).get("include")
            exclude_filters = config.get("url_filters", {}).get("exclude")
            media_urls = extract_media_urls(html, url, include_filters, exclude_filters)
            self._all_media_urls.update(media_urls)

            # Crawl links from rendered page too
            if config.get("follow_links", False):
                allowed_paths = config.get("allowed_paths", None)
                page_links = extract_page_links(
                    html, url, same_domain=True, allowed_paths=allowed_paths)
                max_links = config.get("max_links_per_page", 10)
                for link in page_links[:max_links]:
                    if link not in self._visited_pages:
                        self._visited_pages.add(link)
                        # Render each linked page too
                        link_result = await render_page(
                            link, headers=headers, timeout=timeout, proxy=proxy,
                            scroll=True, max_scrolls=10,
                        )
                        link_html = link_result.get("html", "")
                        if link_html:
                            link_media = extract_media_urls(
                                link_html, link, include_filters, exclude_filters)
                            self._all_media_urls.update(link_media)
                        self._all_media_urls.update(link_result.get("network_urls", set()))

    # ── Main run ──

    async def run(self):
        from db import queries as q
        import re as _re  # for CSS href matching

        task = await q.get_task(self.task_id)
        if not task:
            return
        config = json.loads(task["config"]) if task["config"] else {}
        concurrency = config.get("concurrency", 5)
        request_delay = config.get("request_delay_sec", 0.5)
        timeout = config.get("request_timeout_sec", 30)
        max_retries = config.get("max_retries", 3)
        output_dir = config.get("output_dir", "./downloads")
        headers = _build_headers(config)
        proxy = config.get("proxy", None)
        max_file_size_mb = config.get("max_file_size_mb", None)
        crawl_depth = config.get("crawl_depth", 0)
        max_pages = config.get("max_pages", 200)
        use_browser = config.get("use_browser", False)
        use_site_discovery = config.get("site_discovery", False)

        # Ensure output dir exists
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        # ── Phase 1: Site discovery (sitemap, robots, feeds) ──
        if use_site_discovery:
            logger.info("Starting site discovery for %s", task["url"])
            discovery = await discover_site(
                task["url"], headers=headers, timeout=timeout, proxy=proxy)
            # Add all discovered media URLs from feeds
            self._all_media_urls.update(discovery.get("feed_media_urls", []))
            # Add sitemap URLs and feed page URLs to the crawl queue
            sitemap_pages = discovery.get("sitemap_urls", [])
            feed_pages = discovery.get("feed_page_urls", [])
            all_discovered_pages = sitemap_pages + feed_pages
            logger.info("Site discovery found %d pages to crawl", len(all_discovered_pages))

            # Crawl discovered pages
            include_filters = config.get("url_filters", {}).get("include")
            exclude_filters = config.get("url_filters", {}).get("exclude")

            for page_url in all_discovered_pages[:max_pages]:
                if page_url in self._visited_pages:
                    continue
                if len(self._all_media_urls) >= max_pages:
                    break
                self._visited_pages.add(page_url)

                # Check if it's a direct media file
                parsed_path = urlparse(page_url).path.lower()
                if any(parsed_path.endswith(ext) for ext in MEDIA_EXTENSIONS):
                    self._all_media_urls.add(page_url)
                    continue

                if use_browser:
                    await self._crawl_with_browser(
                        page_url, config, headers, timeout, proxy)
                else:
                    await self._crawl_page(
                        page_url, config, depth=0, headers=headers,
                        timeout=timeout, proxy=proxy)

            logger.info("After site discovery crawl: %d media URLs found",
                        len(self._all_media_urls))

        # ── Phase 2: Crawl starting URL ──
        use_crawling = (
            crawl_depth > 0
            or config.get("follow_links", False)
            or config.get("follow_pagination", True)
            or use_site_discovery
        )

        if use_browser and not use_site_discovery:
            # Browser mode for JS-heavy sites
            await self._crawl_with_browser(
                task["url"], config, headers, timeout, proxy)
            all_urls = list(self._all_media_urls)
        elif use_crawling and not use_site_discovery:
            # Standard multi-page crawl
            await self._crawl_page(
                task["url"], config, depth=0, headers=headers,
                timeout=timeout, proxy=proxy)
            all_urls = list(self._all_media_urls)
        else:
            # Single page or already crawled via site_discovery
            if not self._all_media_urls:
                page_html, is_direct_file, fetch_error = await self._fetch_page(
                    task["url"], headers, timeout, proxy)
                if is_direct_file:
                    all_urls = [task["url"]]
                elif page_html is None:
                    await q.update_task(self.task_id, status="failed",
                                        error_msg=fetch_error or "Failed to fetch page")
                    return
                else:
                    decryptors_enabled = config.get("decryptors", [])
                    decryptor_opts = config.get("decryptor_opts", {})
                    if decryptors_enabled and page_html:
                        result = await run_pipeline(
                            page_html.encode("utf-8"), decryptors_enabled,
                            decryptor_opts, max_passes=3)
                        page_html = result.data.decode("utf-8", errors="ignore")

                    include_filters = config.get("url_filters", {}).get("include")
                    exclude_filters = config.get("url_filters", {}).get("exclude")
                    all_urls = extract_media_urls(
                        page_html, task["url"], include_filters, exclude_filters)
            else:
                all_urls = list(self._all_media_urls)

        # ── Phase 3: Extract inline base64 images ──
        if config.get("extract_base64", False) and page_html:
            b64_results = extract_inline_base64_images(page_html, output_dir)
            if b64_results:
                logger.info("Extracted %d inline base64 images", len(b64_results))

        # ── Phase 4: Deduplicate URLs ──
        # Normalize and deduplicate
        seen_normalized = set()
        unique_urls = []
        for url in all_urls:
            # Normalize: remove trailing slash, lowercase domain, strip tracking params
            parsed = urlparse(url)
            normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip('/')
            if normalized not in seen_normalized:
                seen_normalized.add(normalized)
                unique_urls.append(url)
        all_urls = unique_urls

        logger.info("Total unique media URLs to download: %d (crawled %d pages)",
                    len(all_urls), len(self._visited_pages))

        # ── Phase 5: Create download records ──
        if not all_urls:
            await q.update_task(self.task_id, status="completed", total_files=0, done_files=0)
            return

        existing_urls = await q.get_existing_download_urls(self.task_id)
        new_urls = [url for url in all_urls if url not in existing_urls]
        for url in new_urls:
            filename = Downloader.extract_filename(url)
            await q.create_download(self.task_id, url, filename)

        all_downloads = await q.list_downloads(self.task_id)
        total = len(all_downloads)
        downloads = [d for d in all_downloads if d["status"] != "completed"]

        if not downloads:
            completed = await q.count_downloads_by_status(self.task_id, "completed")
            await q.update_task(self.task_id, status="completed", done_files=completed)
            return

        await q.update_task(self.task_id, total_files=total,
                            extra_info=json.dumps({
                                "pages_crawled": len(self._visited_pages),
                                "total_media_found": len(all_urls),
                                "css_files_crawled": len(self._css_files_crawled),
                            }))

        # ── Phase 6: Download all ──
        done_count = 0
        start_time = time.time()
        logger.info("[Task %d] Starting download phase: %d items", self.task_id, len(downloads))

        async def download_one(dl):
            nonlocal done_count
            try:
                result = await self._download_item(
                    dl, output_dir, headers, timeout, max_retries, request_delay,
                    proxy=proxy, max_file_size_mb=max_file_size_mb)
                done_count += 1
                elapsed = time.time() - start_time
                speed = done_count / elapsed if elapsed > 0 else 0
                if self._progress_cb:
                    await self._progress_cb(self.task_id, done_count, total, dl["filename"], speed)
            except Exception as e:
                logger.exception("Unexpected error downloading %s: %s", dl["url"], e)
                done_count += 1

        # Download in batches to avoid semaphore deadlock
        batch_size = concurrency
        for i in range(0, len(downloads), batch_size):
            batch = downloads[i:i + batch_size]
            batch_tasks = [download_one(dl) for dl in batch]
            await asyncio.gather(*batch_tasks, return_exceptions=True)

        await self._pause_event.wait()
        completed = await q.count_downloads_by_status(self.task_id, "completed")
        failed_count = await q.count_downloads_by_status(self.task_id, "failed")
        if failed_count == total:
            await q.update_task(self.task_id, status="failed", error_msg="All downloads failed")
        else:
            await q.update_task(self.task_id, status="completed", done_files=completed)

    async def _on_progress(self, task_id, dl_id, downloaded, total):
        from db import queries as q
        await q.update_download(dl_id, downloaded=downloaded, file_size=total)
