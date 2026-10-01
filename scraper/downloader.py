"""File download engine.

Handles three shapes of media:

* **Plain files** — streamed to disk in chunks with resume support.
* **HLS (``.m3u8``)** — master playlists resolve to their highest-quality
  variant, AES-128/256 encrypted segments are decrypted, ``EXT-X-BYTERANGE``
  slices and fMP4 ``EXT-X-MAP`` init segments are honoured, and every segment
  is concatenated into one playable file.
* **DASH (``.mpd``)** — ``SegmentTemplate`` (``$Number$``/``$Time$`` with
  ``SegmentTimeline``), ``SegmentList`` and single-file representations are
  expanded and concatenated.

Downloads are incremental and resumable: a partially written file is reported
as a failure with its byte count preserved, and a later retry continues from
where it stopped.  Retries of a *completed* name overwrite rather than
accumulate ``(1)``/``(2)`` copies.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import shutil
import time
from pathlib import Path
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import aiofiles
import aiohttp

logger = logging.getLogger(__name__)

CHUNK_SIZE = 64 * 1024
DEFAULT_TIMEOUT = 30
PROGRESS_INTERVAL = 0.25  # seconds between progress callbacks

_EXTENSION_RE = re.compile(r"\.[A-Za-z0-9]{1,5}$")

# Query parameters that commonly carry a filename.
_NAME_PARAM_HINTS = frozenset({
    "file", "filename", "name", "url", "path", "src", "download",
    "attachment", "doc", "media", "video", "image",
})

_MIME_EXTENSIONS = {
    "image/jpeg": ".jpg", "image/jpg": ".jpg", "image/png": ".png",
    "image/gif": ".gif", "image/webp": ".webp", "image/svg+xml": ".svg",
    "image/avif": ".avif", "image/bmp": ".bmp", "image/tiff": ".tiff",
    "image/heic": ".heic", "image/x-icon": ".ico", "image/vnd.microsoft.icon": ".ico",
    "video/mp4": ".mp4", "video/webm": ".webm", "video/x-flv": ".flv",
    "video/x-matroska": ".mkv", "video/quicktime": ".mov", "video/mp2t": ".ts",
    "video/x-msvideo": ".avi", "video/mpeg": ".mpeg",
    "audio/mpeg": ".mp3", "audio/mp3": ".mp3", "audio/ogg": ".ogg",
    "audio/wav": ".wav", "audio/x-wav": ".wav", "audio/flac": ".flac",
    "audio/aac": ".aac", "audio/mp4": ".m4a", "audio/x-m4a": ".m4a",
    "audio/opus": ".opus", "audio/webm": ".weba",
    "application/pdf": ".pdf", "application/zip": ".zip",
    "application/x-rar-compressed": ".rar", "application/vnd.rar": ".rar",
    "application/x-7z-compressed": ".7z", "application/gzip": ".gz",
    "application/x-tar": ".tar", "application/x-bzip2": ".bz2",
    "application/epub+zip": ".epub", "application/json": ".json",
    "application/vnd.apple.mpegurl": ".m3u8", "application/x-mpegurl": ".m3u8",
    "application/dash+xml": ".mpd", "text/vtt": ".vtt", "application/x-subrip": ".srt",
    "font/woff": ".woff", "font/woff2": ".woff2", "font/ttf": ".ttf",
    "font/otf": ".otf", "application/font-woff": ".woff",
    "application/vnd.ms-fontobject": ".eot",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.ms-powerpoint": ".ppt",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
}

_PLAYLIST_MIMES = frozenset({
    "application/vnd.apple.mpegurl", "application/x-mpegurl",
    "audio/mpegurl", "audio/x-mpegurl",
})


def extension_for_content_type(content_type: str | None) -> str | None:
    """Map a MIME type to a file extension, ignoring parameters."""
    if not content_type:
        return None
    return _MIME_EXTENSIONS.get(content_type.split(";")[0].strip().lower())


class DownloadResult(dict):
    """A dict that also exposes a convenient ``ok`` flag."""

    @property
    def ok(self) -> bool:
        return self.get("status") == "completed"


class _ProgressPump:
    """Rate-limits progress callbacks so the database isn't hit per chunk."""

    def __init__(self, callback, min_interval: float = PROGRESS_INTERVAL):
        self._cb = callback
        self._interval = min_interval
        self._last = 0.0

    async def __call__(self, downloaded: int, total: int | None,
                       force: bool = False) -> None:
        if self._cb is None:
            return
        now = time.monotonic()
        if not force and now - self._last < self._interval:
            return
        self._last = now
        await self._cb(downloaded, total)


