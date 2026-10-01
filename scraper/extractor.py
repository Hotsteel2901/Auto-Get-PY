"""Media URL extraction.

Given the HTML (or CSS, or JSON) of a page, find every URL that points at a
downloadable asset.  Extraction is deliberately multi-strategy: sites hide
their media in ``src``, ``srcset``, lazy-load ``data-*`` attributes, CSS
``url()`` declarations, JSON-LD blocks, inline ``<script>`` strings,
``<noscript>`` fallbacks and ``<template>`` markup, and a generic scraper has
to look in all of them.
"""

from __future__ import annotations

import base64
import html as html_module
import json
import re
from fnmatch import fnmatch
from urllib.parse import (
    quote, unquote, urljoin, urlparse, urlunparse,
)

MEDIA_EXTENSIONS = (
    # Images
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp", ".ico", ".avif", ".heic",
    ".tiff", ".tif", ".jfif", ".pjpeg", ".pjp",
    # Videos
    ".mp4", ".mkv", ".webm", ".avi", ".mov", ".flv", ".wmv", ".ts", ".m3u8", ".m4v",
    ".mpd", ".f4v", ".vob", ".ogv", ".3gp", ".3g2", ".m4s", ".ism",
    # Audio
    ".mp3", ".wav", ".flac", ".aac", ".ogg", ".wma", ".m4a", ".opus", ".mid", ".midi",
    ".m4b", ".aiff", ".weba",
    # Documents
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".epub", ".mobi",
    ".csv", ".rtf", ".odt", ".ods", ".odp", ".srt", ".vtt",
    # Archives
    ".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".zst", ".tgz",
    # Fonts (frequently bundled with sites)
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
)

MEDIA_EXTENSION_SET = frozenset(MEDIA_EXTENSIONS)

_EXT_ALT = "|".join(ext.lstrip(".") for ext in MEDIA_EXTENSIONS)

# Schemes that never point at a downloadable file.
_REJECTED_SCHEMES = ("data:", "javascript:", "mailto:", "tel:", "about:", "blob:", "chrome:")

# Characters that are safe to leave unescaped inside a URL path/query.
_PATH_SAFE = "/%:@!$&'()*+,;=~-._"
_QUERY_SAFE = "=&%:;+,?/@!$'()*~-._[]"

# ─── Core patterns ──────────────────────────────────────────────────────────

# The trailing ``[^"']*`` keeps query strings and chained suffixes
# (``archive.tar.gz``, ``img.jpg?w=800&sig=…``) attached to the captured URL.
URL_PATTERN = re.compile(
    r"""(?i)(?:src|href|data-src|data-url|content|poster)\s*=\s*["']([^"']+\.(?:"""
    + _EXT_ALT + r""")[^"']*)["']"""
)

M3U8_PATTERN = re.compile(r'["\']([^"\']+\.(?:m3u8|mpd)[^"\']*)["\']')

GENERIC_URL_PATTERN = re.compile(
    r'(?i)(?:src|href|data-src|data-url)\s*=\s*["\']([^"\']+)["\']'
)

SOURCE_TAG_PATTERN = re.compile(r'(?i)<source\s+[^>]*?src\s*=\s*["\']([^"\']+)["\']')

POSTER_PATTERN = re.compile(r'(?i)<video\s+[^>]*?poster\s*=\s*["\']([^"\']+)["\']')

SRCSET_PATTERN = re.compile(r'(?i)(?:srcset|data-srcset)\s*=\s*["\']([^"\']+)["\']')

LAZY_LOAD_PATTERN = re.compile(
    r'(?i)data-(?:original|lazy-src|actualsrc|original-src|hi-res-src|'
    r'full-src|image|img-src|bg|background|large-image|zoom-image|hd-src|big-src|'
    r'url|source|video|file|download|thumb|thumbnail)'
    r'\s*=\s*["\']([^"\']+)["\']'
)

CSS_BG_PATTERN = re.compile(
    r"""(?i)background(?:-image)?\s*:\s*url\(\s*["']?([^"')]+\.(?:"""
    + _EXT_ALT + r""")[^"')]*)["']?\s*\)"""
)

STYLE_URL_PATTERN = re.compile(
    r'(?i)style\s*=\s*["\'][^"\']*?url\(\s*["\']?([^"\')\s]+)["\']?\s*\)'
)

JS_STRING_URL_PATTERN = re.compile(
    r"""(?i)(["'])((?:https?://|//)[^"'\s]+\.(?:""" + _EXT_ALT + r""")[^"'\s]*)\1"""
)

