"""Site-level URL discovery: sitemap.xml, robots.txt, RSS/Atom feeds.

Discovers all pages on a website before crawling begins, so nothing is missed.
"""
import asyncio
import logging
import re
import xml.etree.ElementTree as ET
from urllib.parse import urlparse, urljoin
import aiohttp

logger = logging.getLogger(__name__)

# ── robots.txt ──────────────────────────────────────────────────────────────


async def fetch_robots_txt(base_url: str, headers: dict = None,
                            timeout: int = 15, proxy: str = None) -> dict:
    """Parse robots.txt and extract sitemap URLs + crawl directives.

    Returns:
        {
            "sitemaps": [str],          # sitemap URLs found
            "disallowed": [str],        # disallowed path patterns
            "crawl_delay": float|None,  # crawl-delay directive
        }
    """
    parsed = urlparse(base_url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"

    result = {"sitemaps": [], "disallowed": [], "crawl_delay": None}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                robots_url, headers=headers or {},
                timeout=aiohttp.ClientTimeout(total=timeout),
                proxy=proxy,
            ) as resp:
                if resp.status != 200:
                    return result
                text = await resp.text()
    except Exception:
        return result

    current_ua = None
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if line.lower().startswith('user-agent:'):
            current_ua = line.split(':', 1)[1].strip()
        elif line.lower().startswith('sitemap:'):
            sitemap_url = line.split(':', 1)[1].strip()
            # robots.txt may have relative or absolute sitemap URLs
            if not sitemap_url.startswith('http'):
                sitemap_url = urljoin(base_url, sitemap_url)
            result["sitemaps"].append(sitemap_url)
        elif line.lower().startswith('disallow:') and current_ua in ('*', None, ''):
            path = line.split(':', 1)[1].strip()
            if path:
                result["disallowed"].append(path)
        elif line.lower().startswith('crawl-delay:'):
            try:
                result["crawl_delay"] = float(line.split(':', 1)[1].strip())
            except ValueError:
                pass

    return result


# ── sitemap.xml ─────────────────────────────────────────────────────────────


async def fetch_sitemap(sitemap_url: str, headers: dict = None,
                         timeout: int = 30, proxy: str = None,
                         max_depth: int = 3) -> list[str]:
    """Recursively parse sitemap.xml (handles sitemap indexes).

    Returns list of all page URLs found in the sitemap tree.
    """
    urls = []
    await _parse_sitemap(sitemap_url, urls, headers, timeout, proxy, max_depth, 0)
    return urls


async def _parse_sitemap(url: str, urls: list, headers: dict,
                          timeout: int, proxy: str,
                          max_depth: int, depth: int):
    """Recursive sitemap parser."""
    if depth > max_depth:
        return

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, headers=headers or {},
                timeout=aiohttp.ClientTimeout(total=timeout),
                proxy=proxy,
            ) as resp:
                if resp.status != 200:
                    return
                content_type = resp.headers.get('content-type', '').lower()
                text = await resp.text()
    except Exception as e:
        logger.debug("Failed to fetch sitemap %s: %s", url, e)
        return

    # Handle gzip-compressed sitemaps served as application/gzip
    if text.startswith('\x1f\x8b'):
        return  # binary gzip, skip

    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return

    ns = {'sm': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
    tag = root.tag.lower()

    if 'sitemapindex' in tag:
        # Sitemap index — recurse into each child sitemap
        for sitemap in root.findall('.//sm:sitemap/sm:loc', ns):
            if sitemap.text:
                await _parse_sitemap(sitemap.text.strip(), urls, headers,
                                      timeout, proxy, max_depth, depth + 1)
        # Also try without namespace
        for sitemap in root.findall('.//sitemap/loc'):
            if sitemap.text:
                await _parse_sitemap(sitemap.text.strip(), urls, headers,
                                      timeout, proxy, max_depth, depth + 1)
    elif 'urlset' in tag:
        # Regular sitemap
        for url_elem in root.findall('.//sm:url/sm:loc', ns):
            if url_elem.text:
                urls.append(url_elem.text.strip())
        # Without namespace
        for url_elem in root.findall('.//url/loc'):
            if url_elem.text:
                urls.append(url_elem.text.strip())


# ── RSS / Atom feeds ────────────────────────────────────────────────────────


async def discover_feeds(html: str, base_url: str) -> list[str]:
    """Find RSS/Atom feed URLs from <link> tags in HTML."""
    feeds = []
    # <link rel="alternate" type="application/rss+xml" href="...">
    for match in re.finditer(
        r'(?i)<link\s+[^>]*?type\s*=\s*["\']application/(?:rss|atom)\+xml["\'][^>]*?>',
        html,
    ):
        tag = match.group(0)
        href_match = re.search(r'(?i)href\s*=\s*["\']([^"\']+)["\']', tag)
        if href_match:
            feed_url = href_match.group(1)
            if not feed_url.startswith('http'):
                feed_url = urljoin(base_url, feed_url)
            feeds.append(feed_url)
    return feeds


async def fetch_feed(feed_url: str, headers: dict = None,
                      timeout: int = 15, proxy: str = None) -> dict:
    """Parse RSS/Atom feed and extract media URLs + entry links.

    Returns:
        {
            "page_urls": [str],     # Links to individual posts/pages
            "media_urls": [str],    # Direct media URLs from enclosures/media:content
        }
    """
    result = {"page_urls": [], "media_urls": []}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                feed_url, headers=headers or {},
                timeout=aiohttp.ClientTimeout(total=timeout),
                proxy=proxy,
            ) as resp:
                if resp.status != 200:
                    return result
                text = await resp.text()
    except Exception:
        return result

    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return result

    # Namespace map for common feed formats
    ns = {
        'atom': 'http://www.w3.org/2005/Atom',
        'media': 'http://search.yahoo.com/mrss/',
        'itunes': 'http://www.itunes.com/dtds/podcast-1.0.dtd',
        'content': 'http://purl.org/rss/1.0/modules/content/',
    }

    # RSS 2.0
    for item in root.findall('.//item'):
        link = item.find('link')
        if link is not None and link.text:
            result["page_urls"].append(link.text.strip())

        # <enclosure url="..." type="audio/mpeg">
        for enc in item.findall('enclosure'):
            enc_url = enc.get('url')
            if enc_url:
                result["media_urls"].append(enc_url)

        # <media:content url="...">
        for mc in item.findall('media:content', ns):
            mc_url = mc.get('url')
            if mc_url:
                result["media_urls"].append(mc_url)

        # <media:thumbnail url="...">
        for mt in item.findall('media:thumbnail', ns):
            mt_url = mt.get('url')
            if mt_url:
                result["media_urls"].append(mt_url)

        # <itunes:image href="...">
        for it in item.findall('itunes:image', ns):
            it_url = it.get('href')
            if it_url:
                result["media_urls"].append(it_url)

        # <content:encoded> — may contain HTML with media
        for ce in item.findall('content:encoded', ns):
            if ce.text:
                # Extract URLs from embedded HTML
                for m in re.finditer(
                    r'(?i)(?:src|href)\s*=\s*["\']([^"\']+)["\']', ce.text
                ):
                    url = m.group(1)
                    if url.startswith(('http://', 'https://')):
                        result["media_urls"].append(url)

    # Atom
    for entry in root.findall('atom:entry', ns):
        for link in entry.findall('atom:link', ns):
            href = link.get('href')
            rel = link.get('rel', 'alternate')
            if href and rel == 'alternate':
                result["page_urls"].append(href)

        # <media:content> in Atom entries
        for mc in entry.findall('media:content', ns):
            mc_url = mc.get('url')
            if mc_url:
                result["media_urls"].append(mc_url)

    # Also try without namespace (some feeds don't use them)
    for item in root.findall('.//entry'):
        for link in item.findall('link'):
            href = link.get('href')
            if href:
                result["page_urls"].append(href)

    return result