class Downloader:
    """Streams remote files to disk. One instance can serve a whole task."""

    CHUNK_SIZE = CHUNK_SIZE

    def __init__(self, output_dir: str = "./downloads"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    # ── Naming helpers ──────────────────────────────────────────────────────

    @staticmethod
    def sanitize_filename(filename: str, max_length: int = 180) -> str:
        """Strip characters that are illegal on Windows and trim length."""
        if not filename:
            return "unnamed"
        name = unquote(filename).replace("\\", "/").split("/")[-1]
        name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
        name = re.sub(r"\s+", " ", name).strip(" .")
        if not name:
            return "unnamed"
        if len(name) > max_length:
            suffix = Path(name).suffix[:12]
            name = name[: max_length - len(suffix)] + suffix
        return name

    @staticmethod
    def _name_from_query(query: str) -> str | None:
        """Pull a filename out of ``?file=video.mp4`` style queries."""
        if not query:
            return None
        for key, values in parse_qs(query, keep_blank_values=False).items():
            if key.lower() not in _NAME_PARAM_HINTS:
                continue
            for value in values:
                candidate = unquote(value).replace("\\", "/").split("/")[-1]
                if _EXTENSION_RE.search(candidate) and len(candidate) < 150:
                    return candidate
        return None

    @staticmethod
    def extract_filename(url: str) -> str:
        """Best-effort filename for a URL: path name, then query, then hash."""
        parsed = urlparse(url)
        raw_name = unquote(Path(parsed.path).name)

        if raw_name and raw_name not in ("/", ".") and _EXTENSION_RE.search(raw_name):
            return Downloader.sanitize_filename(raw_name)

        from_query = Downloader._name_from_query(parsed.query)
        if from_query:
            return Downloader.sanitize_filename(from_query)

        if raw_name and raw_name not in ("/", ".") and len(raw_name) > 2:
            base = Downloader.sanitize_filename(raw_name)
            return base if "." in base else base + Downloader._guess_ext_from_text(url)

        digest = hashlib.sha1(url.encode("utf-8", "replace")).hexdigest()[:16]
        return f"{digest}{Downloader._guess_ext_from_text(url)}"

    @staticmethod
    def _guess_ext_from_text(text: str) -> str:
        """Find a known extension in the text, respecting token boundaries."""
        from scraper.extractor import MEDIA_EXTENSIONS

        lowered = text.lower()
        best, best_pos = "", len(lowered)
        for ext in MEDIA_EXTENSIONS:
            pos = lowered.find(ext)
            while pos != -1:
                after = lowered[pos + len(ext): pos + len(ext) + 1]
                if after in ("", "?", "&", "#", "/"):
                    if pos < best_pos:
                        best, best_pos = ext, pos
                    break
                pos = lowered.find(ext, pos + 1)
        return best or ".bin"

    @staticmethod
    def _resolve_conflict(filepath: Path) -> Path:
        """Append ``(1)``, ``(2)``… when the target already exists."""
        if not filepath.exists():
            return filepath
        stem, suffix, parent = filepath.stem, filepath.suffix, filepath.parent
        counter = 1
        while True:
            candidate = parent / f"{stem}({counter}){suffix}"
            if not candidate.exists():
                return candidate
            counter += 1

    @staticmethod
    def _check_disk_space(path: str, min_mb: int = 50) -> bool:
        try:
            return shutil.disk_usage(path).free / (1024 * 1024) > min_mb
        except Exception:
            return True

    @staticmethod
    def _content_disposition_name(header: str | None) -> str | None:
        """Parse RFC 5987 / RFC 6266 Content-Disposition filenames."""
        if not header:
            return None
        match = re.search(r"filename\*\s*=\s*([^;]+)", header, re.IGNORECASE)
        if match:
            value = match.group(1).strip().strip("\"'")
            if "''" in value:
                value = value.split("''", 1)[1]
            try:
                return unquote(value, encoding="utf-8") or None
            except Exception:
                return value or None
        match = (re.search(r'filename\s*=\s*"([^"]*)"', header, re.IGNORECASE)
                 or re.search(r"filename\s*=\s*([^;\s]+)", header, re.IGNORECASE))
        if match:
            return match.group(1).strip().strip("\"'") or None
        return None

    # ── Session handling ────────────────────────────────────────────────────

    @staticmethod
    def create_session() -> aiohttp.ClientSession:
        """A session with a persistent cookie jar and connection pooling."""
        return aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(limit=64, ttl_dns_cache=300),
            cookie_jar=aiohttp.CookieJar(unsafe=True),
            trust_env=True,
        )

    # ── Public entry point ──────────────────────────────────────────────────

    async def download_file(
        self,
        url: str,
        output_dir: str | None = None,
        filename: str | None = None,
        task_id: int | None = None,
        dl_id: int | None = None,
        progress_callback=None,
        headers: dict | None = None,
        timeout: int = DEFAULT_TIMEOUT,
        resume_from: int = 0,
        proxy: str | None = None,
        max_file_size_mb: int | None = None,
        session: aiohttp.ClientSession | None = None,
        referer: str | None = None,
        allow_playlists: bool = True,
    ) -> DownloadResult:
        """Download ``url`` and return a result dict.

        ``session`` may be shared across a whole task so that cookies picked up
        while crawling are replayed for the media requests that need them.
        ``progress_callback`` receives ``(dl_id, downloaded, total)``.
        """
        del task_id  # accepted for API compatibility; dl_id is what identifies a row

        out_dir = Path(output_dir) if output_dir else self.output_dir
        out_dir.mkdir(parents=True, exist_ok=True)

        if not self._check_disk_space(str(out_dir)):
            return DownloadResult(status="failed",
                                  error_msg="Disk space critically low (< 50 MB free)")

        own_session = session is None
        if own_session:
            session = self.create_session()

        async def on_progress(downloaded: int, total: int | None) -> None:
            if progress_callback is None:
                return
            await progress_callback(dl_id, downloaded, total)

        pump = _ProgressPump(on_progress if progress_callback else None)

        # The Referer must be present for the *probe* as well as the transfer:
        # hotlink-protected hosts reject the HEAD request too, which would
        # otherwise abort the download before it starts.
        request_headers = dict(headers or {})
        if referer:
            request_headers.setdefault("Referer", referer)

        try:
            probe = await self._probe(url, request_headers, timeout, session)
            if isinstance(probe, DownloadResult):
                return probe
            content_type, final_url, disposition, _ = probe

            if resume_from > 0 and filename:
                # Continue the exact file the previous attempt was writing.
                out_name = self.sanitize_filename(filename)
            else:
                resume_from = 0
                out_name = self._pick_filename(
                    final_url, filename, disposition, content_type)

            if allow_playlists:
                if _is_hls(content_type, final_url):
                    return await self._download_hls(
                        final_url, out_dir, out_name, request_headers, timeout, session,
                        max_file_size_mb, referer, pump, explicit=bool(filename))
                if _is_dash(content_type, final_url):
                    return await self._download_dash(
                        final_url, out_dir, out_name, request_headers, timeout, session,
                        max_file_size_mb, referer, pump, explicit=bool(filename))

            return await self._download_plain(
                final_url, out_dir, out_name, request_headers, timeout, session,
                resume_from, max_file_size_mb, content_type, referer, pump,
                explicit=bool(filename))

        except asyncio.TimeoutError:
            return DownloadResult(status="failed", error_msg="Timeout")
        except aiohttp.ClientError as exc:
            return DownloadResult(status="failed", error_msg=f"Network error: {exc}")
        except Exception as exc:  # noqa: BLE001 - surfaced to the caller as an error
            logger.exception("Unexpected download error for %s", url)
            return DownloadResult(status="failed", error_msg=str(exc))
        finally:
            if own_session:
                await session.close()

    # ── Filename resolution ─────────────────────────────────────────────────

    def _pick_filename(self, url: str, provided: str | None, disposition: str | None,
                       content_type: str | None) -> str:
        """Choose the best filename from headers, then the URL, then the MIME."""
        url_name = self.extract_filename(url)

        chosen = None
        cd_name = self._content_disposition_name(disposition)
        if cd_name:
            candidate = self.sanitize_filename(cd_name)
            if candidate and candidate != "unnamed":
                chosen = candidate
        if not chosen:
            chosen = self.sanitize_filename(provided) if provided else url_name

        # Give a real extension to extension-less or `.bin` names.
        if not _EXTENSION_RE.search(chosen) or chosen.endswith(".bin"):
            by_mime = extension_for_content_type(content_type)
            by_url = self._guess_ext_from_text(url)
            ext = by_mime or (by_url if by_url != ".bin" else "")
            if ext:
                stem = chosen[:-4] if chosen.endswith(".bin") else chosen
                chosen = f"{stem}{ext}"

        return chosen or url_name

    # ── Probing ─────────────────────────────────────────────────────────────

    async def _probe(self, url: str, headers: dict | None, timeout: int,
                     session: aiohttp.ClientSession):
        """Learn the type of a URL without pulling its body."""
        try:
            async with session.head(
                url, headers=dict(headers or {}), allow_redirects=True,
                timeout=aiohttp.ClientTimeout(total=min(timeout, 15)),
            ) as resp:
                if resp.status < 400 and resp.status not in (405, 501):
                    return (
                        resp.headers.get("Content-Type", ""),
                        str(resp.url),
                        resp.headers.get("Content-Disposition", ""),
                        resp.content_length,
                    )
        except (aiohttp.ClientError, asyncio.TimeoutError):
            pass
        return await self._probe_get(url, headers, timeout, session)

    async def _probe_get(self, url: str, headers: dict | None, timeout: int,
                         session: aiohttp.ClientSession):
        """Ask for a single byte: enough for the headers, cheap on bandwidth."""
        req_headers = dict(headers or {})
        req_headers["Range"] = "bytes=0-0"
        async with session.get(
            url, headers=req_headers, allow_redirects=True,
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as resp:
            if resp.status == 429:
                wait = self._retry_after(resp)
                return DownloadResult(
                    status="failed",
                    error_msg=f"HTTP 429 (rate limited, Retry-After: {wait}s)",
                    retry_after=wait,
                )
            if resp.status >= 400:
                return DownloadResult(status="failed", error_msg=f"HTTP {resp.status}")

            content_range = resp.headers.get("Content-Range", "")
            total = resp.content_length
            if "/" in content_range:
                try:
                    total = int(content_range.rsplit("/", 1)[1])
                except ValueError:
                    total = None
            resp.release()
            return (
                resp.headers.get("Content-Type", ""),
                str(resp.url),
                resp.headers.get("Content-Disposition", ""),
                total,
            )

    @staticmethod
    def _retry_after(resp: aiohttp.ClientResponse) -> int:
        try:
            return max(1, int(resp.headers.get("Retry-After", "")))
        except (TypeError, ValueError):
            return 30

    # ── Plain download ──────────────────────────────────────────────────────

    async def _download_plain(
        self, url: str, out_dir: Path, fname: str, headers: dict | None, timeout: int,
        session: aiohttp.ClientSession, resume_from: int, max_file_size_mb: int | None,
        content_type: str, referer: str | None, pump: _ProgressPump, explicit: bool,
    ) -> DownloadResult:
        filepath = out_dir / fname
        req_headers = dict(headers or {})
        if referer:
            req_headers.setdefault("Referer", referer)

        if resume_from > 0 and filepath.exists():
            req_headers["Range"] = f"bytes={resume_from}-"
        else:
            resume_from = 0
            # A caller-supplied name is authoritative: retries overwrite it.
            if not explicit:
                filepath = self._resolve_conflict(filepath)

        max_bytes = max_file_size_mb * 1024 * 1024 if max_file_size_mb else None

        async with session.get(
            url, headers=req_headers, allow_redirects=True,
            timeout=aiohttp.ClientTimeout(total=timeout, sock_read=timeout),
        ) as resp:
            if resp.status == 429:
                wait = self._retry_after(resp)
                return DownloadResult(
                    status="failed",
                    error_msg=f"HTTP 429 (rate limited, Retry-After: {wait}s)",
                    retry_after=wait,
                )
            if resp.status not in (200, 206):
                return DownloadResult(status="failed", error_msg=f"HTTP {resp.status}")

            if resume_from > 0 and resp.status != 206:
                # Server ignored the Range header: start over cleanly.
                resume_from = 0
                filepath = out_dir / fname
                if not explicit:
                    filepath = self._resolve_conflict(filepath)

            total = resp.content_length
            if total is not None and resume_from:
                total += resume_from

            if max_bytes and total and total > max_bytes:
                return DownloadResult(
                    status="failed",
                    error_msg=(f"File too large: {total / 1048576:.1f} MB > "
                               f"{max_file_size_mb} MB limit"),
                )

            mode = "ab" if resume_from > 0 else "wb"
            downloaded = resume_from
            try:
                async with aiofiles.open(filepath, mode) as handle:
                    async for chunk in resp.content.iter_chunked(self.CHUNK_SIZE):
                        downloaded += len(chunk)
                        if max_bytes and downloaded > max_bytes:
                            await handle.close()
                            self._discard(filepath)
                            return DownloadResult(
                                status="failed",
                                error_msg=(f"File exceeded the {max_file_size_mb} MB "
                                           f"limit during download"),
                            )
                        await handle.write(chunk)
                        await pump(downloaded, total)
            except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as exc:
                # Keep the partial file so the next attempt can resume it.
                return DownloadResult(
                    status="failed",
                    error_msg=f"Interrupted after {downloaded} bytes: {exc}",
                    partial_bytes=downloaded,
                )

        if total and downloaded < total:
            return DownloadResult(
                status="failed",
                error_msg=f"Incomplete: got {downloaded} of {total} bytes",
                partial_bytes=downloaded,
            )

        await pump(downloaded, downloaded, force=True)
        return DownloadResult(
            status="completed",
            file_size=downloaded,
            filename=filepath.name,
            filepath=str(filepath),
            mime_type=(content_type or "").split(";")[0] or None,
        )

    @staticmethod
    def _discard(path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass

    async def _fetch_text(self, url: str, headers: dict | None, timeout: int,
                          session: aiohttp.ClientSession) -> str | None:
        try:
            async with session.get(
                url, headers=dict(headers or {}), allow_redirects=True,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                if resp.status >= 400:
                    return None
                return await resp.text(errors="replace")
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return None

    async def _fetch_bytes(self, url: str, headers: dict | None, timeout: int,
                           session: aiohttp.ClientSession, referer: str | None = None,
                           byte_range: tuple[int, int] | None = None) -> bytes | None:
        req_headers = dict(headers or {})
        if referer:
            req_headers.setdefault("Referer", referer)
        if byte_range:
            req_headers["Range"] = f"bytes={byte_range[0]}-{byte_range[1]}"
        try:
            async with session.get(
                url, headers=req_headers, allow_redirects=True,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                if resp.status >= 400:
                    logger.debug("Segment fetch failed (%s): %s", resp.status, url)
                    return None
                return await resp.read()
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            logger.debug("Segment fetch error for %s: %s", url, exc)
            return None

    # ── HLS ─────────────────────────────────────────────────────────────────

    async def _download_hls(
        self, url: str, out_dir: Path, fname: str, headers: dict | None, timeout: int,
        session: aiohttp.ClientSession, max_file_size_mb: int | None,
        referer: str | None, pump: _ProgressPump, explicit: bool,
    ) -> DownloadResult:
        text = await self._fetch_text(url, headers, timeout, session)
        if text is None:
            return DownloadResult(status="failed", error_msg="Could not fetch the HLS playlist")

        variants = parse_hls_master(text, url)
        if variants:
            best = max(variants, key=lambda v: (v["bandwidth"], v["height"]))
            return await self._download_hls(
                best["url"], out_dir, playlist_output_name(fname, best["url"]),
                headers, timeout, session, max_file_size_mb, referer, pump, explicit)

        media = parse_hls_media(text, url)
        if not media["segments"]:
            return await self._download_plain(
                url, out_dir, fname, headers, timeout, session, 0,
                max_file_size_mb, "application/vnd.apple.mpegurl", referer, pump, explicit)

        out_name = playlist_output_name(fname, url, fragmented=bool(media["init_url"]))
        filepath = out_dir / out_name if explicit else self._resolve_conflict(out_dir / out_name)

        downloaded = 0
        max_bytes = max_file_size_mb * 1024 * 1024 if max_file_size_mb else None
        # Playlists do not publish per-segment sizes, so the total stays
        # unknown and the UI shows a byte counter instead of a percentage.
        key_cache: dict[str, bytes] = {}

        try:
            async with aiofiles.open(filepath, "wb") as handle:
                if media["init_url"]:
                    init = await self._fetch_bytes(
                        media["init_url"], headers, timeout, session, referer)
                    if init is None:
                        self._discard(filepath)
                        return DownloadResult(
                            status="failed",
                            error_msg="Failed to fetch the HLS init segment")
                    await handle.write(init)
                    downloaded += len(init)

                for index, segment in enumerate(media["segments"]):
                    data = await self._fetch_bytes(
                        segment["url"], headers, timeout, session, referer,
                        byte_range=segment.get("range"))
                    if data is None:
                        self._discard(filepath)
                        return DownloadResult(
                            status="failed",
                            error_msg=(f"HLS segment {index + 1}/{len(media['segments'])} "
                                       f"failed: {segment['url']}"),
                        )

                    if segment.get("key_url"):
                        key = await self._hls_key(segment["key_url"], headers, timeout,
                                                  session, key_cache)
                        if key is None:
                            self._discard(filepath)
                            return DownloadResult(
                                status="failed",
                                error_msg="Failed to fetch the HLS AES key")
                        data = decrypt_hls_segment(
                            data, key, segment.get("key_iv"), segment["sequence"])

                    downloaded += len(data)
                    if max_bytes and downloaded > max_bytes:
                        await handle.close()
                        self._discard(filepath)
                        return DownloadResult(
                            status="failed",
                            error_msg=(f"Stream exceeded the {max_file_size_mb} MB limit"),
                        )
                    await handle.write(data)
                    await pump(downloaded, None)
        except OSError as exc:
            self._discard(filepath)
            return DownloadResult(status="failed", error_msg=f"Write failed: {exc}")

        await pump(downloaded, downloaded, force=True)
        return DownloadResult(
            status="completed",
            file_size=downloaded,
            filename=filepath.name,
            filepath=str(filepath),
            mime_type="video/mp2t" if not media["init_url"] else "video/mp4",
            segments=len(media["segments"]),
        )

    async def _hls_key(self, key_url: str, headers, timeout, session,
                       cache: dict[str, bytes]) -> bytes | None:
        if key_url in cache:
            return cache[key_url]
        data = await self._fetch_bytes(key_url, headers, timeout, session)
        if data is not None:
            cache[key_url] = data
        return data

    # ── DASH ────────────────────────────────────────────────────────────────

    async def _download_dash(
        self, url: str, out_dir: Path, fname: str, headers: dict | None, timeout: int,
        session: aiohttp.ClientSession, max_file_size_mb: int | None,
        referer: str | None, pump: _ProgressPump, explicit: bool,
    ) -> DownloadResult:
        text = await self._fetch_text(url, headers, timeout, session)
        if text is None:
            return DownloadResult(status="failed", error_msg="Could not fetch the DASH manifest")

        plan = parse_dash_manifest(text, url)
        if not plan or not plan["segments"]:
            return await self._download_plain(
                url, out_dir, fname, headers, timeout, session, 0,
                max_file_size_mb, "application/dash+xml", referer, pump, explicit)

        out_name = f"{Path(fname).stem or 'stream'}.mp4"
        filepath = out_dir / out_name if explicit else self._resolve_conflict(out_dir / out_name)
        downloaded = 0
        max_bytes = max_file_size_mb * 1024 * 1024 if max_file_size_mb else None

        try:
            async with aiofiles.open(filepath, "wb") as handle:
                if plan["init_url"]:
                    init = await self._fetch_bytes(plan["init_url"], headers, timeout,
                                                   session, referer)
                    if init:
                        await handle.write(init)
                        downloaded += len(init)

                for index, segment_url in enumerate(plan["segments"]):
                    data = await self._fetch_bytes(segment_url, headers, timeout,
                                                   session, referer)
                    if data is None:
                        self._discard(filepath)
                        return DownloadResult(
                            status="failed",
                            error_msg=(f"DASH segment {index + 1}/{len(plan['segments'])} "
                                       f"failed"),
                        )
                    downloaded += len(data)
                    if max_bytes and downloaded > max_bytes:
                        await handle.close()
                        self._discard(filepath)
                        return DownloadResult(
                            status="failed",
                            error_msg=(f"Stream exceeded the {max_file_size_mb} MB limit"),
                        )
                    await handle.write(data)
                    await pump(downloaded, downloaded)
        except OSError as exc:
            self._discard(filepath)
            return DownloadResult(status="failed", error_msg=f"Write failed: {exc}")

        await pump(downloaded, downloaded, force=True)
        return DownloadResult(
            status="completed",
            file_size=downloaded,
            filename=filepath.name,
            filepath=str(filepath),
            mime_type="video/mp4",
            segments=len(plan["segments"]),
        )


# ── Format detection ────────────────────────────────────────────────────────


def _is_hls(content_type: str | None, url: str) -> bool:
    mime = (content_type or "").split(";")[0].strip().lower()
    return urlparse(url).path.lower().endswith((".m3u8", ".m3u")) or mime in _PLAYLIST_MIMES


def _is_dash(content_type: str | None, url: str) -> bool:
    mime = (content_type or "").split(";")[0].strip().lower()
    return urlparse(url).path.lower().endswith(".mpd") or mime == "application/dash+xml"


def playlist_output_name(fname: str, url: str, fragmented: bool = False) -> str:
    """Name the file that a playlist's segments are merged into."""
    stem = Path(fname).stem or "stream"
    path = urlparse(url).path.lower()
    if fragmented or path.endswith((".m4s", ".mp4")):
        return f"{stem}.mp4"
    return f"{stem}.ts"


# ── HLS playlist parsing ────────────────────────────────────────────────────


def parse_hls_master(text: str, base_url: str) -> list[dict]:
    """Return the variants of a master playlist, with their bandwidth."""
    variants: list[dict] = []
    pending: dict | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or (line.startswith("#") and not line.startswith("#EXT-X-STREAM-INF:")):
            continue
        if line.startswith("#EXT-X-STREAM-INF:"):
            attrs = parse_attribute_list(line.split(":", 1)[1])
            resolution = attrs.get("RESOLUTION", "")
            pending = {
                "bandwidth": _to_int(attrs.get("BANDWIDTH")) or 0,
                "height": _to_int(resolution.split("x")[-1]) if "x" in resolution else 0,
            }
        elif pending is not None:
            pending["url"] = urljoin(base_url, line)
            variants.append(pending)
            pending = None
    return variants


def parse_hls_media(text: str, base_url: str) -> dict:
    """Expand a media playlist into a concrete, per-segment keyed, segment list."""
    segments: list[dict] = []
    current_range: tuple[int, int] | None = None
    offset = 0
    total_duration = 0.0
    init_url: str | None = None
    bytes_range_used = False

    active_key_url: str | None = None
    active_key_iv: str | None = None
    sequence = 0

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#EXTINF:"):
            total_duration += _to_float(line.split(":", 1)[1].split(",")[0]) or 0.0
        elif line.startswith("#EXT-X-BYTERANGE:"):
            length, _, start = line.split(":", 1)[1].partition("@")
            seg_len = _to_int(length) or 0
            seg_start = _to_int(start) if start else offset
            current_range = (seg_start, seg_start + seg_len - 1)
            offset = seg_start + seg_len
            bytes_range_used = True
        elif line.startswith("#EXT-X-MAP:"):
            attrs = parse_attribute_list(line.split(":", 1)[1])
            if attrs.get("URI"):
                init_url = urljoin(base_url, attrs["URI"])
        elif line.startswith("#EXT-X-KEY:"):
            attrs = parse_attribute_list(line.split(":", 1)[1])
            method = (attrs.get("METHOD") or "").upper()
            if method in ("AES-128", "AES-256"):
                active_key_url = urljoin(base_url, attrs["URI"]) if attrs.get("URI") else None
                active_key_iv = attrs.get("IV")
            elif method == "NONE":
                active_key_url = None
                active_key_iv = None
        elif not line.startswith("#"):
            segments.append({
                "url": urljoin(base_url, line),
                "range": current_range,
                "key_url": active_key_url,
                "key_iv": active_key_iv,
                "sequence": sequence,
            })
            sequence += 1
            current_range = None

    return {
        "segments": segments,
        "init_url": init_url,
        "total_duration": total_duration,
        "bytes_range_used": bytes_range_used,
    }


def decrypt_hls_segment(data: bytes, key: bytes, iv_spec: str | None,
                        sequence: int) -> bytes:
    """AES-CBC decrypt one HLS segment, honouring the explicit IV or sequence."""
    if not key:
        return data
    try:
        from Crypto.Cipher import AES
        from Crypto.Util.Padding import unpad
    except ImportError:
        logger.warning("pycryptodome missing; keeping the HLS segment encrypted")
        return data

    iv = None
    if iv_spec:
        raw_iv = iv_spec[2:] if iv_spec.lower().startswith("0x") else iv_spec
        try:
            iv = bytes.fromhex(raw_iv)
        except ValueError:
            iv = None
    if iv is None:
        iv = sequence.to_bytes(16, "big")
    if len(iv) != 16:
        iv = iv[:16].ljust(16, b"\0")

    key_size = 32 if len(key) >= 32 else 16
    try:
        cipher = AES.new(key[:key_size], AES.MODE_CBC, iv)
        return unpad(cipher.decrypt(data), AES.block_size)
    except Exception as exc:  # noqa: BLE001 - wrong key or invalid padding
        logger.debug("HLS segment decrypt failed (seq %s): %s", sequence, exc)
        return data


def parse_attribute_list(text: str) -> dict:
    """Parse ``KEY=VALUE,KEY="VALUE"`` attribute lists used by HLS and DASH."""
    attrs: dict[str, str] = {}
    for match in re.finditer(r'([A-Za-z0-9\-_]+)\s*=\s*("([^"]*)"|[^,]*)', text):
        value = match.group(3) if match.group(3) is not None else match.group(2)
        attrs[match.group(1).upper()] = value.strip()
    return attrs


def _to_int(value) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _to_float(value) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


# ── DASH manifest parsing ───────────────────────────────────────────────────


def parse_dash_manifest(text: str, base_url: str) -> dict | None:
    """Expand a DASH manifest into a concrete segment list.

    Covers the two shapes behind almost every real manifest:
    ``SegmentTemplate`` with ``$Number$``/``$Time$`` placeholders (optionally
    driven by a ``SegmentTimeline``) and explicit ``SegmentList`` entries.
    Returns ``None`` for shapes that are not supported so the caller can fall
    back to downloading the manifest itself.
    """
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return None

    def local(tag: str) -> str:
        return tag.rsplit("}", 1)[-1]

    def child(element, name):
        if element is None:
            return None
        for kid in element:
            if local(kid.tag) == name:
                return kid
        return None

    def base_of(element, fallback: str) -> str:
        base = child(element, "BaseURL")
        if base is not None and base.text:
            return urljoin(fallback, base.text.strip())
        return fallback

    manifest_base = base_of(root, base_url)

    representations: list[tuple] = []
    for period in root.iter():
        if local(period.tag) != "Period":
            continue
        period_base = base_of(period, manifest_base)
        for adapset in period:
            if local(adapset.tag) != "AdaptationSet":
                continue
            set_base = base_of(adapset, period_base)
            mime = adapset.get("mimeType", "")
            for rep in adapset:
                if local(rep.tag) == "Representation":
                    representations.append((rep, adapset, set_base, mime))

    if not representations:
        return None

    def score(entry) -> tuple:
        rep, _, _, mime = entry
        return (
            1 if mime.startswith("video") else (0.5 if mime.startswith("audio") else 0),
            _to_int(rep.get("bandwidth")) or 0,
            _to_int(rep.get("height")) or 0,
        )

    rep, adapset, rep_base, mime = max(representations, key=score)
    rep_base = base_of(rep, rep_base)

    def inherit(name: str):
        """Look the element up on the Representation, then the AdaptationSet.

        Deliberately avoids ``child(rep, name) or child(adapset, name)``:
        an ElementTree Element with no children — e.g. a self-closing
        ``<SegmentTemplate .../>``, which is how most manifests write it — is
        *falsy*, so the ``or`` would silently skip it.
        """
        found = child(rep, name)
        return found if found is not None else child(adapset, name)

    template = inherit("SegmentTemplate")
    segment_list = inherit("SegmentList")
    segment_base = inherit("SegmentBase")

    duration = _parse_iso_duration(root.get("mediaPresentationDuration"))
    init_url: str | None = None
    segments: list[str] = []

    if template is not None:
        timescale = _to_int(template.get("timescale")) or 1
        start_number = _to_int(template.get("startNumber")) or 1
        rep_id = rep.get("id", "")
        bandwidth = rep.get("bandwidth", "")
        init_tpl = template.get("initialization")
        if init_tpl:
            init_url = urljoin(rep_base, _fill_template(init_tpl, start_number, 0,
                                                        rep_id, bandwidth))
        media_tpl = template.get("media")
        if media_tpl:
            timeline = child(template, "SegmentTimeline")
            seg_duration = _to_int(template.get("duration"))
            if timeline is not None:
                number, clock = start_number, 0
                for s in timeline:
                    if local(s.tag) != "S":
                        continue
                    repeat = _to_int(s.get("r")) or 0
                    clock = _to_int(s.get("t")) if s.get("t") is not None else clock
                    step = _to_int(s.get("d")) or seg_duration or 1
                    for _ in range(repeat + 1):
                        segments.append(urljoin(rep_base, _fill_template(
                            media_tpl, number, clock, rep_id, bandwidth)))
                        number += 1
                        clock += step
            elif seg_duration and duration:
                count = int(duration * timescale / seg_duration)
                if count > 20000:
                    return None
                for i in range(count):
                    segments.append(urljoin(rep_base, _fill_template(
                        media_tpl, start_number + i, 0, rep_id, bandwidth)))
    elif segment_list is not None:
        init = child(segment_list, "Initialization")
        if init is not None and init.get("sourceURL"):
            init_url = urljoin(rep_base, init.get("sourceURL"))
        for seg in segment_list:
            if local(seg.tag) == "SegmentURL" and seg.get("media"):
                segments.append(urljoin(rep_base, seg.get("media")))
    else:
        # Single-file representation (SegmentBase or a bare BaseURL).
        del segment_base
        segments.append(rep_base)

    if not segments:
        return None
    return {"segments": segments, "init_url": init_url, "mime": mime}


def _fill_template(template: str, number: int, time: int,
                   rep_id: str = "", bandwidth: str = "") -> str:
    """Substitute the DASH ``$Number$``, ``$Time$``, ``$Bandwidth$`` and
    ``$RepresentationID$`` placeholders in a URL template."""

    def substitute(value: str):
        def _replace(match: re.Match) -> str:
            text = str(value)
            return text.zfill(int(match.group(1))) if match.group(1) else text
        return _replace

    out = re.sub(r"\$Number(?:%0(\d+)d)?\$", substitute(number), template)
    out = re.sub(r"\$Time(?:%0(\d+)d)?\$", substitute(time), out)
    out = re.sub(r"\$Bandwidth(?:%0(\d+)d)?\$", substitute(bandwidth), out)
    out = out.replace("$RepresentationID$", str(rep_id))
    return out.replace("$$", "$")


def _parse_iso_duration(value: str | None) -> float | None:
    """Parse an ISO-8601 duration such as ``PT1H2M3.5S``."""
    if not value:
        return None
    match = re.match(
        r"P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?"
        r"(?:(?P<seconds>\d+(?:\.\d+)?)S)?)?",
        value,
    )
    if not match:
        return None
    parts = {k: float(v) for k, v in match.groupdict().items() if v}
    total = (parts.get("days", 0) * 86400 + parts.get("hours", 0) * 3600
             + parts.get("minutes", 0) * 60 + parts.get("seconds", 0))
    return total or None
