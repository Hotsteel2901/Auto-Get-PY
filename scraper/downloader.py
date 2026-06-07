import asyncio
import re
import shutil
import aiohttp
import aiofiles
from pathlib import Path
from urllib.parse import urlparse
import urllib.parse


class Downloader:
    CHUNK_SIZE = 64 * 1024

    def __init__(self, output_dir: str = "./downloads"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def sanitize_filename(filename: str) -> str:
        name = re.sub(r'[<>:"/\\|?*]', "_", filename)
        # Truncate very long filenames
        if len(name) > 200:
            stem = name[:190]
            suffix = Path(name).suffix[:10]
            name = stem + suffix
        return name.strip() or "unnamed"

    @staticmethod
    def extract_filename(url: str) -> str:
        path = urlparse(url).path
        # Try to get meaningful filename from path
        name = Path(path).name
        if not name or name == '/':
            # Generate from URL hash
            import hashlib
            name = hashlib.md5(url.encode()).hexdigest()[:16]
            # Try to guess extension from URL
            for ext in ('.mp4', '.mp3', '.jpg', '.png', '.pdf', '.webm', '.gif'):
                if ext in url.lower():
                    name += ext
                    break
            else:
                name += '.bin'
        return Downloader.sanitize_filename(name)

    @staticmethod
    def _resolve_conflict(filepath: Path) -> Path:
        """If file already exists, append (1), (2), etc. to avoid overwriting."""
        if not filepath.exists():
            return filepath
        stem = filepath.stem
        suffix = filepath.suffix
        parent = filepath.parent
        counter = 1
        while True:
            new_path = parent / f"{stem}({counter}){suffix}"
            if not new_path.exists():
                return new_path
            counter += 1

    @staticmethod
    def _check_disk_space(path: str, min_mb: int = 50) -> bool:
        """Check if there's enough disk space for downloading."""
        try:
            usage = shutil.disk_usage(path)
            free_mb = usage.free / (1024 * 1024)
            return free_mb > min_mb
        except Exception:
            return True

    async def download_file(self, url: str, output_dir: str = None,
                            filename: str = None, task_id: int = None,
                            dl_id: int = None, progress_callback=None,
                            headers: dict = None, timeout: int = 30,
                            resume_from: int = 0, proxy: str = None,
                            max_file_size_mb: int = None) -> dict:
        out_dir = Path(output_dir) if output_dir else self.output_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        fname = filename or self.extract_filename(url)
        filepath = out_dir / fname

        # Only resolve conflicts for new downloads (not resuming)
        if resume_from == 0:
            filepath = self._resolve_conflict(filepath)
            fname = filepath.name

        # Disk space check
        if not self._check_disk_space(str(out_dir)):
            return {"status": "failed", "error_msg": "Disk space critically low (< 50MB free)"}

        try:
            req_headers = headers.copy() if headers else {}
            if resume_from > 0:
                req_headers["Range"] = f"bytes={resume_from}-"

            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, headers=req_headers,
                    timeout=aiohttp.ClientTimeout(total=timeout),
                    proxy=proxy,
                ) as resp:
                    # Handle 429 Too Many Requests
                    if resp.status == 429:
                        retry_after = resp.headers.get('Retry-After')
                        if retry_after:
                            try:
                                wait = int(retry_after)
                            except ValueError:
                                wait = 30
                        else:
                            wait = 30
                        return {
                            "status": "failed",
                            "error_msg": f"HTTP 429 (rate limited, Retry-After: {wait}s)",
                            "retry_after": wait,
                        }

                    if resp.status not in (200, 206):
                        return {"status": "failed", "error_msg": f"HTTP {resp.status}"}

                    if resume_from > 0 and resp.status == 200:
                        resume_from = 0

                    total_size = resp.content_length
                    if total_size and resume_from > 0:
                        total_size += resume_from

                    # Check max file size before downloading
                    if max_file_size_mb and total_size:
                        max_bytes = max_file_size_mb * 1024 * 1024
                        if total_size > max_bytes:
                            return {
                                "status": "failed",
                                "error_msg": f"File too large: {total_size / 1024 / 1024:.1f}MB > {max_file_size_mb}MB limit",
                            }

                    # Smart Content-Disposition filename override
                    cd = resp.headers.get('Content-Disposition', '')
                    if cd and not filename:
                        cd_match = re.search(r'filename[*]?=["\']?([^"\';\s]+)', cd)
                        if cd_match:
                            cd_name = self.sanitize_filename(cd_match.group(1))
                            if cd_name and cd_name != 'unnamed':
                                fname = cd_name
                                filepath = out_dir / fname
                                if resume_from == 0:
                                    filepath = self._resolve_conflict(filepath)
                                    fname = filepath.name

                    # If filename has no extension, guess from Content-Type
                    if not Path(fname).suffix or Path(fname).suffix == '.bin':
                        from scraper.extractor import guess_extension_from_content_type
                        ct = resp.headers.get('Content-Type', '')
                        ext = guess_extension_from_content_type(ct)
                        if ext:
                            fname = Path(fname).stem + ext
                            filepath = out_dir / fname
                            if resume_from == 0:
                                filepath = self._resolve_conflict(filepath)
                                fname = filepath.name

                    mode = "ab" if resume_from > 0 else "wb"
                    async with aiofiles.open(filepath, mode) as f:
                        downloaded = resume_from
                        async for chunk in resp.content.iter_chunked(self.CHUNK_SIZE):
                            # Check size limit during download
                            if max_file_size_mb:
                                max_bytes = max_file_size_mb * 1024 * 1024
                                if downloaded + len(chunk) > max_bytes:
                                    return {
                                        "status": "failed",
                                        "error_msg": f"File exceeded {max_file_size_mb}MB limit during download",
                                    }
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
            return {"status": "failed", "error_msg": "Timeout"}
        except Exception as e:
            return {"status": "failed", "error_msg": str(e)}
