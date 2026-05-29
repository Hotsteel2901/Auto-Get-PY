import asyncio
import json
import logging
import time
import aiohttp
from pathlib import Path
from urllib.parse import urlparse
from scraper.extractor import extract_media_urls, MEDIA_EXTENSIONS
from scraper.decryptors import run_pipeline
from scraper.downloader import Downloader

logger = logging.getLogger(__name__)

_BINARY_CONTENT_TYPES = {
    "application/octet-stream",
    "application/pdf",
    "application/zip",
    "application/x-rar-compressed",
    "application/x-7z-compressed",
    "application/x-tar",
    "application/gzip",
    "application/x-bzip2",
    "application/x-xz",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/epub+zip",
}

_BINARY_CONTENT_PREFIXES = ("video/", "audio/", "image/", "font/")


class ScraperEngine:
    def __init__(self, task_id: int, semaphore: asyncio.Semaphore,
                 pause_event: asyncio.Event, progress_cb=None):
        self.task_id = task_id
        self._semaphore = semaphore
        self._pause_event = pause_event
        self._progress_cb = progress_cb
        self._downloader = Downloader()

    async def _download_item(self, dl, output_dir, headers, timeout, max_retries, request_delay):
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

                dl_result = await self._downloader.download_file(
                    url=dl["url"],
                    output_dir=output_dir,
                    filename=dl["filename"],
                    task_id=self.task_id,
                    dl_id=dl["id"],
                    progress_callback=self._on_progress,
                    headers=headers,
                    timeout=timeout,
                    resume_from=resume_from,
                )

                if dl_result["status"] == "completed":
                    await q.update_download(dl["id"], status="completed",
                                            file_size=dl_result["file_size"])
                    return dl_result

                retries += 1
                if retries < max_retries:
                    await q.update_download(dl["id"], status="pending",
                                            retry_count=retries,
                                            error_msg=dl_result.get("error_msg"))
                    await asyncio.sleep(2 ** retries)
                else:
                    await q.update_download(dl["id"], status="failed",
                                            error_msg=dl_result.get("error_msg"))
                    return dl_result

    async def run(self):
        from db import queries as q

        task = await q.get_task(self.task_id)
        if not task:
            return
        config = json.loads(task["config"]) if task["config"] else {}
        concurrency = config.get("concurrency", 5)
        request_delay = config.get("request_delay_sec", 0.5)
        timeout = config.get("request_timeout_sec", 30)
        max_retries = config.get("max_retries", 3)
        output_dir = config.get("output_dir", "./downloads")
        decryptors_enabled = config.get("decryptors", [])
        decryptor_opts = config.get("decryptor_opts", {})
        include_filters = config.get("url_filters", {}).get("include")
        exclude_filters = config.get("url_filters", {}).get("exclude")
        headers = config.get("custom_headers", {})

        page_html, is_direct_file, fetch_error = await self._fetch_page(task["url"], headers, timeout)

        if is_direct_file:
            existing_urls = await q.get_existing_download_urls(self.task_id)
            if task["url"] not in existing_urls:
                filename = Downloader.extract_filename(task["url"])
                await q.create_download(self.task_id, task["url"], filename)
            await q.update_task(self.task_id, total_files=1, done_files=0)

            downloads = await q.list_downloads(self.task_id)
            downloads = [d for d in downloads if d["status"] != "completed"]

            if not downloads:
                completed = await q.count_downloads_by_status(self.task_id, "completed")
                await q.update_task(self.task_id, status="completed", done_files=completed)
                return

            result = await self._download_item(
                downloads[0], output_dir, headers, timeout, max_retries, request_delay)

            await self._pause_event.wait()
            completed = await q.count_downloads_by_status(self.task_id, "completed")
            if self._progress_cb:
                await self._progress_cb(self.task_id, 1, 1, downloads[0]["filename"], 0)
            await q.update_task(self.task_id, status="completed", done_files=completed)
            return

        if page_html is None:
            await q.update_task(self.task_id, status="failed",
                                error_msg=fetch_error or "Failed to fetch page")
            return

        if decryptors_enabled and page_html:
            result = await run_pipeline(
                page_html.encode("utf-8"),
                decryptors_enabled,
                decryptor_opts,
                max_passes=3,
            )
            page_html = result.data.decode("utf-8", errors="ignore")

        urls = extract_media_urls(page_html, task["url"], include_filters, exclude_filters)
        if not urls:
            await q.update_task(self.task_id, status="completed", total_files=0, done_files=0)
            return

        existing_urls = await q.get_existing_download_urls(self.task_id)
        new_urls = [url for url in urls if url not in existing_urls]
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

        await q.update_task(self.task_id, total_files=total)
        done_count = 0
        start_time = time.time()

        async def download_one(dl):
            nonlocal done_count
            try:
                result = await self._download_item(
                    dl, output_dir, headers, timeout, max_retries, request_delay)
                done_count += 1
                elapsed = time.time() - start_time
                speed = done_count / elapsed if elapsed > 0 else 0
                if self._progress_cb:
                    await self._progress_cb(self.task_id, done_count, total, dl["filename"], speed)
            except Exception:
                logger.exception("Unexpected error downloading %s", dl["url"])
                done_count += 1

        tasks = [download_one(dl) for dl in downloads]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                logger.error("Download task raised: %s", r)

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

    async def _fetch_page(self, url: str, headers: dict, timeout: int) -> tuple[str | None, bool, str | None]:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers,
                                       timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                    if resp.status != 200:
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

                    return (await resp.text(), False, None)
        except Exception as e:
            logger.warning("Failed to fetch %s: %s", url, e)
            return (None, False, str(e))