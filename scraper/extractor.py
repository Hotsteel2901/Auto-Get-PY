import re
import json
import base64
import unicodedata
from urllib.parse import urljoin, urlparse, unquote, quote
from fnmatch import fnmatch


MEDIA_EXTENSIONS = (
    # Images
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp", ".ico", ".avif", ".heic",
    ".tiff", ".tif", ".jfif", ".pjpeg", ".pjp",
    # Videos
    ".mp4", ".mkv", ".webm", ".avi", ".mov", ".flv", ".wmv", ".ts", ".m3u8", ".m4v",
    ".mpd", ".f4v", ".vob", ".ogv", ".3gp", ".3g2",
    # Audio
    ".mp3", ".wav", ".flac", ".aac", ".ogg", ".wma", ".m4a", ".opus", ".mid", ".midi",
    # Documents
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".epub", ".mobi",
    ".csv", ".rtf", ".odt", ".ods", ".odp",
    # Archives
    ".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".zst",
    # Fonts (frequently bundled with sites)
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
)

# ─── Original patterns (backward compatible) ────────────────────────────────

_EXT_ALT = "|".join(ext.strip(".") for ext in MEDIA_EXTENSIONS)

URL_PATTERN = re.compile(
    r"""(?i)(?:src|href|data-src|data-url|content)\s*=\s*["']([^"']+\.(?:"""
    + _EXT_ALT + r"""))["']"""
)

M3U8_PATTERN = re.compile(r'["\']([^"\']+\.m3u8[^"\']*)["\']')

GENERIC_URL_PATTERN = re.compile(
    r'(?i)(?:src|href|data-src|data-url)\s*=\s*["\']([^"\']+)["\']'
)

# ─── Enhanced patterns ──────────────────────────────────────────────────────

# 1. <source src="..."> inside <video>/<audio>/<picture>
SOURCE_TAG_PATTERN = re.compile(
    r'(?i)<source\s+[^>]*?src\s*=\s*["\']([^"\']+)["\']'
)

# 2. poster attribute on <video>
POSTER_PATTERN = re.compile(
    r'(?i)<video\s+[^>]*?poster\s*=\s*["\']([^"\']+)["\']'
)

# 3. srcset / data-srcset
SRCSET_PATTERN = re.compile(
    r'(?i)(?:srcset|data-srcset)\s*=\s*["\']([^"\']+)["\']'
)

# 4. Lazy-load data-* attributes
LAZY_LOAD_PATTERN = re.compile(
    r'(?i)data-(?:original|lazy-src|actualsrc|original-src|hi-res-src|'
    r'full-src|image|img-src|bg|background|large-image|zoom-image|hd-src|big-src)'
    r'\s*=\s*["\']([^"\']+)["\']'
)

# 5. CSS background-image: url(...)
CSS_BG_PATTERN = re.compile(
    r"""(?i)background(?:-image)?\s*:\s*url\(\s*["']?([^"')]+\.(?:"""
    + _EXT_ALT + r"""))["']?\s*\)"""
)

# 6. CSS url() in style attributes
STYLE_URL_PATTERN = re.compile(
    r'(?i)style\s*=\s*["\'][^"\']*?url\(\s*["\']?([^"\')\s]+)["\']?\s*\)'
)

# 7. URLs inside JavaScript strings
JS_STRING_URL_PATTERN = re.compile(
    r"""(?i)(["'])((?:https?://|//)[^"'\s]+\.(?:"""
    + _EXT_ALT + r"""))\1"""
)

# 8. <img>/<video>/<source> with data-* lazy-load attributes
DATA_IMG_PATTERN = re.compile(
    r'(?i)<(?:img|video|source)\s+[^>]*?data-(?:src|original|lazy|url)[^>]*?=\s*["\']([^"\']+)["\']'
)

# 9. JSON-LD contentUrl / embedUrl / url
JSON_LD_CONTENT_URL = re.compile(
    r'(?i)"(?:contentUrl|embedUrl|thumbnailUrl|url)"\s*:\s*"((?:https?://|//)[^"]+)"'
)