# URLs escaped inside JSON string literals: https:\/\/cdn.example.com\/a.jpg
JSON_ESCAPED_URL_PATTERN = re.compile(
    r"""(?i)["']((?:https?:)?\\?/\\?/[^"'\s]+?\.(?:""" + _EXT_ALT + r""")[^"'\s]*?)["']"""
)

DATA_IMG_PATTERN = re.compile(
    r'(?i)<(?:img|video|source|a|div)\s+[^>]*?data-(?:src|original|lazy|url)'
    r'[^>]*?=\s*["\']([^"\']+)["\']'
)

JSON_LD_CONTENT_URL = re.compile(
    r'(?i)"(?:contentUrl|embedUrl|thumbnailUrl|url|image|src|videoUrl|audioUrl|file)"'
    r'\s*:\s*"((?:https?://|//|/)[^"]+)"'
)

OG_MEDIA_PATTERN = re.compile(
    r'(?i)<meta\s+(?:property|name)\s*=\s*["\']og:(?:image|video|audio)'
    r'(?::url|:secure_url)?["\']\s+content\s*=\s*["\']([^"\']+)["\']'
)

HREF_DOWNLOAD_PATTERN = re.compile(
    r"""(?i)href\s*=\s*["']([^"']*(?:download|file|attachment|media|video|audio|image)"""
    r"""[^"']*\.(?:""" + _EXT_ALT + r""")[^"']*)["']"""
)

BARE_MEDIA_URL_PATTERN = re.compile(
    r"""(?i)(["'])((?:https?://|//)[^"'\s]{10,}\.(?:""" + _EXT_ALT + r"""))\1"""
)

BASE64_IMG_PATTERN = re.compile(
    r'data:(image/(?:png|jpeg|jpg|gif|webp|svg\+xml|bmp|avif|tiff));base64,'
    r'([A-Za-z0-9+/=\s]{50,})'
)

CSS_IMPORT_PATTERN = re.compile(
    r'(?i)@import\s+(?:url\(\s*)?["\']?([^"\')\s]+\.css[^"\')\s]*)["\']?\s*\)?'
)

CSS_FONT_URL_PATTERN = re.compile(
    r'(?i)@font-face\s*\{[^}]*?src\s*:[^}]*?url\(\s*["\']?([^"\')\s]+\.(?:woff2?|ttf|otf|eot))'
    r'["\']?\s*\)',
    re.DOTALL,
)

CSS_ANY_URL_PATTERN = re.compile(
    r'(?i)url\(\s*["\']?([^"\')\s]+\.(?:' + _EXT_ALT + r')[^"\')\s]*)["\']?\s*\)'
)

IFRAME_PATTERN = re.compile(r'(?i)<iframe\s+[^>]*?src\s*=\s*["\']([^"\']+)["\']')

EMBED_OBJECT_PATTERN = re.compile(
    r'(?i)<(?:embed|object)\s+[^>]*?(?:src|data)\s*=\s*["\']([^"\']+)["\']'
)

SCHEMA_MEDIA_PATTERN = re.compile(
    r'(?i)"(?:thumbnailUrl|contentUrl|embedUrl|url|image)"\s*:\s*'
    r'(?:"([^"]+)"|\[([^\]]+)\])'
)

PICTURE_SOURCE_PATTERN = re.compile(r'(?i)<picture\s*>(.*?)</picture>', re.DOTALL)

MEDIA_TAG_PATTERN = re.compile(r'(?i)<(?:video|audio)\s[^>]*>(.*?)</(?:video|audio)>', re.DOTALL)

LINK_PRELOAD_PATTERN = re.compile(
    r'(?i)<link\s+[^>]*?rel\s*=\s*["\'](?:preload|prefetch|apple-touch-icon)["\']'
    r'[^>]*?href\s*=\s*["\']([^"\']+)["\']'
)

TWITTER_MEDIA_PATTERN = re.compile(
    r'(?i)<meta\s+(?:property|name)\s*=\s*["\']twitter:(?:image|player)(?::src)?["\']'
    r'\s+content\s*=\s*["\']([^"\']+)["\']'
)

CDN_URL_PATTERN = re.compile(
    r"""(?i)(["'])((?:https?://|//)[^"'\s]*(?:"""
    r"""cdn|static|assets|media|upload|storage|cloudfront|akamai|imgix|cloudinary|"""
    r"""aliyuncs|myqcloud|b-cdn|fastly)"""
    r"""[^"'\s]*\.(?:""" + _EXT_ALT + r"""))(?:[?#][^"'\s]*)?\1"""
)

VIDEO_AUDIO_SRC_PATTERN = re.compile(
    r'(?i)<(?:video|audio)\s+[^>]*?src\s*=\s*["\']([^"\']+)["\']'
)

