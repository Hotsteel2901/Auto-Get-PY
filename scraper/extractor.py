import re
from urllib.parse import urljoin, urlparse
from fnmatch import fnmatch


MEDIA_EXTENSIONS = (
    # Images
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp", ".ico", ".avif", ".heic",
    # Videos
    ".mp4", ".mkv", ".webm", ".avi", ".mov", ".flv", ".wmv", ".ts", ".m3u8",
    # Audio
    ".mp3", ".wav", ".flac", ".aac", ".ogg", ".wma", ".m4a", ".opus",
    # Documents
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".epub",
    # Archives
    ".zip", ".rar", ".7z", ".tar", ".gz",
)

URL_PATTERN = re.compile(
    r"""(?i)(?:src|href|data-src|data-url|content)\s*=\s*["']([^"']+\.(?:"""
    + "|".join(ext.strip(".") for ext in MEDIA_EXTENSIONS)
    + r"""))["']"""
)

M3U8_PATTERN = re.compile(r'["\']([^"\']+\.m3u8[^"\']*)["\']')

GENERIC_URL_PATTERN = re.compile(
    r'(?i)(?:src|href|data-src|data-url)\s*=\s*["\']([^"\']+)["\']'
)


def _is_media_url(url: str) -> bool:
    """Check if URL points to a media file based on extension."""
    parsed = urlparse(url)
    path = parsed.path.lower()
    return any(path.endswith(ext) for ext in MEDIA_EXTENSIONS)


_DIRECT_SEGMENTS = frozenset({
    "download", "file", "files", "attachment", "attachments",
    "media", "video", "audio", "image",
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


def extract_media_urls(html: str, base_url: str,
                       include_filters: list[str] = None,
                       exclude_filters: list[str] = None) -> list[str]:
    urls = set()
    
    for match in URL_PATTERN.finditer(html):
        url = match.group(1)
        full_url = urljoin(base_url, url)
        urls.add(full_url)
    
    for match in M3U8_PATTERN.finditer(html):
        urls.add(urljoin(base_url, match.group(1)))
    
    for match in GENERIC_URL_PATTERN.finditer(html):
        url = match.group(1)
        if not url.startswith(('http://', 'https://', '//')):
            continue
        if url.endswith(('.html', '.htm', '.php', '.asp', '.aspx', '.jsp')):
            continue
        if '#' in url and not url.endswith(('.m3u8',)):
            continue
        full_url = urljoin(base_url, url)
        if _is_direct_link(full_url):
            urls.add(full_url)

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