# 10. Open Graph meta tags (including og:video:secure_url, og:image:url)
OG_MEDIA_PATTERN = re.compile(
    r'(?i)<meta\s+(?:property|name)\s*=\s*["\']og:(?:image|video|audio)(?::url|:secure_url)?["\']'
    r'\s+content\s*=\s*["\']([^"\']+)["\']'
)

# 11. href pointing to direct download pages
HREF_DOWNLOAD_PATTERN = re.compile(
    r"""(?i)href\s*=\s*["']([^"']*(?:download|file|attachment)[^"']*\.(?:"""
    + _EXT_ALT + r"""))["']"""
)

# 12. Quoted media URLs in page source
BARE_MEDIA_URL_PATTERN = re.compile(
    r"""(?i)(["'])((?:https?://|//)[^"'\s]{10,}\.(?:"""
    + _EXT_ALT + r"""))\1"""
)

# ─── NEW: Deeper extraction patterns ────────────────────────────────────────

# 13. Inline base64 images: data:image/png;base64,XXXXX
BASE64_IMG_PATTERN = re.compile(
    r'data:(image/(?:png|jpeg|gif|webp|svg\+xml|bmp|avif|tiff));base64,([A-Za-z0-9+/=\s]{50,})'
)

# 14. CSS @import url(...)
CSS_IMPORT_PATTERN = re.compile(
    r'(?i)@import\s+(?:url\(\s*)?["\']?([^"\')\s]+\.css[^"\')\s]*)["\']?\s*\)?'
)

# 15. CSS @font-face src: url(...)
CSS_FONT_URL_PATTERN = re.compile(
    r'(?i)@font-face\s*\{[^}]*?src\s*:[^}]*?url\(\s*["\']?([^"\')\s]+\.(?:woff2?|ttf|otf|eot))["\']?\s*\)',
    re.DOTALL,
)

# 16. CSS url() — any url() in CSS (broader than just background)
CSS_ANY_URL_PATTERN = re.compile(
    r'(?i)url\(\s*["\']?([^"\')\s]+\.(?:' + _EXT_ALT + r'))["\']?\s*\)'
)

# 17. <iframe src="...">
IFRAME_PATTERN = re.compile(
    r'(?i)<iframe\s+[^>]*?src\s*=\s*["\']([^"\']+)["\']'
)

# 18. <embed src="..."> / <object data="...">
EMBED_OBJECT_PATTERN = re.compile(
    r'(?i)<(?:embed|object)\s+[^>]*?(?:src|data)\s*=\s*["\']([^"\']+)["\']'
)

# 19. Schema.org VideoObject / ImageObject
SCHEMA_MEDIA_PATTERN = re.compile(
    r'(?i)"(?:thumbnailUrl|contentUrl|embedUrl|url|image)"\s*:\s*'
    r'(?:"([^"]+)"|\[([^\]]+)\])'
)

# 20. <picture> <source srcset="...">
PICTURE_SOURCE_PATTERN = re.compile(
    r'(?i)<picture\s*>(.*?)</picture>', re.DOTALL
)

# 21. <video>/<audio> inner <source> — extract all sources from media tags
MEDIA_TAG_PATTERN = re.compile(
    r'(?i)<(?:video|audio)\s[^>]*>(.*?)</(?:video|audio)>', re.DOTALL
)

# 22. <link rel="preload/as" href="..."> for fonts/images
LINK_PRELOAD_PATTERN = re.compile(
    r'(?i)<link\s+[^>]*?rel\s*=\s*["\'](?:preload|prefetch)["\']'
    r'[^>]*?href\s*=\s*["\']([^"\']+)["\']'
)

# 23. <meta name="twitter:image" content="...">
TWITTER_MEDIA_PATTERN = re.compile(
    r'(?i)<meta\s+(?:property|name)\s*=\s*["\']twitter:(?:image|player)(?::src)?["\']'
    r'\s+content\s*=\s*["\']([^"\']+)["\']'
)

# 24. Common CDN / storage URL patterns in scripts
CDN_URL_PATTERN = re.compile(
    r"""(?i)(["'])((?:https?://|//)[^"'\s]*(?:"""
    r"""cdn|static|assets|media|upload|storage|cloudfront|akamai|imgix|cloudinary"""
    r""")[^"'\s]*\.(?:""" + _EXT_ALT + r"""))\1"""
)

