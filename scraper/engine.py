"""Scrape orchestration: crawl pages, discover media, download it.

The engine runs in two phases.

**Discovery** — a bounded pool of workers pulls URLs off a queue, fetches each
page, extracts media URLs using every strategy in :mod:`scraper.extractor`,
then feeds pagination, ``<a href>`` links, stylesheets and iframes back into the
queue.  A single :class:`aiohttp.ClientSession` is shared for the whole task so
cookies and connection reuse work exactly as they would in a browser, which is
what makes cookie-gated and hotlink-protected sites downloadable.

**Transfer** — discovered URLs become database rows, then a second worker pool
downloads them concurrently with retries, resume support and playlist merging.

Every discovered URL remembers the page that referenced it, so media requests
carry the correct ``Referer`` (many CDNs reject requests without one).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urljoin, urlparse

import aiohttp

from scraper.decryptors import run_pipeline
from scraper.downloader import Downloader
from scraper.extractor import (
    MEDIA_EXTENSIONS,
    canonicalize_url,
    decode_body,
    extract_css_urls,
    extract_iframe_urls,
    extract_media_urls,
    extract_noscript_template_urls,
    extract_page_links,
    find_meta_refresh_url,
    find_next_page_url,
)
from scraper.site_crawler import discover_site

logger = logging.getLogger(__name__)

_BINARY_CONTENT_TYPES = frozenset({
    "application/octet-stream", "application/pdf", "application/zip",
    "application/x-rar-compressed", "application/vnd.rar",
    "application/x-7z-compressed", "application/x-tar", "application/gzip",
    "application/x-bzip2", "application/x-xz", "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/epub+zip", "application/vnd.apple.mpegurl", "application/x-mpegurl",
    "application/dash+xml", "font/woff", "font/woff2", "font/ttf", "font/otf",
    "application/font-woff", "application/font-woff2",
})
_BINARY_CONTENT_PREFIXES = ("video/", "audio/", "image/", "font/")

# Rotation pool used when the caller has not pinned a User-Agent.
_USER_AGENTS = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/18.2 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0",
)

DEFAULT_HEADERS = {
    "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
               "image/webp,image/apng,*/*;q=0.8"),
    "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
}


def build_headers(config: dict | "CrawlConfig", referer: str | None = None) -> dict:
    """Compose request headers: caller overrides, then UA, then defaults.

    Accepts either a raw config dict or a :class:`CrawlConfig`, because both
    shapes reach this function.
    """
    if isinstance(config, CrawlConfig):
        custom = dict(config.custom_headers)
    else:
        custom = dict(config.get("custom_headers") or {})

    headers = dict(DEFAULT_HEADERS)
    headers.update(custom)
    if not any(key.lower() == "user-agent" for key in headers):
        headers["User-Agent"] = random.choice(_USER_AGENTS)
    if referer:
        headers.setdefault("Referer", referer)
    return headers


@dataclass
class CrawlConfig:
    """Validated task configuration with sensible defaults everywhere."""

    start_url: str
    output_dir: str = "./downloads"
    concurrency: int = 5
    crawl_concurrency: int = 8
    request_delay_sec: float = 0.5
    request_timeout_sec: int = 30
    max_retries: int = 3
    max_file_size_mb: int | None = 500
    proxy: str | None = None
    crawl_depth: int = 0
    max_pages: int = 500
    max_media: int = 20000
    max_links_per_page: int = 20
    follow_links: bool = False
    follow_pagination: bool = True
    crawl_css: bool = True
    crawl_iframes: bool = True
    use_browser: bool = False
    site_discovery: bool = False
    extract_base64: bool = False
    probe_links: bool = False
    scroll_page: bool = True
    max_scrolls: int = 30
    scroll_delay: float = 1.5
    allowed_paths: list[str] = field(default_factory=list)
    include_filters: list[str] = field(default_factory=list)
    exclude_filters: list[str] = field(default_factory=list)
    decryptors: list[str] = field(default_factory=list)
    decryptor_opts: dict = field(default_factory=dict)
    custom_headers: dict = field(default_factory=dict)
    time_budget_sec: float = 0.0

    @classmethod
    def from_dict(cls, url: str, config: dict | None) -> "CrawlConfig":
        raw = dict(config or {})
        filters = raw.get("url_filters") or {}

        def _int(key, default, low=0, high=None):
            try:
                value = int(raw.get(key, default))
            except (TypeError, ValueError):
                value = default
            value = max(low, value)
            return min(high, value) if high is not None else value

        def _float(key, default, low=0.0):
            try:
                value = float(raw.get(key, default))
            except (TypeError, ValueError):
                value = default
            return max(low, value)

        max_size = raw.get("max_file_size_mb", 500)
        try:
            max_size = int(max_size)
        except (TypeError, ValueError):
            max_size = 500

        return cls(
            start_url=url,
            output_dir=str(raw.get("output_dir") or "./downloads"),
            concurrency=_int("concurrency", 5, 1, 50),
            crawl_concurrency=_int("crawl_concurrency", 8, 1, 32),
            request_delay_sec=_float("request_delay_sec", 0.5),
            request_timeout_sec=_int("request_timeout_sec", 30, 3, 600),
            max_retries=_int("max_retries", 3, 0, 10),
            max_file_size_mb=max_size if max_size > 0 else None,
            proxy=raw.get("proxy") or None,
            crawl_depth=_int("crawl_depth", 0, 0, 50),
            max_pages=_int("max_pages", 500, 1, 500000),
            max_media=_int("max_media", 20000, 1, 500000),
            max_links_per_page=_int("max_links_per_page", 20, 1, 500),
            follow_links=bool(raw.get("follow_links", False)),
            follow_pagination=bool(raw.get("follow_pagination", True)),
            crawl_css=bool(raw.get("crawl_css", True)),
            crawl_iframes=bool(raw.get("crawl_iframes", True)),
            use_browser=bool(raw.get("use_browser", False)),
            site_discovery=bool(raw.get("site_discovery", False)),
            extract_base64=bool(raw.get("extract_base64", False)),
            probe_links=bool(raw.get("probe_links", False)),
            scroll_page=bool(raw.get("scroll_page", True)),
            max_scrolls=_int("max_scrolls", 30, 0, 500),
            scroll_delay=_float("scroll_delay", 1.5, 0.0),
            allowed_paths=list(raw.get("allowed_paths") or []),
            include_filters=list(filters.get("include") or []),
            exclude_filters=list(filters.get("exclude") or []),
            decryptors=list(raw.get("decryptors") or []),
            decryptor_opts=dict(raw.get("decryptor_opts") or {}),
            custom_headers=dict(raw.get("custom_headers") or {}),
            time_budget_sec=_float("time_budget_sec", 0.0),
        )


class ScraperEngine:
    """Runs one task: discovery followed by transfer."""

    def __init__(self, task_id: int, semaphore: asyncio.Semaphore,
                 pause_event: asyncio.Event, progress_cb=None,
                 file_progress_cb=None):
        self.task_id = task_id
        self._global_sem = semaphore
        self._pause_event = pause_event
        self._progress_cb = progress_cb
        self._file_progress_cb = file_progress_cb

        self.session: aiohttp.ClientSession | None = None
        self._downloader: Downloader | None = None

        # url -> the page that referenced it (used as Referer)
        self._media: dict[str, str | None] = {}
        self._visited: set[str] = set()
        self._css_seen: set[str] = set()
        self._probed: set[str] = set()
        self._pages_fetched = 0
        self._cancelled = False

        # Transfer bookkeeping
        self._done_count = 0
        self._total_count = 0
        self._started_at = time.monotonic()
        self._progress_lock = asyncio.Lock()

        # Discovery limits, filled in from the task config by `run()`.
        self._include_filters: list[str] = []
        self._exclude_filters: list[str] = []
        self._max_media = 100000

    # ── Public entry point ──────────────────────────────────────────────────

    def cancel(self) -> None:
        self._cancelled = True
        self._pause_event.set()

    def _bind_config(self, config: CrawlConfig) -> None:
        """Copy the discovery limits the registry and filters depend on."""
        self._include_filters = config.include_filters
        self._exclude_filters = config.exclude_filters
        self._max_media = config.max_media

    @property
    def discovered_urls(self) -> list[str]:
        """Media URLs found so far, in discovery order."""
        return list(self._media.keys())

    @property
    def pages_fetched(self) -> int:
        return self._pages_fetched

    async def discover(self, config: CrawlConfig) -> None:
        """Run only the discovery phase, writing nothing to disk.

        Used by the preview endpoints, which must honour the same URL filters
        and budgets as a real run.
        """
        self._bind_config(config)
        self._downloader = Downloader(config.output_dir)
        self.session = Downloader.create_session()
        try:
            await self._discovery_phase(config)
            self._register_failed_start_url(config)
        finally:
            await self.session.close()
            self.session = None

    async def run(self) -> None:
        from db import queries as q

        task = await q.get_task(self.task_id)
        if not task:
            logger.warning("Task %s disappeared before it started", self.task_id)
            return

        config = CrawlConfig.from_dict(task["url"], task.get("config_parsed") or {})
        output_dir = Path(config.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        self._bind_config(config)
        self._downloader = Downloader(str(output_dir))
        self.session = Downloader.create_session()

        started = time.monotonic()
        try:
            await self._discovery_phase(config)
            self._register_failed_start_url(config)
            await self._transfer_phase(config)
        finally:
            await self.session.close()
            self.session = None

        elapsed = time.monotonic() - started
        logger.info("[Task %d] finished in %.1fs (%d pages, %d media)",
                    self.task_id, elapsed, self._pages_fetched, len(self._media))

    # ── Phase 1: discovery ──────────────────────────────────────────────────

    async def _discovery_phase(self, config: CrawlConfig) -> None:
        if config.crawl_css or config.crawl_iframes or config.follow_links \
                or config.follow_pagination or config.crawl_depth > 0 \
                or config.use_browser or config.site_discovery:
            await self._crawl(config)
        else:
            await self._single_page(config)

    def _register_failed_start_url(self, config: CrawlConfig) -> None:
        """If the target itself is a media file that would not load, keep it.

        Otherwise a mistyped or protected file URL produces an empty, silent
        task instead of a download record explaining what went wrong.
        """
        if self._media or self._cancelled:
            return
        parsed = urlparse(config.start_url)
        if any(parsed.path.lower().endswith(ext) for ext in MEDIA_EXTENSIONS):
            self._register_media([config.start_url], None)

    async def _single_page(self, config: CrawlConfig) -> None:
        """Fetch exactly one URL and extract from it."""
        html, final_url, error = await self._fetch(config, config.start_url, None)
        if error:
            from db import queries as q

            await q.update_task(self.task_id, status="failed",
                                error_msg=f"Failed to fetch page: {error}")
            return

        if final_url in self._media:
            return  # it was a direct media file

        self._pages_fetched = 1
        page_url = final_url or config.start_url
        html = await self._apply_decryptors(html, config)

        media = extract_media_urls(html, page_url,
                                   config.include_filters, config.exclude_filters)
        self._register_media(media, page_url)
        self._register_media(extract_noscript_template_urls(html, page_url), page_url)

        if config.extract_base64:
            from scraper.extractor import extract_inline_base64_images

            saved = extract_inline_base64_images(html, config.output_dir)
            if saved:
                logger.info("[Task %d] extracted %d inline base64 images",
                            self.task_id, len(saved))

    async def _crawl(self, config: CrawlConfig) -> None:
        """Bounded, concurrent crawl starting from ``config.start_url``."""
        queue: asyncio.Queue = asyncio.Queue()
        await queue.put((config.start_url, 0, None))
        self._pages_fetched = 0

        if config.site_discovery:
            await self._seed_from_site_discovery(config, queue)

        workers = [
            asyncio.create_task(self._crawl_worker(queue, config))
            for _ in range(config.crawl_concurrency)
        ]
        try:
            await queue.join()
        finally:
            for worker in workers:
                worker.cancel()
            await asyncio.gather(*workers, return_exceptions=True)

        logger.info("[Task %d] discovery done: %d pages, %d media URLs",
                    self.task_id, self._pages_fetched, len(self._media))

    async def _seed_from_site_discovery(self, config: CrawlConfig,
                                        queue: asyncio.Queue) -> None:
        """Feed sitemap and feed URLs into the crawl queue."""
        try:
            discovery = await discover_site(
                config.start_url, headers=build_headers(config),
                timeout=config.request_timeout_sec, proxy=config.proxy)
        except Exception as exc:  # noqa: BLE001 - discovery is best-effort
            logger.warning("[Task %d] site discovery failed: %s", self.task_id, exc)
            return

        self._register_media(discovery.get("feed_media_urls") or [], None)
        pages = (discovery.get("sitemap_urls") or []) + (discovery.get("feed_page_urls") or [])
        logger.info("[Task %d] site discovery found %d pages", self.task_id, len(pages))

        for page_url in pages:
            if self._pages_fetched >= config.max_pages:
                break
            parsed = urlparse(page_url)
            if any(parsed.path.lower().endswith(ext) for ext in MEDIA_EXTENSIONS):
                self._register_media([page_url], None)
                continue
            if canonicalize_url(page_url) in self._visited:
                continue
            await queue.put((page_url, 0, None))

    async def _crawl_worker(self, queue: asyncio.Queue, config: CrawlConfig) -> None:
        while True:
            url, depth, referer = await queue.get()
            try:
                if self._cancelled:
                    continue
                if not self._claim(url, depth, config):
                    continue
                await self._pause_event.wait()
                if self._cancelled:
                    continue
                await self._visit(url, depth, referer, config, queue)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - one bad page must not kill the crawl
                logger.exception("[Task %d] crawl error on %s", self.task_id, url)
            finally:
                queue.task_done()

    def _claim(self, url: str, depth: int, config: CrawlConfig) -> bool:
        """Reserve the right to crawl ``url``; False when out of budget."""
        if self._cancelled:
            return False
        if depth > config.crawl_depth:
            return False
        if self._pages_fetched >= config.max_pages:
            return False
        if len(self._media) >= config.max_media:
            return False
        key = canonicalize_url(url)
        if key in self._visited:
            return False
        self._visited.add(key)
        self._pages_fetched += 1
        return True

    async def _visit(self, url: str, depth: int, referer: str | None,
                     config: CrawlConfig, queue: asyncio.Queue) -> None:
        if config.request_delay_sec:
            await asyncio.sleep(config.request_delay_sec)

        if config.use_browser:
            handled = await self._visit_with_browser(url, depth, config, queue)
            if handled:
                return

        html, final_url, error = await self._fetch(config, url, referer)
        if error:
            logger.debug("[Task %d] skip %s: %s", self.task_id, url, error)
            return
        if html is None:
            return  # direct media file, already registered

        page_url = final_url or url
        html = await self._apply_decryptors(html, config)

        found = extract_media_urls(html, page_url,
                                   config.include_filters, config.exclude_filters)
        found += extract_noscript_template_urls(html, page_url)
        self._register_media(found, page_url)

        if config.extract_base64:
            from scraper.extractor import extract_inline_base64_images

            extract_inline_base64_images(html, config.output_dir)

        if self._cancelled or len(self._media) >= config.max_media:
            return

        # ── Follow a meta-refresh redirect ──
        refresh = find_meta_refresh_url(html, page_url)
        if refresh:
            await queue.put((refresh, depth, page_url))

        # ── Feed child URLs back into the queue ──
        if self._pages_fetched >= config.max_pages:
            return

        if config.crawl_css:
            for css_url in self._stylesheet_urls(html, page_url):
                await self._crawl_stylesheet(css_url, config, page_url, depth, queue)

        if config.crawl_iframes:
            for iframe_url in extract_iframe_urls(html, page_url)[:5]:
                await queue.put((iframe_url, depth + 1, page_url))

        # Pagination is a sibling chain: it does not consume crawl depth.
        if config.follow_pagination:
            next_url = find_next_page_url(html, page_url, self._visited)
            if next_url:
                logger.debug("[Task %d] pagination → %s", self.task_id, next_url)
                await queue.put((next_url, depth, page_url))

        if config.follow_links and depth < config.crawl_depth:
            links = extract_page_links(
                html, page_url, same_domain=True,
                allowed_paths=config.allowed_paths or None,
                max_links=config.max_links_per_page)
            for link in links:
                await queue.put((link, depth + 1, page_url))

    def _stylesheet_urls(self, html: str, base_url: str) -> list[str]:
        import re

        urls: list[str] = []
        for match in re.finditer(r'(?i)<link\s+[^>]*?href\s*=\s*["\']([^"\']+\.css[^"\']*)["\']',
                                 html):
            resolved = urljoin(base_url, match.group(1))
            if resolved not in self._css_seen:
                urls.append(resolved)
        return urls

    async def _crawl_stylesheet(self, css_url: str, config: CrawlConfig,
                                referer: str, depth: int, queue: asyncio.Queue,
                                _level: int = 0) -> None:
        """Fetch a stylesheet and harvest the assets it references."""
        if css_url in self._css_seen or _level > 3 or self._cancelled:
            return
        if len(self._media) >= config.max_media:
            return
        self._css_seen.add(css_url)

        headers = build_headers(config, referer)
        try:
            async with self.session.get(
                css_url, headers=headers, allow_redirects=True,
                timeout=aiohttp.ClientTimeout(total=config.request_timeout_sec),
            ) as resp:
                if resp.status != 200:
                    return
                content_type = resp.headers.get("Content-Type", "").lower()
                if "css" not in content_type and "text" not in content_type:
                    return
                css_text = (await resp.read()).decode("utf-8", errors="replace")
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return

        media_urls, imports = extract_css_urls(css_text, css_url)
        self._register_media(media_urls, css_url)

        for import_url in imports[:10]:
            await self._crawl_stylesheet(import_url, config, referer, depth, queue,
                                         _level + 1)

    async def _visit_with_browser(self, url: str, depth: int, config: CrawlConfig,
                                  queue: asyncio.Queue) -> bool:
        """Render with Playwright and harvest both DOM and network traffic."""
        try:
            from scraper.browser import render_page
        except ImportError as exc:
            logger.warning("[Task %d] browser rendering unavailable: %s", self.task_id, exc)
            return False

        result = await render_page(
            url, headers=build_headers(config), timeout=config.request_timeout_sec,
            proxy=config.proxy, scroll=config.scroll_page,
            max_scrolls=config.max_scrolls, scroll_delay=config.scroll_delay)

        self._adopt_browser_cookies(result.get("cookies") or [])

        network_urls = result.get("network_urls") or set()
        self._register_media(network_urls, url)

        html = result.get("html") or ""
        if html:
            found = extract_media_urls(html, url, config.include_filters,
                                       config.exclude_filters)
            self._register_media(found, url)

            if config.follow_links and depth < config.crawl_depth:
                for link in extract_page_links(
                        html, url, same_domain=True,
                        allowed_paths=config.allowed_paths or None,
                        max_links=config.max_links_per_page):
                    await queue.put((link, depth + 1, url))
            if config.follow_pagination:
                next_url = find_next_page_url(html, url, self._visited)
                if next_url:
                    await queue.put((next_url, depth, url))
            return True

        if result.get("error"):
            # Rendering failed: let the plain HTTP path have a go.
            return False
        return True

    def _adopt_browser_cookies(self, cookies: list[dict]) -> None:
        """Copy browser cookies into the shared jar so downloads can use them."""
        if not self.session or not cookies:
            return
        jar = self.session.cookie_jar
        for cookie in cookies:
            name, value = cookie.get("name"), cookie.get("value")
            if not name or value is None:
                continue
            domain = (cookie.get("domain") or "").lstrip(".") or "localhost"
            path = cookie.get("path") or "/"
            scheme = "https" if cookie.get("secure") else "http"
            try:
                jar.update_cookies(
                    {name: value},
                    response_url=aiohttp.client.URL(f"{scheme}://{domain}{path}"),
                )
            except Exception:  # noqa: BLE001 - cookie shapes vary wildly
                continue

    # ── Fetching ────────────────────────────────────────────────────────────

    async def _fetch(self, config: CrawlConfig, url: str,
                     referer: str | None) -> tuple[str | None, str | None, str | None]:
        """Fetch a URL.

        Returns ``(html, final_url, error)``.  When the target turns out to be a
        media file, ``html`` is ``None``, the URL is registered, and there is no
        error.
        """
        attempts = max(1, config.max_retries + 1)
        last_error: str | None = None

        for attempt in range(attempts):
            if self._cancelled:
                return None, None, "cancelled"
            headers = build_headers(config, referer)
            try:
                async with self.session.get(
                    url, headers=headers, allow_redirects=True,
                    timeout=aiohttp.ClientTimeout(total=config.request_timeout_sec),
                ) as resp:
                    final_url = str(resp.url)

                    if resp.status == 429:
                        wait = _retry_after(resp)
                        logger.warning("[Task %d] 429 on %s, waiting %ss",
                                       self.task_id, url, wait)
                        await asyncio.sleep(min(wait, 120))
                        last_error = "HTTP 429"
                        continue

                    if resp.status in (403, 401):
                        # Rotate the UA and pretend to arrive from search.
                        last_error = f"HTTP {resp.status}"
                        if attempt + 1 < attempts:
                            await asyncio.sleep(1 + attempt)
                        continue

                    if resp.status >= 400:
                        return None, None, f"HTTP {resp.status}"

                    content_type = (resp.headers.get("Content-Type") or "").lower()
                    disposition = resp.headers.get("Content-Disposition") or ""
                    if self._looks_like_file(final_url, content_type, disposition):
                        # Goes through _register_media so url_filters apply here
                        # too, not just to what the HTML parser found.
                        self._register_media([final_url], referer)
                        return None, final_url, None

                    body = await resp.read()
                    html, _ = decode_body(body, dict(resp.headers))
                    return html, final_url, None

            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                last_error = str(exc) or type(exc).__name__
                if attempt + 1 < attempts:
                    await asyncio.sleep(min(2 ** attempt, 30) + random.uniform(0, 1))
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.exception("[Task %d] fetch failed for %s", self.task_id, url)
                return None, None, str(exc)

        return None, None, last_error or "unknown error"

    @staticmethod
    def _looks_like_file(url: str, content_type: str, disposition: str) -> bool:
        if "attachment" in disposition.lower():
            return True
        mime = content_type.split(";")[0].strip()
        if mime in _BINARY_CONTENT_TYPES:
            return True
        if any(mime.startswith(prefix) for prefix in _BINARY_CONTENT_PREFIXES):
            return True
        path = urlparse(url).path.lower()
        return any(path.endswith(ext) for ext in MEDIA_EXTENSIONS)

    async def _apply_decryptors(self, html: str, config: CrawlConfig) -> str:
        if not html or not config.decryptors:
            return html
        try:
            result = await run_pipeline(
                html.encode("utf-8", errors="replace"), config.decryptors,
                config.decryptor_opts, max_passes=3)
        except Exception as exc:  # noqa: BLE001 - decryptors are user-provided
            logger.warning("[Task %d] decryptor pipeline failed: %s", self.task_id, exc)
            return html
        if not result.success or result.data is None:
            return html
        try:
            return result.data.decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            return html

    # ── Media bookkeeping ───────────────────────────────────────────────────

    def _register_media(self, urls, referer: str | None) -> None:
        """Record discovered assets.

        Filters are applied here rather than at each call site so that every
        discovery route — HTML, CSS, iframes, sitemaps, feeds, browser network
        capture — honours ``url_filters`` identically.
        """
        from scraper.extractor import apply_url_filters

        for url in urls or []:
            if not url:
                continue
            if len(self._media) >= self._max_media:
                return
            if not apply_url_filters([url], self._include_filters,
                                     self._exclude_filters):
                continue
            self._media.setdefault(url, referer)

    # ── Phase 2: transfer ───────────────────────────────────────────────────

    async def _transfer_phase(self, config: CrawlConfig) -> None:
        from db import queries as q

        if self._cancelled:
            return

        if not self._media:
            await q.update_task(self.task_id, status="completed", total_files=0,
                                done_files=0,
                                extra_info={"pages_crawled": self._pages_fetched,
                                            "total_media_found": 0,
                                            "css_files_crawled": len(self._css_seen)})
            return

        existing = await q.get_existing_download_urls(self.task_id)
        used_names = {d.get("filename") for d in
                      await q.list_downloads(self.task_id) if d.get("filename")}
        new_items = []
        for url, referer in self._media.items():
            if url in existing:
                continue
            filename = self._unique_filename(url, used_names)
            used_names.add(filename)
            new_items.append((url, filename, referer))

        if new_items:
            await q.create_downloads_bulk(self.task_id, new_items)

        all_downloads = await q.list_downloads(self.task_id)
        pending = [d for d in all_downloads if d["status"] != "completed"]
        total = len(all_downloads)

        await q.update_task(
            self.task_id, total_files=total,
            done_files=sum(1 for d in all_downloads if d["status"] == "completed"),
            extra_info={"pages_crawled": self._pages_fetched,
                        "total_media_found": len(self._media),
                        "css_files_crawled": len(self._css_seen)})

        if not pending:
            await q.update_task(self.task_id, status="completed")
            return

        logger.info("[Task %d] downloading %d items (concurrency=%d)",
                    self.task_id, len(pending), config.concurrency)

        queue: asyncio.Queue = asyncio.Queue()
        for download in pending:
            queue.put_nowait(download)

        self._done_count = sum(1 for d in all_downloads if d["status"] == "completed")
        self._total_count = total
        self._started_at = time.monotonic()
        self._progress_lock = asyncio.Lock()

        workers = [
            asyncio.create_task(self._download_worker(queue, config))
            for _ in range(config.concurrency)
        ]
        try:
            await queue.join()
        finally:
            for worker in workers:
                worker.cancel()
            await asyncio.gather(*workers, return_exceptions=True)

        stats = await q.get_download_stats(self.task_id)
        if stats["completed"] == 0 and stats["total"] > 0:
            await q.update_task(self.task_id, status="failed",
                                error_msg="All downloads failed",
                                done_files=0)
        elif self._cancelled:
            await q.update_task(self.task_id, status="cancelled",
                                done_files=stats["completed"])
        else:
            await q.update_task(self.task_id, status="completed",
                                done_files=stats["completed"],
                                error_msg=None)

    def _unique_filename(self, url: str, used: set[str]) -> str:
        """Stable, collision-free filename for a URL within this task."""
        base = Downloader.extract_filename(url)
        if base not in used:
            return base
        digest = hashlib.sha1(url.encode("utf-8", "replace")).hexdigest()[:8]
        stem, suffix = Path(base).stem, Path(base).suffix
        candidate = f"{stem}-{digest}{suffix}"
        counter = 1
        while candidate in used:
            candidate = f"{stem}-{digest}-{counter}{suffix}"
            counter += 1
        return candidate

    async def _download_worker(self, queue: asyncio.Queue, config: CrawlConfig) -> None:
        while True:
            download = await queue.get()
            try:
                if self._cancelled:
                    continue
                await self._pause_event.wait()
                if self._cancelled:
                    continue
                await self._download_one(download, config)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.exception("[Task %d] download error for %s",
                                 self.task_id, download.get("url"))
            finally:
                queue.task_done()

    async def _download_one(self, download: dict, config: CrawlConfig) -> None:
        from db import queries as q

        url = download["url"]
        referer = download.get("referer")
        filename = download.get("filename") or Downloader.extract_filename(url)
        out_dir = Path(config.output_dir)
        target = out_dir / filename

        if config.request_delay_sec:
            await asyncio.sleep(config.request_delay_sec)

        async with self._global_sem:
            await self._pause_event.wait()
            if self._cancelled:
                return

            attempt = 0
            while True:
                attempt += 1
                await q.update_download(download["id"], status="downloading",
                                        error_msg=None)

                resume_from = target.stat().st_size if target.exists() else 0
                if resume_from and download.get("file_size") \
                        and resume_from >= download["file_size"]:
                    # Already complete on disk from an earlier run.
                    await q.update_download(
                        download["id"], status="completed", downloaded=resume_from,
                        filepath=str(target))
                    await self._bump_progress(filename)
                    return

                result = await self._downloader.download_file(
                    url=url,
                    output_dir=str(out_dir),
                    filename=filename,
                    dl_id=download["id"],
                    progress_callback=self._on_download_progress,
                    headers=build_headers(config, referer),
                    timeout=config.request_timeout_sec,
                    resume_from=resume_from,
                    proxy=config.proxy,
                    max_file_size_mb=config.max_file_size_mb,
                    session=self.session,
                    referer=referer,
                )

                if result.ok:
                    await q.update_download(
                        download["id"],
                        status="completed",
                        filename=result.get("filename") or filename,
                        filepath=result.get("filepath"),
                        file_size=result.get("file_size") or 0,
                        downloaded=result.get("file_size") or 0,
                        mime_type=result.get("mime_type"),
                        error_msg=None,
                        retry_count=attempt - 1,
                    )
                    await self._bump_progress(result.get("filename") or filename)
                    return

                error = result.get("error_msg") or "unknown error"
                if attempt > config.max_retries:
                    await q.update_download(download["id"], status="failed",
                                            error_msg=error, retry_count=attempt - 1)
                    await self._bump_progress(filename)
                    logger.warning("[Task %d] gave up on %s: %s",
                                   self.task_id, url, error)
                    return

                backoff = result.get("retry_after") or min(2 ** attempt, 60)
                backoff += random.uniform(0, 1.5)
                await q.update_download(download["id"], status="pending",
                                        error_msg=error, retry_count=attempt - 1)
                logger.debug("[Task %d] retry %d/%d for %s in %.1fs (%s)",
                             self.task_id, attempt, config.max_retries, url,
                             backoff, error)
                await asyncio.sleep(backoff)

    async def _on_download_progress(self, dl_id, downloaded: int,
                                    total: int | None) -> None:
        from db import queries as q

        try:
            await q.update_download_progress(dl_id, downloaded, total)
        except Exception:  # noqa: BLE001 - progress must never break a download
            logger.debug("progress update failed for download %s", dl_id)

        if self._file_progress_cb:
            try:
                await self._file_progress_cb(self.task_id, dl_id, downloaded, total)
            except Exception:  # noqa: BLE001
                pass

    async def _bump_progress(self, current_file: str) -> None:
        async with self._progress_lock:
            self._done_count += 1
            done = self._done_count
        elapsed = time.monotonic() - self._started_at
        speed = done / elapsed if elapsed > 0 else 0.0
        if self._progress_cb:
            try:
                await self._progress_cb(self.task_id, done, self._total_count,
                                        current_file, speed)
            except Exception:  # noqa: BLE001
                logger.debug("progress callback failed for task %s", self.task_id)


def _retry_after(resp: aiohttp.ClientResponse) -> int:
    try:
        return max(1, int(resp.headers.get("Retry-After", "")))
    except (TypeError, ValueError):
        return 30