# ── Full site discovery ─────────────────────────────────────────────────────


async def discover_site(
    base_url: str,
    headers: dict = None,
    timeout: int = 30,
    proxy: str = None,
    include_feeds: bool = True,
    max_sitemap_urls: int = 50000,
) -> dict:
    """Full site discovery: robots.txt → sitemaps → feeds → page URLs.

    Returns:
        {
            "sitemap_urls": [str],      # All URLs from sitemaps
            "feed_urls": [str],         # Feed URLs discovered
            "feed_media_urls": [str],   # Media URLs from feeds
            "feed_page_urls": [str],    # Page URLs from feeds
            "robots_crawl_delay": float|None,
        }
    """
    result = {
        "sitemap_urls": [],
        "feed_urls": [],
        "feed_media_urls": [],
        "feed_page_urls": [],
        "robots_crawl_delay": None,
    }

    parsed = urlparse(base_url)
    base_domain = f"{parsed.scheme}://{parsed.netloc}"

    # 1. Parse robots.txt
    robots = await fetch_robots_txt(base_domain, headers, timeout, proxy)
    result["robots_crawl_delay"] = robots["crawl_delay"]

    # 2. Fetch all sitemaps
    sitemap_urls = list(robots["sitemaps"])

    # Also try common sitemap locations if none found in robots.txt
    if not sitemap_urls:
        common_paths = [
            '/sitemap.xml', '/sitemap_index.xml', '/sitemap/',
            '/sitemap/sitemap.xml', '/wp-sitemap.xml',
            '/post-sitemap.xml', '/page-sitemap.xml',
        ]
        for path in common_paths:
            sitemap_urls.append(f"{base_domain}{path}")

    all_sitemap_page_urls = []
    for sitemap_url in sitemap_urls:
        urls = await fetch_sitemap(sitemap_url, headers, timeout, proxy)
        all_sitemap_page_urls.extend(urls)
        if len(all_sitemap_page_urls) >= max_sitemap_urls:
            break

    result["sitemap_urls"] = all_sitemap_page_urls[:max_sitemap_urls]
    logger.info("Discovered %d URLs from sitemaps", len(result["sitemap_urls"]))

    # 3. Try to discover RSS/Atom feeds from the homepage
    if include_feeds:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    base_url, headers=headers or {},
                    timeout=aiohttp.ClientTimeout(total=timeout),
                    proxy=proxy,
                ) as resp:
                    if resp.status == 200:
                        html = await resp.text()
                        feed_urls = await discover_feeds(html, base_url)
                        result["feed_urls"] = feed_urls
                        logger.info("Discovered %d feed URLs", len(feed_urls))

                        for feed_url in feed_urls[:10]:  # cap at 10 feeds
                            feed_data = await fetch_feed(feed_url, headers, timeout, proxy)
                            result["feed_media_urls"].extend(feed_data["media_urls"])
                            result["feed_page_urls"].extend(feed_data["page_urls"])
        except Exception as e:
            logger.warning("Feed discovery failed: %s", e)

    logger.info("Site discovery complete: %d sitemap URLs, %d feed media, %d feed pages",
                len(result["sitemap_urls"]),
                len(result["feed_media_urls"]),
                len(result["feed_page_urls"]))
    return result