SRCSET_FULL_PATTERN = re.compile(r'(?i)srcset\s*=\s*["\']([^"\']+)["\']')

BLOB_URL_PATTERN = re.compile(r'(blob:[^"\'<>\s]+)')

_NOSCRIPT_PATTERN = re.compile(r'(?i)<noscript[^>]*>(.*?)</noscript>', re.DOTALL)
_TEMPLATE_PATTERN = re.compile(r'(?i)<template[^>]*>(.*?)</template>', re.DOTALL)

_DIRECT_SEGMENTS = frozenset({
    "download", "downloads", "file", "files", "attachment", "attachments",
    "media", "video", "videos", "audio", "image", "images", "uploads", "upload",
    "assets", "static", "cdn", "storage", "get", "stream",
})

_SKIP_EXTENSIONS = frozenset({
    ".css", ".js", ".json", ".xml", ".rss", ".atom", ".map",
})

_HTML_DOC_EXTENSIONS = frozenset({
    ".html", ".htm", ".php", ".asp", ".aspx", ".jsp", ".do", ".action",
})

# Pages that are almost certainly not worth crawling.
_SKIP_LINK_WORDS = frozenset({
    "login", "logout", "signup", "signin", "register", "cart", "checkout",
    "privacy", "terms", "cookie", "unsubscribe",
})


# ── URL normalisation ───────────────────────────────────────────────────────


def _idna_host(netloc: str) -> str:
    """Encode an internationalised host to punycode, keeping userinfo/port."""
    if not netloc or netloc.isascii():
        return netloc
    userinfo = ""
    if "@" in netloc:
        userinfo, netloc = netloc.rsplit("@", 1)
        userinfo += "@"
    host, sep, port = netloc.rpartition(":")
    if not sep or not port.isdigit():
        host, port, sep = netloc, "", ""
    try:
        return f"{userinfo}{host.encode('idna').decode('ascii')}{sep}{port}"
    except (UnicodeError, UnicodeDecodeError):
        return f"{userinfo}{host}{sep}{port}"


def _encode_url(raw: str) -> str:
    """Percent-encode a URL, preserving escapes that are already valid."""
    parsed = urlparse(raw)
    path = quote(parsed.path, safe=_PATH_SAFE)
    query = quote(parsed.query, safe=_QUERY_SAFE)
    return urlunparse((
        parsed.scheme.lower(),
        _idna_host(parsed.netloc.lower()),
        path,
        parsed.params,
        query,
        "",  # fragments never identify a distinct asset
    ))


def _normalize_url(url: str, base_url: str) -> str | None:
    """Resolve ``url`` against ``base_url`` and make it safe to request.

    Handles HTML entities, protocol-relative URLs, internationalised domains,
    spaces and non-ASCII path segments. Returns ``None`` for anything that
    cannot be an http(s) asset.
    """
    if not url:
        return None
    url = html_module.unescape(str(url)).strip().strip("\"'")
    if not url or url.startswith("#") or url.startswith(_REJECTED_SCHEMES):
        return None
    # Undo the escaping that URLs pick up inside JS/JSON string literals.
    url = url.replace("\\/", "/").replace("\\u002F", "/").replace("\\u002f", "/")
    url = url.lstrip("\u0000-\u001f").strip()
    if not url or url.startswith("#") or url.startswith(_REJECTED_SCHEMES):
        return None

    if url.startswith("//"):
        url = f"{urlparse(base_url).scheme or 'https'}:{url}"
    elif not url.startswith(("http://", "https://")):
        if re.match(r"^[a-zA-Z][a-zA-Z0-9+.\-]*:", url):
            return None  # some other scheme (ftp:, ws:, …)
        url = urljoin(base_url, url)

    try:
        encoded = _encode_url(url)
    except (ValueError, UnicodeError):
        return None

    parsed = urlparse(encoded)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    return encoded


def _is_media_url(url: str) -> bool:
    """True when the URL path ends in a known media extension."""
    parsed = urlparse(url)
    path = parsed.path.lower()
    return any(path.endswith(ext) for ext in MEDIA_EXTENSION_SET)


def _is_direct_link(url: str) -> bool:
    """True when a URL looks like a file rather than an HTML page."""
    parsed = urlparse(url)
    path = parsed.path.lower()
    if any(seg in _DIRECT_SEGMENTS for seg in path.split("/") if seg):
        return True
    if parsed.query:
        query = parsed.query.lower()
        if "download" in query or "file=" in query or "filename=" in query:
            return True
    return _is_media_url(url)


