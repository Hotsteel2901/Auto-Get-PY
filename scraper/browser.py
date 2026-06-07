"""Playwright-based browser rendering for JavaScript-heavy pages.

Handles SPA, infinite scroll, lazy loading, and captures network requests
to discover media URLs that static HTML parsing would miss.
"""
import asyncio
import logging
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Singleton browser instance (reused across tasks)
_browser = None
_playwright = None


async def _ensure_browser(proxy: str = None, headless: bool = True):
    """Lazily init Playwright browser."""
    global _browser, _playwright
    if _browser is not None:
        return _browser
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise RuntimeError(
            "playwright not installed. Run: pip install playwright && playwright install chromium"
        )
    _playwright = await async_playwright().start()
    launch_opts = {"headless": headless}
    if proxy:
        launch_opts["proxy"] = {"server": proxy}
    _browser = await _playwright.chromium.launch(**launch_opts)
    return _browser


async def close_browser():
    """Shutdown browser. Call on app exit."""
    global _browser, _playwright
    if _browser:
        await _browser.close()
        _browser = None
    if _playwright:
        await _playwright.stop()
        _playwright = None


async def render_page(
    url: str,
    headers: dict = None,
    timeout: int = 30,
    proxy: str = None,
    scroll: bool = True,
    max_scrolls: int = 20,
    scroll_delay: float = 1.5,
    wait_after_load: float = 2.0,
    capture_network: bool = True,
) -> dict:
    """Render a page with Playwright and return rich data.

    Returns:
        {
            "html": str,              # Final rendered HTML
            "network_urls": set[str], # All media URLs captured from network
            "cookies": list[dict],    # Cookies set by the page
            "title": str,             # Page title
            "status": int,            # HTTP status
        }
    """
    browser = await _ensure_browser(proxy=proxy)
    context_opts = {
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "viewport": {"width": 1920, "height": 1080},
        "java_script_enabled": True,
    }
    if headers:
        context_opts["extra_http_headers"] = headers

    context = await browser.new_context(**context_opts)
    page = await context.new_page()

    network_urls = set()
    media_ct_prefixes = ("video/", "audio/", "image/")
    media_ct_exact = {
        "application/pdf", "application/zip",
        "application/x-rar-compressed", "application/x-7z-compressed",
        "application/octet-stream",
    }

    async def _on_response(response):
        """Intercept network responses and capture media URLs."""
        try:
            ct = response.headers.get("content-type", "").lower()
            url_str = response.url
            is_media = (
                any(ct.startswith(p) for p in media_ct_prefixes)
                or ct in media_ct_exact
                or any(urlparse(url_str).path.lower().endswith(ext)
                       for ext in ('.m3u8', '.mpd', '.mp4', '.webm', '.mkv',
                                   '.ts', '.flv', '.avi', '.mov'))
            )
            if is_media:
                network_urls.add(url_str)
        except Exception:
            pass

    if capture_network:
        page.on("response", _on_response)

    status = 0
    try:
        resp = await page.goto(url, wait_until="domcontentloaded",
                               timeout=timeout * 1000)
        status = resp.status if resp else 0

        # Wait for network to settle (short timeout to avoid hanging)
        try:
            await asyncio.wait_for(
                page.wait_for_load_state("networkidle", timeout=timeout * 1000),
                timeout=timeout,
            )
        except (asyncio.TimeoutError, Exception):
            pass

        # Extra wait for dynamic content
        await asyncio.sleep(wait_after_load)

        # Infinite scroll
        if scroll:
            await _auto_scroll(page, max_scrolls, scroll_delay)

        html = await page.content()
        title = await page.title()
        cookies = await context.cookies()

        return {
            "html": html,
            "network_urls": network_urls,
            "cookies": cookies,
            "title": title,
            "status": status,
        }
    except Exception as e:
        logger.warning("Playwright render failed for %s: %s", url, e)
        return {
            "html": "",
            "network_urls": network_urls,
            "cookies": [],
            "title": "",
            "status": status,
            "error": str(e),
        }
    finally:
        await context.close()


async def _auto_scroll(page, max_scrolls: int, delay: float):
    """Scroll to bottom repeatedly to trigger lazy loading / infinite scroll."""
    prev_height = 0
    stale_count = 0
    for i in range(max_scrolls):
        try:
            height = await asyncio.wait_for(
                page.evaluate("document.body.scrollHeight"), timeout=5)
            if height == prev_height:
                stale_count += 1
                if stale_count >= 2:
                    break
            else:
                stale_count = 0
            prev_height = height
            await asyncio.wait_for(
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)"),
                timeout=5)
            await asyncio.sleep(delay)
        except (asyncio.TimeoutError, Exception):
            break


async def extract_network_media(url: str, headers: dict = None,
                                 timeout: int = 30, proxy: str = None,
                                 duration: float = 10.0) -> set[str]:
    """Lightweight mode: just capture network media URLs without full render.

    Opens the page, waits for `duration` seconds while capturing media requests,
    then returns all captured URLs. Good for sites that load media via XHR/fetch.
    """
    browser = await _ensure_browser(proxy=proxy)
    context = await browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
    )
    if headers:
        await context.set_extra_http_headers(headers)

    page = await context.new_page()
    captured = set()
    media_exts = (
        '.mp4', '.webm', '.mkv', '.avi', '.mov', '.flv', '.ts', '.m3u8', '.mpd',
        '.mp3', '.wav', '.flac', '.aac', '.ogg', '.m4a', '.opus',
        '.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.avif',
        '.pdf', '.zip', '.rar', '.7z',
    )

    async def _on_resp(response):
        try:
            ct = response.headers.get("content-type", "").lower()
            u = response.url
            if (any(ct.startswith(p) for p in ("video/", "audio/", "image/"))
                or any(urlparse(u).path.lower().endswith(ext) for ext in media_exts)):
                captured.add(u)
        except Exception:
            pass

    page.on("response", _on_resp)
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
        await asyncio.sleep(duration)
    except Exception as e:
        logger.warning("Network capture failed for %s: %s", url, e)
    finally:
        await context.close()
    return captured
