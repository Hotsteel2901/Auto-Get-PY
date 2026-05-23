import asyncio
import json
import time
import aiohttp
from pathlib import Path
from scraper.extractor import extract_media_urls, MEDIA_EXTENSIONS
from scraper.decryptors import register_all, run_pipeline
from scraper.downloader import Downloader


class ScraperEngine:
    def __init__(self, task_id: int, semaphore: asyncio.Semaphore,
                 pause_event: asyncio.Event, progress_cb=None):
        self.task_id = task_id
        self._semaphore = semaphore
        self._pause_event = pause_event
        self._progress_cb = progress_cb
        self._downloader = Downloader()

    async def run(self):
        from db import queries as q

        register_all()
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

        page_html, is_direct_file = await self._fetch_page(task["url"], headers, timeout)
        
        if is_direct_file:
            filename = Downloader.extract_filename(task["url"])
            await q.create_download(self.task_id, task["url"], filename)
            await q.update_task(self.task_id, total_files=1, done_files=0)
            
            sem = asyncio.Semaphore(concurrency)
            downloads = await q.list_downloads(self.task_id)
            
            done_count = 0
            start_time = time.time()
            
            async def download_one(dl):
                nonlocal done_count
                async with sem:
                    await self._pause_event.wait()
                    await q.update_download(dl["id"], status="downloading")
                    
                    dl_result = await self._downloader.download_file(
                        url=dl["url"],
                        output_dir=output_dir,
                        filename=dl["filename"],
                        task_id=self.task_id,
                        dl_id=dl["id"],
                        progress_callback=self._on_progress,
                        headers=headers,
                        timeout=timeout,
                    )
                    
                    if dl_result["status"] == "completed":
                        await q.update_download(dl["id"], status="completed",
                                                file_size=dl_result["file_size"])
                    else:
                        retry_count = dl.get("retry_count", 0) + 1
                        if retry_count < max_retries:
                            await q.update_download(dl["id"], status="pending",
                                                    retry_count=retry_count,
                                                    error_msg=dl_result.get("error_msg"))
                            await asyncio.sleep(2 ** retry_count)
                            await download_one(dl)
                        else:
                            await q.update_download(dl["id"], status="failed",
                                                    error_msg=dl_result.get("error_msg"))
                    
                    done_count += 1
                    if self._progress_cb:
                        await self._progress_cb(self.task_id, done_count, 1, dl["filename"], 0)
            
            await download_one(downloads[0])
            await self._pause_event.wait()
            await q.update_task(self.task_id, status="completed", done_files=done_count)
            return
        
        if page_html is None:
            await q.update_task(self.task_id, status="failed", error_msg="Failed to fetch page")
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

        for url in urls:
            filename = Downloader.extract_filename(url)
            await q.create_download(self.task_id, url, filename)

        total = len(urls)
        await q.update_task(self.task_id, total_files=total)

        sem = asyncio.Semaphore(concurrency)
        done_count = 0
        start_time = time.time()

        downloads = await q.list_downloads(self.task_id)

        async def download_one(dl):
            nonlocal done_count
            async with sem:
                await self._pause_event.wait()
                await q.update_download(dl["id"], status="downloading")

                dl_result = await self._downloader.download_file(
                    url=dl["url"],
                    output_dir=output_dir,
                    filename=dl["filename"],
                    task_id=self.task_id,
                    dl_id=dl["id"],
                    progress_callback=self._on_progress,
                    headers=headers,
                    timeout=timeout,
                )

                if dl_result["status"] == "completed":
                    await q.update_download(dl["id"], status="completed",
                                            file_size=dl_result["file_size"])
                else:
                    retry_count = dl.get("retry_count", 0) + 1
                    if retry_count < max_retries:
                        await q.update_download(dl["id"], status="pending",
                                                retry_count=retry_count,
                                                error_msg=dl_result.get("error_msg"))
                        await asyncio.sleep(2 ** retry_count)
                        await download_one(dl)
                    else:
                        await q.update_download(dl["id"], status="failed",
                                                error_msg=dl_result.get("error_msg"))

                done_count += 1
                elapsed = time.time() - start_time
                speed = done_count / elapsed if elapsed > 0 else 0
                if self._progress_cb:
                    await self._progress_cb(self.task_id, done_count, total, dl["filename"], speed)

        tasks = [download_one(dl) for dl in downloads]
        await asyncio.gather(*tasks, return_exceptions=True)

        await self._pause_event.wait()
        failed_count = await q.count_downloads_by_status(self.task_id, "failed")
        if failed_count == total:
            await q.update_task(self.task_id, status="failed", error_msg="All downloads failed")
        else:
            await q.update_task(self.task_id, status="completed", done_files=done_count)

    async def _on_progress(self, task_id, dl_id, downloaded, total):
        from db import queries as q
        await q.update_download(dl_id, downloaded=downloaded, file_size=total)

    async def _fetch_page(self, url: str, headers: dict, timeout: int) -> tuple[str | None, bool]:
        """Fetch page content and return (html_content, is_direct_file).
        
        Returns:
            tuple: (html_content or None, is_direct_file boolean)
            - If URL points directly to a file, returns (None, True)
            - If URL points to HTML page, returns (html_text, False)
            - On error, returns (None, False)
        """
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers,
                                       timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                    if resp.status != 200:
                        return (None, False)
                    
                    content_type = resp.headers.get('Content-Type', '').lower()
                    content_disposition = resp.headers.get('Content-Disposition', '')
                    
                    is_file = (
                        'application/octet-stream' in content_type or
                        'attachment' in content_disposition or
                        any(ext in url.lower() for ext in MEDIA_EXTENSIONS)
                    )
                    
                    if is_file:
                        return (None, True)
                    
                    return (await resp.text(), False)
        except Exception:
            pass
        return (None, False)