def _parse_srcset(srcset_value: str, base_url: str) -> list[str]:
    """Parse a ``srcset`` attribute into resolved URLs."""
    urls = []
    for part in srcset_value.split(","):
        part = part.strip()
        if not part:
            continue
        tokens = part.split()
        if tokens:
            url = _normalize_url(tokens[0], base_url)
            if url:
                urls.append(url)
    return urls


def _walk_json_for_urls(obj, urls: list, base_url: str) -> None:
    """Recursively collect URL-ish string values from decoded JSON."""
    if isinstance(obj, dict):
        for value in obj.values():
            _walk_json_for_urls(value, urls, base_url)
    elif isinstance(obj, list):
        for item in obj:
            _walk_json_for_urls(item, urls, base_url)
    elif isinstance(obj, str) and obj.startswith(("http://", "https://", "//", "/")):
        if _is_media_url(obj) or _is_direct_link(obj):
            normalized = _normalize_url(obj, base_url)
            if normalized:
                urls.append(normalized)


def _extract_json_urls(text: str, base_url: str) -> list[str]:
    """Pull URLs out of JSON objects and arrays embedded in the page."""
    urls: list[str] = []
    for match in re.finditer(r"\{[^{}]{10,}\}", text):
        try:
            _walk_json_for_urls(json.loads(match.group()), urls, base_url)
        except (json.JSONDecodeError, RecursionError):
            pass
    for match in re.finditer(r"\[[^\[\]]{20,}\]", text):
        try:
            _walk_json_for_urls(json.loads(match.group()), urls, base_url)
        except (json.JSONDecodeError, RecursionError):
            pass
    return urls


# ── Main extractor ──────────────────────────────────────────────────────────


def extract_media_urls(html: str, base_url: str,
                       include_filters: list[str] | None = None,
                       exclude_filters: list[str] | None = None) -> list[str]:
    """Extract every downloadable media URL from a page."""
    if not html:
        return []
    urls: set[str] = set()

    def add(raw: str) -> None:
        resolved = _normalize_url(raw, base_url)
        if resolved:
            urls.add(resolved)

    def add_all(raw_list) -> None:
        for item in raw_list:
            add(item)

    # 1. Direct attribute matches (src/href/poster/data-src, with extension).
    for match in URL_PATTERN.finditer(html):
        add(match.group(1))

    # 2. Playlists announced anywhere in quotes (may have query strings).
    for match in M3U8_PATTERN.finditer(html):
        add(match.group(1))

    # 3. Attribute values that resolve to something file-shaped.
    for match in GENERIC_URL_PATTERN.finditer(html):
        candidate = match.group(1)
        if not candidate.startswith(("http://", "https://", "//")):
            continue
        if candidate.lower().endswith(tuple(_HTML_DOC_EXTENSIONS)):
            continue
        if "#" in candidate and not candidate.endswith((".m3u8", ".mpd")):
            continue
        resolved = _normalize_url(candidate, base_url)
        if resolved and _is_direct_link(resolved):
            urls.add(resolved)

    # 4. Dedicated tag/attribute passes.
    for pattern in (
        SOURCE_TAG_PATTERN, POSTER_PATTERN, LAZY_LOAD_PATTERN, CSS_BG_PATTERN,
        JS_STRING_URL_PATTERN, JSON_ESCAPED_URL_PATTERN, OG_MEDIA_PATTERN,
        BARE_MEDIA_URL_PATTERN, HREF_DOWNLOAD_PATTERN, CSS_ANY_URL_PATTERN,
        VIDEO_AUDIO_SRC_PATTERN, EMBED_OBJECT_PATTERN, TWITTER_MEDIA_PATTERN,
    ):
        for match in pattern.finditer(html):
            add(match.group(match.lastindex or 1))

    # 5. srcset — several candidate URLs per attribute.
    for match in SRCSET_PATTERN.finditer(html):
        add_all(_parse_srcset(match.group(1), base_url))

    # 6. style="... url(...)" — only when the target really is media.
    for match in STYLE_URL_PATTERN.finditer(html):
        candidate = match.group(1)
        if _is_media_url(candidate) or _looks_like_media_path(candidate):
            add(candidate)

    # 7. Anything inside a JSON string.
    for match in JSON_LD_CONTENT_URL.finditer(html):
        add(match.group(1))

    # 8. Recursively walk embedded JSON blobs.
    add_all(_extract_json_urls(html, base_url))

    # 9. rel="preload" targets, but only genuine media.
    for match in LINK_PRELOAD_PATTERN.finditer(html):
        resolved = _normalize_url(match.group(1), base_url)
        if resolved and _is_media_url(resolved):
            urls.add(resolved)

    # 10. Schema.org values, including JSON arrays.
    for match in SCHEMA_MEDIA_PATTERN.finditer(html):
        raw = match.group(1) or match.group(2)
        if not raw:
            continue
        if raw.strip().startswith("["):
            try:
                add_all(json.loads(raw))
            except json.JSONDecodeError:
                pass
        else:
            add(raw)

    # 11. CDN-hosted assets referenced from script strings.
    for match in CDN_URL_PATTERN.finditer(html):
        add(match.group(2))

    # 12. <picture> and <video>/<audio> internals.
    for pic_match in PICTURE_SOURCE_PATTERN.finditer(html):
        inner = pic_match.group(1)
        for src_match in SRCSET_FULL_PATTERN.finditer(inner):
            add_all(_parse_srcset(src_match.group(1), base_url))
        for src_match in SOURCE_TAG_PATTERN.finditer(inner):
            add(src_match.group(1))

    for media_match in MEDIA_TAG_PATTERN.finditer(html):
        for src_match in re.finditer(r'(?i)src\s*=\s*["\']([^"\']+)["\']',
                                     media_match.group(1)):
            add(src_match.group(1))

    add_all(_extract_noscript_template_urls(html, base_url))

    result = list(urls)
    return apply_url_filters(result, include_filters, exclude_filters)