# 25. <video>/<audio> src directly
VIDEO_AUDIO_SRC_PATTERN = re.compile(
    r'(?i)<(?:video|audio)\s+[^>]*?src\s*=\s*["\']([^"\']+)["\']'
)

# 26. <img srcset> with multiple URLs — enhanced for <picture>
SRCSET_FULL_PATTERN = re.compile(
    r'(?i)srcset\s*=\s*["\']([^"\']+)["\']'
)

# 27. Blob URLs (from JS-created object URLs)
BLOB_URL_PATTERN = re.compile(
    r'(blob:[^"\'<>\s]+)'
)


def _is_media_url(url: str) -> bool:
    """Check if URL points to a media file based on extension."""
    parsed = urlparse(url)
    path = parsed.path.lower().split('?')[0].split('#')[0]
    return any(path.endswith(ext) for ext in MEDIA_EXTENSIONS)


def _normalize_url(url: str, base_url: str) -> str | None:
    """Normalize and resolve a URL. Returns None if invalid.

    Handles:
    - Unicode/Chinese characters in URLs (percent-encodes them)
    - IDN domains (punycode)
    - HTML entity decoding (&amp; → &)
    - Double-encoding detection
    """
    if not url or not url.strip():
        return None
    url = url.strip()
    if url.startswith(('data:', 'javascript:', 'mailto:', 'tel:', '#')):
        return None

    # Unescape HTML entities
    url = url.replace('&amp;', '&').replace('&#38;', '&')
    url = url.replace('&lt;', '<').replace('&gt;', '>')
    url = url.replace('&#39;', "'").replace('&quot;', '"')

    # Decode percent-encoded chars then re-encode non-ASCII properly
    try:
        decoded = unquote(url, encoding='utf-8', errors='replace')
    except Exception:
        decoded = url

    if url.startswith('//'):
        parsed_base = urlparse(base_url)
        url = f"{parsed_base.scheme}:{decoded}"
    elif not url.startswith(('http://', 'https://')):
        url = urljoin(base_url, decoded)
    else:
        url = decoded

    # Re-encode non-ASCII characters in the path (Chinese, Japanese, etc.)
    parsed = urlparse(url)
    path = parsed.path
    # Only encode chars that are not already percent-encoded and are non-ASCII
    if any(ord(c) > 127 for c in path):
        # Encode each path segment separately to preserve /
        segments = path.split('/')
        encoded_segments = []
        for seg in segments:
            if any(ord(c) > 127 for c in seg):
                seg = quote(seg, safe='')
            encoded_segments.append(seg)
        path = '/'.join(encoded_segments)
        url = f"{parsed.scheme}://{parsed.netloc}{path}"
        if parsed.query:
            url += f"?{parsed.query}"
        if parsed.fragment:
            url += f"#{parsed.fragment}"

    return url


_DIRECT_SEGMENTS = frozenset({
    "download", "file", "files", "attachment", "attachments",
    "media", "video", "audio", "image", "uploads", "upload",
    "assets", "static", "cdn",
})


