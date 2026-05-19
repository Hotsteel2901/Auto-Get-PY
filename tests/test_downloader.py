import pytest
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock
from scraper.downloader import Downloader


def _make_get_context_manager(mock_resp):
    """Build a mock that acts as an async context manager for session.get()."""
    ctx_mgr = MagicMock()
    ctx_mgr.__aenter__ = AsyncMock(return_value=mock_resp)
    ctx_mgr.__aexit__ = AsyncMock(return_value=None)
    return ctx_mgr


async def _async_iter(*chunks):
    """Yield chunks as an async iterator (matches aiohttp's iter_chunked)."""
    for c in chunks:
        yield c


@pytest.mark.asyncio
async def test_download_creates_file(tmp_path):
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.content_length = 19
    mock_resp.content = MagicMock()
    mock_resp.content.iter_chunked = MagicMock(return_value=_async_iter(b"Hello download test"))

    mock_session = MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    ctx_mgr = _make_get_context_manager(mock_resp)
    mock_session.get = MagicMock(return_value=ctx_mgr)

    with patch("scraper.downloader.aiohttp.ClientSession", return_value=mock_session):
        dl = Downloader(output_dir=str(tmp_path))
        result = await dl.download_file(
            url="http://example.com/test.txt",
            output_dir=str(tmp_path),
            filename="test.txt",
        )
        assert result["status"] == "completed"
        assert result["file_size"] == 19
        filepath = tmp_path / "test.txt"
        assert filepath.read_bytes() == b"Hello download test"


@pytest.mark.asyncio
async def test_download_callback(tmp_path):
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.content_length = 100
    mock_resp.content = MagicMock()
    mock_resp.content.iter_chunked = MagicMock(return_value=_async_iter(b"A" * 100))

    mock_session = MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    ctx_mgr = _make_get_context_manager(mock_resp)
    mock_session.get = MagicMock(return_value=ctx_mgr)

    progress = []
    async def cb(task_id, dl_id, down, total):
        progress.append((down, total))

    with patch("scraper.downloader.aiohttp.ClientSession", return_value=mock_session):
        dl = Downloader(output_dir=str(tmp_path))
        result = await dl.download_file(
            url="http://example.com/test.txt",
            output_dir=str(tmp_path),
            filename="test.txt",
            task_id=1, dl_id=1,
            progress_callback=cb,
        )
        assert result["status"] == "completed"
        assert len(progress) > 0
        assert progress[-1] == (100, 100)


def test_sanitize_filename():
    assert Downloader.sanitize_filename("hello/world:file.txt") == "hello_world_file.txt"


def test_extract_filename():
    assert Downloader.extract_filename("http://example.com/path/to/file.jpg") == "file.jpg"
    assert Downloader.extract_filename("http://example.com/") == "unnamed"