def _looks_like_media_path(candidate: str) -> bool:
    """Loosely match paths like ``/media/12345`` used by extension-less CDNs."""
    segments = [seg for seg in urlparse(candidate).path.lower().split("/") if seg]
    return any(seg in _DIRECT_SEGMENTS for seg in segments[:-1])


def apply_url_filters(urls: list[str], include_filters: list[str] | None,
                      exclude_filters: list[str] | None) -> list[str]:
    """Apply ``*.ext`` include/exclude globs to a list of URLs.

    Exposed publicly so the engine can apply the same rules to assets it finds
    outside the HTML parser (stylesheets, feeds, browser network capture).
    """
    if include_filters:
        urls = [u for u in urls if any(
            fnmatch(urlparse(u).path.lower(), f.lower()) for f in include_filters)]
    if exclude_filters:
        urls = [u for u in urls if not any(
            fnmatch(urlparse(u).path.lower(), f.lower()) for f in exclude_filters)]
    return urls


_apply_filters = apply_url_filters  # backwards-compatible private alias


def _extract_noscript_template_urls(html: str, base_url: str) -> list[str]:
    """Media inside <noscript>/<template>: the real URLs on lazy-loading sites."""
    if not html:
        return []
    found: set[str] = set()
    for pattern in (_NOSCRIPT_PATTERN, _TEMPLATE_PATTERN):
        for match in pattern.finditer(html):
            inner = match.group(1)
            for sub in (URL_PATTERN, SOURCE_TAG_PATTERN, LAZY_LOAD_PATTERN,
                        DATA_IMG_PATTERN, SRCSET_FULL_PATTERN):
                for sub_match in sub.finditer(inner):
                    value = sub_match.group(sub_match.lastindex or 1)
                    if sub is SRCSET_FULL_PATTERN:
                        for parsed in _parse_srcset(value, base_url):
                            found.add(parsed)
                        continue
                    resolved = _normalize_url(value, base_url)
                    if resolved:
                        found.add(resolved)
    return list(found)


def extract_noscript_template_urls(html: str, base_url: str) -> list[str]:
    """Public wrapper around the <noscript>/<template> scan."""
    return _extract_noscript_template_urls(html, base_url)


def extract_inline_base64_images(html: str, output_dir: str | None = None) -> list[dict]:
    """Decode inline ``data:image/...;base64`` payloads, optionally saving them."""
    from pathlib import Path

    results = []
    for match in BASE64_IMG_PATTERN.finditer(html or ""):
        fmt = match.group(1).split("/")[-1].replace("+xml", "").replace("jpg", "jpg")
        payload = re.sub(r"\s+", "", match.group(2))
        try:
            data = base64.b64decode(payload, validate=False)
        except Exception:
            continue
        entry = {"format": fmt, "size": len(data), "data": data, "saved_path": None}
        if output_dir and len(data) > 1024:
            import hashlib

            digest = hashlib.md5(data).hexdigest()[:12]
            fpath = Path(output_dir) / f"inline_{digest}.{fmt}"
            try:
                if not fpath.exists():
                    fpath.write_bytes(data)
                entry["saved_path"] = str(fpath)
            except OSError:
                pass
        results.append(entry)
    return results