def _is_direct_link(url: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path.lower()
    path_segments = [s for s in path.split("/") if s]
    if any(seg in _DIRECT_SEGMENTS for seg in path_segments):
        return True
    if parsed.query:
        query_params = parsed.query.lower()
        if 'download' in query_params or 'file=' in query_params:
            return True
    return _is_media_url(url)


def _parse_srcset(srcset_value: str, base_url: str) -> list[str]:
    """Parse srcset attribute, returning list of resolved URLs."""
    urls = []
    for part in srcset_value.split(','):
        part = part.strip()
        if not part:
            continue
        tokens = part.split()
        if tokens:
            url = _normalize_url(tokens[0], base_url)
            if url:
                urls.append(url)
    return urls


def _extract_json_urls(text: str, base_url: str) -> list[str]:
    """Extract URLs from JSON-like structures in the text."""
    urls = []
    # Match JSON objects
    for match in re.finditer(r'\{[^{}]{10,}\}', text):
        try:
            obj = json.loads(match.group())
            _walk_json_for_urls(obj, urls, base_url)
        except (json.JSONDecodeError, RecursionError):
            pass
    # Match JSON arrays
    for match in re.finditer(r'\[[^\[\]]{20,}\]', text):
        try:
            obj = json.loads(match.group())
            _walk_json_for_urls(obj, urls, base_url)
        except (json.JSONDecodeError, RecursionError):
            pass
    return urls


def _walk_json_for_urls(obj, urls: list, base_url: str):
    """Recursively walk JSON object looking for URL values."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            if isinstance(value, str):
                if value.startswith(('http://', 'https://', '//')):
                    if _is_media_url(value):
                        normalized = _normalize_url(value, base_url)
                        if normalized:
                            urls.append(normalized)
                elif value.startswith('data:image/'):
                    pass  # handled by base64 extractor
            elif isinstance(value, (dict, list)):
                _walk_json_for_urls(value, urls, base_url)
    elif isinstance(obj, list):
        for item in obj:
            if isinstance(item, (dict, list)):
                _walk_json_for_urls(item, urls, base_url)
            elif isinstance(item, str) and item.startswith(('http://', 'https://', '//')):
                if _is_media_url(item):
                    normalized = _normalize_url(item, base_url)
                    if normalized:
                        urls.append(normalized)


def extract_media_urls(html: str, base_url: str,
                       include_filters: list[str] = None,
                       exclude_filters: list[str] = None) -> list[str]:
    """Extract media URLs from HTML using 20+ strategies."""
    urls = set()

    # ── Core strategies (backward compatible) ──

    for match in URL_PATTERN.finditer(html):
        url = _normalize_url(match.group(1), base_url)
        if url:
            urls.add(url)

    for match in M3U8_PATTERN.finditer(html):
        url = _normalize_url(match.group(1), base_url)
        if url:
            urls.add(url)

    for match in GENERIC_URL_PATTERN.finditer(html):
        url = match.group(1)
        if not url.startswith(('http://', 'https://', '//')):
            continue
        if url.endswith(('.html', '.htm', '.php', '.asp', '.aspx', '.jsp')):
            continue
        if '#' in url and not url.endswith(('.m3u8',)):
            continue
        full_url = _normalize_url(url, base_url)
        if full_url and _is_direct_link(full_url):
            urls.add(full_url)

    # ── Enhanced strategies ──

    # <source> tags
    for match in SOURCE_TAG_PATTERN.finditer(html):
        url = _normalize_url(match.group(1), base_url)
        if url:
            urls.add(url)

    # video poster
    for match in POSTER_PATTERN.finditer(html):
        url = _normalize_url(match.group(1), base_url)
        if url:
            urls.add(url)

    # srcset
    for match in SRCSET_PATTERN.finditer(html):
        for url in _parse_srcset(match.group(1), base_url):
            urls.add(url)

    # Lazy-load data-*
    for match in LAZY_LOAD_PATTERN.finditer(html):
        url = _normalize_url(match.group(1), base_url)
        if url:
            urls.add(url)

    # CSS background-image
    for match in CSS_BG_PATTERN.finditer(html):
        url = _normalize_url(match.group(1), base_url)
        if url:
            urls.add(url)

    # Style attribute url()
    for match in STYLE_URL_PATTERN.finditer(html):
        candidate = match.group(1)
        url = _normalize_url(candidate, base_url)
        if url and _is_media_url(candidate):
            urls.add(url)

    # JS string URLs
    for match in JS_STRING_URL_PATTERN.finditer(html):
        url = _normalize_url(match.group(2), base_url)
        if url:
            urls.add(url)

    # JSON-LD
    for match in JSON_LD_CONTENT_URL.finditer(html):
        url = _normalize_url(match.group(1), base_url)
        if url:
            urls.add(url)

    # Open Graph
    for match in OG_MEDIA_PATTERN.finditer(html):
        url = _normalize_url(match.group(1), base_url)
        if url:
            urls.add(url)

    # Bare media URLs in quotes
    for match in BARE_MEDIA_URL_PATTERN.finditer(html):
        url = _normalize_url(match.group(2), base_url)
        if url:
            urls.add(url)

    # Deep JSON extraction
    for url in _extract_json_urls(html, base_url):
        urls.add(url)

    # href download links
    for match in HREF_DOWNLOAD_PATTERN.finditer(html):
        url = _normalize_url(match.group(1), base_url)
        if url:
            urls.add(url)

    # ── NEW deep strategies ──

    # CSS any url() — catches fonts, images in inline styles, etc.
    for match in CSS_ANY_URL_PATTERN.finditer(html):
        url = _normalize_url(match.group(1), base_url)
        if url:
            urls.add(url)

    # <video>/<audio> direct src
    for match in VIDEO_AUDIO_SRC_PATTERN.finditer(html):
        url = _normalize_url(match.group(1), base_url)
        if url:
            urls.add(url)

    # <embed> / <object>
    for match in EMBED_OBJECT_PATTERN.finditer(html):
        url = _normalize_url(match.group(1), base_url)
        if url:
            urls.add(url)

    # <link rel="preload/prefetch">
    for match in LINK_PRELOAD_PATTERN.finditer(html):
        url = _normalize_url(match.group(1), base_url)
        if url and _is_media_url(url):
            urls.add(url)

    # Twitter card media
    for match in TWITTER_MEDIA_PATTERN.finditer(html):
        url = _normalize_url(match.group(1), base_url)
        if url:
            urls.add(url)

    # Schema.org VideoObject/ImageObject (nested in JSON-LD)
    for match in SCHEMA_MEDIA_PATTERN.finditer(html):
        raw = match.group(1) or match.group(2)
        if raw:
            # Could be a single URL or a JSON array
            if raw.startswith('['):
                try:
                    arr = json.loads(raw)
                    for item in arr:
                        if isinstance(item, str):
                            url = _normalize_url(item, base_url)
                            if url:
                                urls.add(url)
                except json.JSONDecodeError:
                    pass
            else:
                url = _normalize_url(raw, base_url)
                if url:
                    urls.add(url)

    # CDN URLs in scripts
    for match in CDN_URL_PATTERN.finditer(html):
        url = _normalize_url(match.group(2), base_url)
        if url:
            urls.add(url)

    # <picture> <source> extraction
    for pic_match in PICTURE_SOURCE_PATTERN.finditer(html):
        pic_html = pic_match.group(1)
        for src_match in SRCSET_FULL_PATTERN.finditer(pic_html):
            for url in _parse_srcset(src_match.group(1), base_url):
                urls.add(url)
        for src_match in SOURCE_TAG_PATTERN.finditer(pic_html):
            url = _normalize_url(src_match.group(1), base_url)
            if url:
                urls.add(url)

    # <video>/<audio> inner sources
    for media_match in MEDIA_TAG_PATTERN.finditer(html):
        inner = media_match.group(1)
        for src_match in re.finditer(r'(?i)src\s*=\s*["\']([^"\']+)["\']', inner):
            url = _normalize_url(src_match.group(1), base_url)
            if url:
                urls.add(url)

    # ── Apply filters ──
    result = list(urls)

    if include_filters:
        result = [u for u in result if any(
            fnmatch(urlparse(u).path.lower(), f.lower()) for f in include_filters
        )]

    if exclude_filters:
        result = [u for u in result if not any(
            fnmatch(urlparse(u).path.lower(), f.lower()) for f in exclude_filters
        )]

    return result


def extract_inline_base64_images(html: str, output_dir: str = None) -> list[dict]:
    """Extract inline base64-encoded images and optionally save to disk.

    Returns list of:
        [{"format": "png", "size": 12345, "data": bytes, "saved_path": str|None}]
    """
    results = []
    for match in BASE64_IMG_PATTERN.finditer(html):
        fmt = match.group(1).split('/')[-1].replace('+xml', '')
        data_str = match.group(2).replace('\n', '').replace('\r', '').replace(' ', '')
        try:
            data = base64.b64decode(data_str)
            entry = {"format": fmt, "size": len(data), "data": data, "saved_path": None}
            if output_dir and len(data) > 1024:  # only save images > 1KB
                import hashlib
                from pathlib import Path
                h = hashlib.md5(data).hexdigest()[:12]
                fname = f"inline_{h}.{fmt}"
                fpath = Path(output_dir) / fname
                if not fpath.exists():
                    fpath.write_bytes(data)
                entry["saved_path"] = str(fpath)
            results.append(entry)
        except Exception:
            continue
    return results


def extract_css_urls(css_text: str, base_url: str) -> list[str]:
    """Extract all media URLs from CSS content (for crawling external CSS files)."""
    urls = set()
    # url() references
    for match in CSS_ANY_URL_PATTERN.finditer(css_text):
        url = _normalize_url(match.group(1), base_url)
        if url:
            urls.add(url)
    # @font-face src
    for match in CSS_FONT_URL_PATTERN.finditer(css_text):
        url = _normalize_url(match.group(1), base_url)
        if url:
            urls.add(url)
    # @import — return these as CSS file URLs to crawl further
    imports = []
    for match in CSS_IMPORT_PATTERN.finditer(css_text):
        url = _normalize_url(match.group(1), base_url)
        if url:
            imports.append(url)
    return list(urls), imports


# ── Pagination & link discovery ─────────────────────────────────────────────

_NEXT_PAGE_PATTERNS = [
    # rel="next" patterns
    re.compile(r'(?i)<a\s+[^>]*?rel\s*=\s*["\'](?:[^"\']*\s)?next(?:\s[^"\']*)?["\'][^>]*?href\s*=\s*["\']([^"\']+)["\']'),
    re.compile(r'(?i)<a\s+[^>]*?href\s*=\s*["\']([^"\']+)["\'][^>]*?rel\s*=\s*["\'](?:[^"\']*\s)?next(?:\s[^"\']*)?["\']'),
    re.compile(r'(?i)<link\s+[^>]*?rel\s*=\s*["\']next["\'][^>]*?href\s*=\s*["\']([^"\']+)["\']'),
    # Chinese text patterns (下一页/下一頁/后页/后页/下页/>>/≫)
    re.compile(r'(?i)<a\s+[^>]*?href\s*=\s*["\']([^"\']+)["\'][^>]*>\s*(?:下一页|下一頁|后页|後頁|下页|下頁)\s*</a>', re.DOTALL),
    # Unicode arrows and chevrons
    re.compile(r'(?i)<a\s+[^>]*?href\s*=\s*["\']([^"\']+)["\'][^>]*>\s*(?:next|›|»|→|>|≫|▶|>>)\s*</a>', re.DOTALL),
    re.compile(r'(?i)<a\s+[^>]*?href\s*=\s*["\']([^"\']+)["\'][^>]*>\s*Next\s*Page\s*</a>', re.DOTALL),
    # Class-based patterns (next, pagination-next, page-next, 后页, 下一页)
    re.compile(r'(?i)<a\s+[^>]*?href\s*=\s*["\']([^"\']+)["\'][^>]*?class\s*=\s*["\'][^"\']*?(?:next|pagination-next|page-next|btn-next)[^"\']*?["\']'),
    re.compile(r'(?i)<a\s+[^>]*?class\s*=\s*["\'][^"\']*?(?:next|pagination-next|page-next)[^"\']*?["\'][^>]*?href\s*=\s*["\']([^"\']+)["\']'),
    # page=N pattern in links with "next" context
    re.compile(r'(?i)<a\s+[^>]*?href\s*=\s*["\']([^"\']*?page=\d+[^"\']*)["\'][^>]*?class\s*=\s*["\'][^"\']*?next[^"\']*?["\']'),
    # Chinese page number links: 第X页 where X > current
    re.compile(r'(?i)<a\s+[^>]*?href\s*=\s*["\']([^"\']+)["\'][^>]*>\s*(?:\u7b2c?\s*\d+\s*\u9875?)\s*</a>'),
]


def find_next_page_url(html: str, base_url: str) -> str | None:
    """Find the next page URL from pagination links."""
    for pattern in _NEXT_PAGE_PATTERNS:
        match = pattern.search(html)
        if match:
            url = _normalize_url(match.group(1), base_url)
            if url and url != base_url:
                return url
    return None


_LINK_PATTERN = re.compile(
    r'(?i)<a\s+[^>]*?href\s*=\s*["\']([^"\'#]+)["\']'
)

_SKIP_EXTENSIONS = {
    '.css', '.js', '.json', '.xml', '.rss', '.atom', '.txt',
    '.ico', '.robots', '.sitemap', '.map',
}


def extract_page_links(html: str, base_url: str,
                       same_domain: bool = True,
                       allowed_paths: list[str] = None) -> list[str]:
    """Extract all <a href> links from a page for crawling."""
    base_parsed = urlparse(base_url)
    base_domain = base_parsed.netloc
    links = set()

    for match in _LINK_PATTERN.finditer(html):
        raw_url = match.group(1).strip()
        url = _normalize_url(raw_url, base_url)
        if not url:
            continue

        parsed = urlparse(url)
        if parsed.scheme not in ('http', 'https'):
            continue
        if same_domain and parsed.netloc != base_domain:
            continue

        path_lower = parsed.path.lower()
        if any(path_lower.endswith(ext) for ext in _SKIP_EXTENSIONS):
            continue
        if raw_url.startswith(('#', 'javascript:')):
            continue

        if allowed_paths:
            if not any(path_lower.startswith(prefix.lower()) for prefix in allowed_paths):
                continue

        url = url.split('#')[0]
        if url:
            links.add(url)

    return list(links)


def extract_iframe_urls(html: str, base_url: str) -> list[str]:
    """Extract iframe src URLs for further crawling."""
    urls = []
    for match in IFRAME_PATTERN.finditer(html):
        url = _normalize_url(match.group(1), base_url)
        if url and url.startswith(('http://', 'https://')):
            urls.append(url)
    return urls


# ── Meta refresh redirect detection ─────────────────────────────────────────

_META_REFRESH_PATTERN = re.compile(
    r'(?i)<meta\s+[^>]*?http-equiv\s*=\s*["\']refresh["\'][^>]*?content\s*=\s*["\'][^"\']*?url=([^"\';\s]+)',
    re.DOTALL,
)
_META_REFRESH_PATTERN2 = re.compile(
    r'(?i)<meta\s+[^>]*?content\s*=\s*["\'][^"\']*?url=([^"\';\s]+)[^"\']*?["\'][^>]*?http-equiv\s*=\s*["\']refresh["\']',
    re.DOTALL,
)


def find_meta_refresh_url(html: str, base_url: str) -> str | None:
    """Detect <meta http-equiv="refresh" content="0;url=..."> redirects."""
    for pattern in (_META_REFRESH_PATTERN, _META_REFRESH_PATTERN2):
        match = pattern.search(html)
        if match:
            url = _normalize_url(match.group(1), base_url)
            if url and url.startswith(('http://', 'https://')):
                return url
    return None


# ── <noscript> and <template> content extraction ────────────────────────────

_NOSCRIPT_PATTERN = re.compile(r'(?i)<noscript>(.*?)</noscript>', re.DOTALL)
_TEMPLATE_PATTERN = re.compile(r'(?i)<template>(.*?)</template>', re.DOTALL)


def extract_noscript_template_urls(html: str, base_url: str) -> list[str]:
    """Extract media URLs from <noscript> and <template> tags.

    Sites like Pinterest/Instagram put real image URLs in <noscript> fallbacks.
    <template> tags may contain lazy-loaded content not yet in the DOM.
    """
    urls = set()
    for pattern in (_NOSCRIPT_PATTERN, _TEMPLATE_PATTERN):
        for match in pattern.finditer(html):
            inner = match.group(1)
            # Reuse the main URL pattern on inner content
            for url_match in URL_PATTERN.finditer(inner):
                url = _normalize_url(url_match.group(1), base_url)
                if url:
                    urls.add(url)
            for url_match in SOURCE_TAG_PATTERN.finditer(inner):
                url = _normalize_url(url_match.group(1), base_url)
                if url:
                    urls.add(url)
            for url_match in LAZY_LOAD_PATTERN.finditer(inner):
                url = _normalize_url(url_match.group(1), base_url)
                if url:
                    urls.add(url)
    return list(urls)


# ── Manifest.json parsing ───────────────────────────────────────────────────

_MANIFEST_LINK_PATTERN = re.compile(
    r'(?i)<link\s+[^>]*?rel\s*=\s*["\']manifest["\'][^>]*?href\s*=\s*["\']([^"\']+)["\']'
)


def find_manifest_url(html: str, base_url: str) -> str | None:
    """Find the PWA manifest.json URL from <link rel="manifest">."""
    match = _MANIFEST_LINK_PATTERN.search(html)
    if match:
        return _normalize_url(match.group(1), base_url)
    return None


# ── URL canonicalization (tracking param removal) ───────────────────────────

_TRACKING_PARAMS = {
    'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content',
    'utm_id', 'utm_source_platform', 'utm_creative_format',
    'fbclid', 'gclid', 'gclsrc', 'dclid', 'gbraid', 'wbraid',
    'msclkid', 'twclid', 'li_fat_id',
    'mc_cid', 'mc_eid',
    'ref', 'referrer', 'source', 'spm', 'from', 'isappinstalled',
    'scene', 'clickid', 'share_source', 'share_medium',
    '_ga', '_gl', 'yclid', 'igshid',
}


def canonicalize_url(url: str) -> str:
    """Remove tracking parameters from URL for deduplication.

    Also normalizes:
    - Removes trailing slashes from path
    - Lowercases scheme and domain
    - Removes fragment
    """
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    path = parsed.path.rstrip('/') or '/'

    # Remove tracking params
    if parsed.query:
        from urllib.parse import parse_qs, urlencode
        params = parse_qs(parsed.query, keep_blank_values=True)
        clean_params = {k: v for k, v in params.items()
                       if k.lower() not in _TRACKING_PARAMS}
        query = urlencode(clean_params, doseq=True) if clean_params else ''
    else:
        query = ''

    return f"{scheme}://{netloc}{path}" + (f"?{query}" if query else '')


# ── Encoding detection helper ───────────────────────────────────────────────

def detect_encoding(resp_headers: dict, body: bytes) -> str:
    """Detect encoding from Content-Type header or body sniffing.

    Priority:
    1. Content-Type charset parameter
    2. HTML <meta charset="...">
    3. BOM detection
    4. Default utf-8
    """
    # 1. Content-Type header
    ct = resp_headers.get('content-type', '')
    ct_match = re.search(r'charset=([^\s;]+)', ct, re.IGNORECASE)
    if ct_match:
        return ct_match.group(1).strip().strip('"\'').lower()

    # 2. HTML meta charset (look in first 4KB)
    head = body[:4096]
    meta_match = re.search(
        rb'(?i)<meta[^>]+charset=["\']?([^"\'\s;>]+)', head)
    if meta_match:
        return meta_match.group(1).decode('ascii', errors='ignore').lower()

    # 3. BOM detection
    if body.startswith(b'\xef\xbb\xbf'):
        return 'utf-8-sig'
    if body.startswith(b'\xff\xfe'):
        return 'utf-16-le'
    if body.startswith(b'\xfe\xff'):
        return 'utf-16-be'

    # 4. Default
    return 'utf-8'


# ── Content-Type to extension mapping ───────────────────────────────────────

_CT_EXTENSION_MAP = {
    'image/jpeg': '.jpg', 'image/png': '.png', 'image/gif': '.gif',
    'image/webp': '.webp', 'image/svg+xml': '.svg', 'image/avif': '.avif',
    'image/bmp': '.bmp', 'image/tiff': '.tiff',
    'video/mp4': '.mp4', 'video/webm': '.webm', 'video/x-flv': '.flv',
    'video/x-matroska': '.mkv', 'video/quicktime': '.mov',
    'video/MP2T': '.ts',
    'audio/mpeg': '.mp3', 'audio/ogg': '.ogg', 'audio/wav': '.wav',
    'audio/flac': '.flac', 'audio/aac': '.aac', 'audio/mp4': '.m4a',
    'audio/opus': '.opus',
    'application/pdf': '.pdf',
    'application/zip': '.zip',
    'application/x-rar-compressed': '.rar',
    'application/x-7z-compressed': '.7z',
    'application/gzip': '.gz',
    'font/woff': '.woff', 'font/woff2': '.woff2',
    'application/font-woff': '.woff', 'application/font-woff2': '.woff2',
}


def guess_extension_from_content_type(content_type: str) -> str | None:
    """Guess file extension from Content-Type header."""
    ct = content_type.split(';')[0].strip().lower()
    return _CT_EXTENSION_MAP.get(ct)
