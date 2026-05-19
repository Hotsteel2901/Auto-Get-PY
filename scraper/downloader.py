import re
import asyncio
import aiohttp
import aiofiles
from pathlib import Path
from urllib.parse import urlparse


class Downloader:
    CHUNK_SIZE = 64 * 1024

    def __init__(self, output_dir: str = "./downloads", max_retries: int = 3):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.max_retries = max_retries

    @staticmethod
    def sanitize_filename(filename: str) -> str:
        name = re.sub(r'[<>:"/\\|?*]', "_", filename)
        return name.strip() or "unnamed"

    @staticmethod
    def extract_filename(url: str) -> str:
        path = urlparse(url).path
        name = Path(path).name or "unnamed"
        return Downloader.sanitize_filename(name)

    async def download_file(self, url: str, output_dir: str = None,
                            filename: str = None, task_id: int = None,
                            dl_id: int = None, progress_callback=None,
                            headers: dict = None, timeout: int = 30,
                            resume_from: int = 0) -> dict:
        out_dir = Path(output_dir) if output_dir else self.output_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        fname = filename or self.extract_filename(url)
        filepath = out_dir / fname

        for attempt in range(self.max_retries):
            try:
                req_headers = headers.copy() if headers else {}
                if resume_from > 0:
                    req_headers["Range"] = f"bytes={resume_from}-"

                async with aiohttp.ClientSession() as session:
                    async with session.get(url, headers=req_headers,
                                           timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                        if resp.status not in (200, 206):
                            if attempt < self.max_retries - 1:
                                await asyncio.sleep(2 ** attempt)
                                continue
                            return {"status": "failed", "error_msg": f"HTTP {resp.status}"}

                        total_size = resp.content_length
                        if total_size:
                            total_size += resume_from

                        mode = "ab" if resume_from > 0 else "wb"
                        async with aiofiles.open(filepath, mode) as f:
                            downloaded = resume_from
                            async for chunk in resp.content.iter_chunked(self.CHUNK_SIZE):
                                await f.write(chunk)
                                downloaded += len(chunk)
                                if progress_callback and task_id and dl_id:
                                    await progress_callback(task_id, dl_id, downloaded, total_size)

                        return {
                            "status": "completed",
                            "file_size": downloaded,
                            "filename": fname,
                            "filepath": str(filepath),
                        }
            except asyncio.TimeoutError:
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                return {"status": "failed", "error_msg": "Timeout"}
            except Exception as e:
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                return {"status": "failed", "error_msg": str(e)}

        return {"status": "failed", "error_msg": "Max retries exceeded"}