def extract_css_urls(css_text: str, base_url: str) -> tuple[list[str], list[str]]:
    """Return ``(media_urls, imported_css_urls)`` for a stylesheet."""
    media: set[str] = set()
    for pattern in (CSS_ANY_URL_PATTERN, CSS_FONT_URL_PATTERN, CSS_BG_PATTERN):
        for match in pattern.finditer(css_text or ""):
            resolved = _normalize_url(match.group(1), base_url)
            if resolved:
                media.add(resolved)

    imports: list[str] = []
    for match in CSS_IMPORT_PATTERN.finditer(css_text or ""):
        resolved = _normalize_url(match.group(1), base_url)
        if resolved and resolved not in imports:
            imports.append(resolved)
    return list(media), imports


# ── Pagination ──────────────────────────────────────────────────────────────

_NEXT_PAGE_PATTERNS = (
    re.compile(r'(?i)<a\s+[^>]*?rel\s*=\s*["\'](?:[^"\']*\s)?next(?:\s[^"\']*)?["\']'
               r'[^>]*?href\s*=\s*["\']([^"\']+)["\']'),
    re.compile(r'(?i)<a\s+[^>]*?href\s*=\s*["\']([^"\']+)["\'][^>]*?rel\s*=\s*["\']'
               r'(?:[^"\']*\s)?next(?:\s[^"\']*)?["\']'),
    re.compile(r'(?i)<link\s+[^>]*?rel\s*=\s*["\']next["\'][^>]*?href\s*=\s*["\']([^"\']+)["\']'),
    re.compile(r'(?i)<a\s+[^>]*?href\s*=\s*["\']([^"\']+)["\'][^>]*>\s*'
               r'(?:下一页|下一頁|后页|後頁|下页|下頁|次页)\s*</a>', re.DOTALL),
    re.compile(r'(?i)<a\s+[^>]*?href\s*=\s*["\']([^"\']+)["\'][^>]*>\s*'
               r'(?:next|next page|older|more|›|»|→|≫|▶|>>|&gt;&gt;|&raquo;)\s*</a>', re.DOTALL),
    re.compile(r'(?i)<a\s+[^>]*?href\s*=\s*["\']([^"\']+)["\'][^>]*?'
               r'class\s*=\s*["\'][^"\']*?(?:next|pagination-next|page-next|btn-next|'
               r'next-page|pager-next)[^"\']*?["\']'),
    re.compile(r'(?i)<a\s+[^>]*?class\s*=\s*["\'][^"\']*?(?:next|pagination-next|page-next|'
               r'next-page|pager-next)[^"\']*?["\'][^>]*?href\s*=\s*["\']([^"\']+)["\']'),
    re.compile(r'(?i)<a\s+[^>]*?href\s*=\s*["\']([^"\']*?[?&](?:page|p|paged|pg|offset|start)='
               r'\d+[^"\']*)["\'][^>]*?class\s*=\s*["\'][^"\']*?next[^"\']*?["\']'),
    re.compile(r'(?i)<a\s+[^>]*?href\s*=\s*["\']([^"\']+)["\'][^>]*>\s*'
               r'(?:第?\s*\d+\s*页?)\s*</a>'),
    re.compile(r'(?i)<a\s+[^>]*?href\s*=\s*["\']([^"\']*/page/\d+/?[^"\']*)["\']'),
)

_PAGE_NUMBER_RE = re.compile(r"(?i)[?&](?:page|p|paged|pg|offset|start)=(\d+)")


def find_next_page_url(html: str, base_url: str,
                       visited: set[str] | None = None) -> str | None:
    """Find the "next page" link, preferring forward-only candidates."""
    current_page = _current_page_number(base_url)

    for pattern in _NEXT_PAGE_PATTERNS:
        for match in pattern.finditer(html or ""):
            url = _normalize_url(match.group(1), base_url)
            if not url or url == base_url:
                continue
            if visited and url in visited:
                continue
            next_page = _current_page_number(url)
            if current_page is not None and next_page is not None and next_page <= current_page:
                continue
            return url
    return None


def _current_page_number(url: str) -> int | None:
    match = _PAGE_NUMBER_RE.search(url)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            return None
    path_match = re.search(r"/page/(\d+)", url)
    if path_match:
        return int(path_match.group(1))
    return None


# ── Link discovery for recursive crawls ─────────────────────────────────────

_LINK_PATTERN = re.compile(r'(?i)<a\s+[^>]*?href\s*=\s*["\']([^"\'#]+)["\']')


def extract_page_links(html: str, base_url: str, same_domain: bool = True,
                       allowed_paths: list[str] | None = None,
                       max_links: int | None = None) -> list[str]:
    """Collect crawlable ``<a href>`` targets, most promising first."""
    base_domain = urlparse(base_url).netloc
    links: list[str] = []
    seen: set[str] = set()

    for match in _LINK_PATTERN.finditer(html or ""):
        raw = match.group(1).strip()
        if raw.startswith(("#", "javascript:")):
            continue
        url = _normalize_url(raw, base_url)
        if not url:
            continue
        parsed = urlparse(url)
        if same_domain and parsed.netloc != base_domain:
            continue

        path_lower = parsed.path.lower()
        if any(path_lower.endswith(ext) for ext in _SKIP_EXTENSIONS):
            continue
        if any(path_lower.endswith(ext) for ext in _HTML_DOC_EXTENSIONS):
            pass  # static pages are still crawlable
        if any(word in path_lower for word in _SKIP_LINK_WORDS):
            continue

        if allowed_paths and not any(
                path_lower.startswith(prefix.lower()) for prefix in allowed_paths):
            continue

        canonical = parsed._replace(fragment="").geturl()
        if canonical in seen or canonical == base_url:
            continue
        seen.add(canonical)
        links.append(canonical)

    if max_links is not None:
        return links[:max_links]
    return links


def extract_iframe_urls(html: str, base_url: str) -> list[str]:
    """Iframe ``src`` values worth rendering or crawling."""
    urls: list[str] = []
    for match in IFRAME_PATTERN.finditer(html or ""):
        resolved = _normalize_url(match.group(1), base_url)
        if resolved and resolved not in urls:
            urls.append(resolved)
    return urls


# ── Meta refresh ────────────────────────────────────────────────────────────

_META_REFRESH_PATTERN = re.compile(
    r'(?i)<meta\s+[^>]*?http-equiv\s*=\s*["\']refresh["\'][^>]*?content\s*=\s*'
    r'["\'][^"\']*?url\s*=\s*([^"\';\s]+)',
    re.DOTALL,
)
_META_REFRESH_PATTERN2 = re.compile(
    r'(?i)<meta\s+[^>]*?content\s*=\s*["\'][^"\']*?url\s*=\s*([^"\';\s]+)[^"\']*?["\']'
    r'[^>]*?http-equiv\s*=\s*["\']refresh["\']',
    re.DOTALL,
)


def find_meta_refresh_url(html: str, base_url: str) -> str | None:
    """Detect ``<meta http-equiv="refresh">`` redirect targets."""
    for pattern in (_META_REFRESH_PATTERN, _META_REFRESH_PATTERN2):
        match = pattern.search(html or "")
        if match:
            resolved = _normalize_url(match.group(1), base_url)
            if resolved:
                return resolved
    return None


# ── PWA manifest ────────────────────────────────────────────────────────────

_MANIFEST_LINK_PATTERN = re.compile(
    r'(?i)<link\s+[^>]*?rel\s*=\s*["\']manifest["\'][^>]*?href\s*=\s*["\']([^"\']+)["\']'
)


def find_manifest_url(html: str, base_url: str) -> str | None:
    match = _MANIFEST_LINK_PATTERN.search(html or "")
    return _normalize_url(match.group(1), base_url) if match else None


# ── Canonicalisation for deduplication ──────────────────────────────────────

_TRACKING_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_id", "utm_source_platform", "utm_creative_format", "utm_name",
    "fbclid", "gclid", "gclsrc", "dclid", "gbraid", "wbraid", "msclkid",
    "twclid", "li_fat_id", "mc_cid", "mc_eid", "igshid", "yclid",
    "ref", "referrer", "source", "spm", "from", "isappinstalled", "scene",
    "clickid", "share_source", "share_medium", "_ga", "_gl",
})


def canonicalize_url(url: str) -> str:
    """Produce a stable key for deduplication (tracking params stripped)."""
    parsed = urlparse(url)
    path = parsed.path.rstrip("/") or "/"
    query = ""
    if parsed.query:
        from urllib.parse import parse_qs, urlencode

        params = parse_qs(parsed.query, keep_blank_values=True)
        clean = {k: v for k, v in params.items() if k.lower() not in _TRACKING_PARAMS}
        query = urlencode(clean, doseq=True) if clean else ""
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{path}" + (
        f"?{query}" if query else "")


# ── Encoding detection ──────────────────────────────────────────────────────

_CHARSET_ALIASES = {
    "gb2312": "gb18030",     # superset, decodes gb2312 and gbk correctly
    "gbk": "gb18030",
    "gb_2312-80": "gb18030",
    "big5": "big5hkscs",     # superset
    "shift_jis": "shift_jis",
    "sjis": "shift_jis",
    "iso-8859-1": "cp1252",  # browsers treat latin-1 as cp1252
    "latin1": "cp1252",
    "ascii": "utf-8",
    "utf8": "utf-8",
}

# Common Chinese/Japanese pages frequently mislabel their charset; if we see
# this many multi-byte sequences we prefer a UTF-8 decode.
_CHARSET_META_RE = re.compile(
    rb'(?i)<meta[^>]+charset\s*=\s*["\']?\s*([a-zA-Z0-9_\-]+)')
_CHARSET_HTTP_EQUIV_RE = re.compile(
    rb'(?i)<meta[^>]+content\s*=\s*["\'][^"\']*charset\s*=\s*([a-zA-Z0-9_\-]+)')


def detect_encoding(resp_headers: dict, body: bytes) -> str:
    """Pick a decoding for a response body.

    Order: explicit header charset → HTML ``<meta charset>`` → BOM → UTF-8.
    Alias mapping means ``gb2312``/``gbk`` decode as ``gb18030`` (a superset)
    and ``iso-8859-1`` as ``cp1252``, which is what browsers do.
    """
    headers_lower = {str(k).lower(): v for k, v in (resp_headers or {}).items()}
    content_type = headers_lower.get("content-type", "") or ""
    match = re.search(r"charset\s*=\s*([^\s;]+)", content_type, re.IGNORECASE)
    if match:
        return _canonical_charset(match.group(1).strip().strip("\"'"))

    head = (body or b"")[:4096]
    for pattern in (_CHARSET_META_RE, _CHARSET_HTTP_EQUIV_RE):
        meta = pattern.search(head)
        if meta:
            return _canonical_charset(meta.group(1).decode("ascii", errors="ignore"))

    if body:
        if body.startswith(b"\xef\xbb\xbf"):
            return "utf-8-sig"
        if body.startswith(b"\xff\xfe\x00\x00"):
            return "utf-32-le"
        if body.startswith(b"\x00\x00\xfe\xff"):
            return "utf-32-be"
        if body.startswith(b"\xff\xfe"):
            return "utf-16-le"
        if body.startswith(b"\xfe\xff"):
            return "utf-16-be"

    return "utf-8"


def _canonical_charset(name: str) -> str:
    lowered = name.strip().lower()
    if not lowered:
        return "utf-8"
    return _CHARSET_ALIASES.get(lowered, lowered)


def decode_body(body: bytes, resp_headers: dict | None = None) -> tuple[str, str]:
    """Decode a response body, falling back gracefully on bad bytes."""
    encoding = detect_encoding(resp_headers or {}, body)
    try:
        return body.decode(encoding, errors="replace"), encoding
    except (LookupError, UnicodeDecodeError):
        return body.decode("utf-8", errors="replace"), "utf-8"


# ── Content-Type → extension ────────────────────────────────────────────────

_CT_EXTENSION_MAP = {
    "image/jpeg": ".jpg", "image/jpg": ".jpg", "image/png": ".png",
    "image/gif": ".gif", "image/webp": ".webp", "image/svg+xml": ".svg",
    "image/avif": ".avif", "image/bmp": ".bmp", "image/tiff": ".tiff",
    "image/heic": ".heic", "image/x-icon": ".ico",
    "video/mp4": ".mp4", "video/webm": ".webm", "video/x-flv": ".flv",
    "video/x-matroska": ".mkv", "video/quicktime": ".mov", "video/mp2t": ".ts",
    "video/x-msvideo": ".avi",
    "audio/mpeg": ".mp3", "audio/ogg": ".ogg", "audio/wav": ".wav",
    "audio/x-wav": ".wav", "audio/flac": ".flac", "audio/aac": ".aac",
    "audio/mp4": ".m4a", "audio/opus": ".opus",
    "application/pdf": ".pdf", "application/zip": ".zip",
    "application/x-rar-compressed": ".rar", "application/vnd.rar": ".rar",
    "application/x-7z-compressed": ".7z", "application/gzip": ".gz",
    "application/x-tar": ".tar", "application/epub+zip": ".epub",
    "application/vnd.apple.mpegurl": ".m3u8", "application/x-mpegurl": ".m3u8",
    "application/dash+xml": ".mpd",
    "font/woff": ".woff", "font/woff2": ".woff2", "font/ttf": ".ttf",
    "font/otf": ".otf", "application/font-woff": ".woff",
    "application/font-woff2": ".woff2",
}


def guess_extension_from_content_type(content_type: str) -> str | None:
    """Guess a file extension from a Content-Type header."""
    if not content_type:
        return None
    return _CT_EXTENSION_MAP.get(content_type.split(";")[0].strip().lower())
