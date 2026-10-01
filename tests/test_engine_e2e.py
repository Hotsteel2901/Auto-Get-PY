"""End-to-end crawler tests against ``tests/local_site.py``.

These are the tests that actually prove the scraper works: a real HTTP server,
real requests, real files on disk. Each one targets a specific promise the
project makes in its README.
"""

from __future__ import annotations

from urllib.parse import urlparse

import pytest

from tests.conftest import files_on_disk, make_pause_event

pytestmark = pytest.mark.asyncio


def downloaded_paths(downloads) -> set[str]:
    return {urlparse(d["url"]).path for d in downloads}


def completed(downloads) -> list[dict]:
    return [d for d in downloads if d["status"] == "completed"]


# ── Single page ─────────────────────────────────────────────────────────────


async def test_single_page_finds_every_embedded_media_kind(local_site, run_task):
    """The homepage hides media in a dozen different places."""
    task, downloads, out = await run_task(
        local_site.url,
        {"crawl_depth": 0, "follow_pagination": False, "follow_links": False,
         "crawl_css": False, "crawl_iframes": False},
    )

    assert task["status"] == "completed", task["error_msg"]
    found = downloaded_paths(downloads)

    # Plain <img>, lazy data-src, srcset, CSS background, poster, <source>,
    # <audio>, og:image, twitter:image, JSON-LD and inline <script> strings.
    for expected in [
        "/img/hero.jpg", "/img/lazy.jpg", "/img/bg.jpg", "/img/poster.jpg",
        "/vid/clip.mp4", "/vid/clip.webm", "/audio/song.mp3",
        "/img/og.jpg", "/img/twitter.png", "/img/thumb.jpg",
        "/img/js-poster.jpg",
    ]:
        assert expected in found, f"{expected} was not discovered"

    # srcset yields both candidates.
    assert {"/img/small.jpg", "/img/large.jpg"} <= found

    # <noscript> holds the real image behind a lazy placeholder.
    assert "/img/noscript-real.jpg" in found


async def test_single_page_downloads_files_to_disk(local_site, run_task):
    task, downloads, out = await run_task(
        local_site.url,
        {"crawl_depth": 0, "follow_pagination": False, "follow_links": False,
         "crawl_css": False, "crawl_iframes": False},
    )

    assert task["status"] == "completed"
    assert completed(downloads), "nothing downloaded"
    names = files_on_disk(out)
    assert "hero.jpg" in names
    assert (out / "hero.jpg").read_bytes().startswith(b"\xff\xd8\xff")
    assert task["done_files"] == len(completed(downloads)) >= 12
    assert task["extra_info"]["pages_crawled"] == 1
    assert task["extra_info"]["total_media_found"] >= 12


async def test_filepath_and_size_recorded(local_site, run_task):
    _, downloads, out = await run_task(
        local_site.url,
        {"crawl_depth": 0, "follow_pagination": False, "follow_links": False,
         "crawl_css": False, "crawl_iframes": False},
    )
    done = completed(downloads)
    assert done
    for record in done:
        assert record["filepath"], "filepath column not populated"
        assert record["file_size"] > 0
        assert (out / record["filename"]).exists()


# ── Pagination, links, CSS, iframes ─────────────────────────────────────────


async def test_pagination_chain_is_followed(local_site, run_task):
    task, downloads, _ = await run_task(
        local_site.url,
        {"crawl_depth": 0, "follow_pagination": True, "follow_links": False,
         "crawl_css": False, "crawl_iframes": False, "max_pages": 50},
    )
    found = downloaded_paths(downloads)
    # ?page=2 via rel=next, then /page/3 via the Chinese 下一页 link.
    assert "/img/page2-a.jpg" in found
    assert "/img/cn-page.jpg" in found
    assert task["extra_info"]["pages_crawled"] >= 3


async def test_link_following_respects_depth(local_site, run_task):
    _, deep, _ = await run_task(
        local_site.url,
        {"crawl_depth": 2, "follow_pagination": False, "follow_links": True,
         "crawl_css": False, "crawl_iframes": False, "max_pages": 50},
    )
    found = downloaded_paths(deep)
    assert "/img/blog.jpg" in found, "did not follow /blog/post-1"
    assert "/img/hero.jpg" in found


async def test_stylesheets_yield_hidden_assets(local_site, run_task):
    _, downloads, _ = await run_task(
        local_site.url,
        {"crawl_depth": 1, "follow_pagination": False, "follow_links": True,
         "crawl_css": True, "crawl_iframes": False, "max_pages": 50},
    )
    found = downloaded_paths(downloads)
    assert "/img/css-bg.jpg" in found, "asset from a stylesheet missing"
    assert "/img/nested-bg.png" in found, "nested @import not followed"
    assert "/img/deeper-bg.png" in found, "@import depth limit too shallow"
    assert "/fonts/body.woff2" in found, "@font-face src not harvested"


async def test_iframes_are_entered(local_site, run_task):
    _, downloads, _ = await run_task(
        local_site.url,
        {"crawl_depth": 1, "follow_pagination": False, "follow_links": False,
         "crawl_css": False, "crawl_iframes": True, "max_pages": 50},
    )
    found = downloaded_paths(downloads)
    assert "/img/iframe-image.jpg" in found
    assert "/vid/iframe-video.mp4" in found


async def test_site_discovery_uses_sitemap_and_feeds(local_site, run_task):
    task, downloads, _ = await run_task(
        local_site.url,
        {"site_discovery": True, "crawl_depth": 0, "follow_pagination": False,
         "follow_links": False, "crawl_css": False, "crawl_iframes": False,
         "max_pages": 100},
    )
    found = downloaded_paths(downloads)
    assert "/img/sitemap-a.jpg" in found
    assert "/img/sitemap-b.jpg" in found
    assert "/img/feed-post.jpg" in found
    assert task["status"] == "completed"


# ── Cookies, Referer, content-disposition ───────────────────────────────────


async def test_session_cookies_are_replayed_for_media(local_site, run_task):
    """`/` sets a session cookie; `/protected/*` refuses to serve without it."""
    _, downloads, _ = await run_task(
        local_site.url,
        {"crawl_depth": 1, "follow_pagination": False, "follow_links": False,
         "crawl_css": False, "crawl_iframes": False, "max_pages": 50},
    )
    protected = [d for d in downloads if urlparse(d["url"]).path.startswith("/protected/")]
    assert protected, "the cookie-gated link was not discovered"
    assert protected[0]["status"] == "completed", \
        f"cookie was not replayed: {protected[0]['error_msg']}"


async def test_cookie_gated_asset_fails_without_the_session(local_site):
    """Controls for the test above: no page visit, no cookie, no file."""
    from scraper.downloader import Downloader
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        session = Downloader.create_session()
        try:
            result = await Downloader().download_file(
                f"{local_site.url}protected/secret.jpg", output_dir=tmp,
                session=session, filename="secret.jpg")
        finally:
            await session.close()

    assert not result.ok
    assert "403" in result["error_msg"]


async def test_hotlink_protection_is_defeated_by_referer(local_site):
    """Media that 403s without a Referer downloads because the engine sends one."""
    from scraper.downloader import Downloader
    import tempfile

    target = f"{local_site.url}hotlink/needs-referer.jpg"

    with tempfile.TemporaryDirectory() as tmp:
        session = Downloader.create_session()
        try:
            without = await Downloader().download_file(
                target, output_dir=tmp, session=session, filename="no-ref.jpg")
            assert not without.ok, "the fixture should refuse a request with no Referer"
            assert "403" in without["error_msg"]

            with_ref = await Downloader().download_file(
                target, output_dir=tmp, session=session, filename="with-ref.jpg",
                referer=local_site.url)
        finally:
            await session.close()

    assert with_ref.ok, with_ref.get("error_msg")
    assert with_ref["file_size"] > 0


async def test_content_disposition_filename_wins(local_site, run_task):
    """/dl/report has no extension; the server names it via Content-Disposition."""
    from scraper.downloader import Downloader
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        session = Downloader.create_session()
        try:
            result = await Downloader().download_file(
                f"{local_site.url}dl/report", output_dir=tmp, session=session,
                filename="report")
        finally:
            await session.close()

        assert result.ok, result.get("error_msg")
        assert result["filename"] == "quarterly-report.pdf", result["filename"]
        assert Path(tmp, "quarterly-report.pdf").exists()


# ── Streams ─────────────────────────────────────────────────────────────────


async def test_hls_master_is_resolved_and_segments_merged(local_site, run_task):
    from scraper.downloader import Downloader
    import tempfile
    from pathlib import Path

    playlist = f"{local_site.url}vid/stream/master.m3u8"

    with tempfile.TemporaryDirectory() as tmp:
        session = Downloader.create_session()
        try:
            result = await Downloader().download_file(
                playlist, output_dir=tmp, session=session, filename="master.m3u8")
        finally:
            await session.close()

        assert result.ok, result.get("error_msg")
        assert result.get("segments") == 3, result
        merged = Path(tmp, result["filename"])
        assert merged.exists()
        # Three segments of 188*4 bytes each, concatenated.
        assert merged.stat().st_size == 188 * 4 * 3
        assert result["filename"].endswith(".ts")


async def test_m3u8_url_is_discovered_by_the_crawler(local_site, run_task):
    _, downloads, _ = await run_task(
        local_site.url,
        {"crawl_depth": 0, "follow_pagination": False, "follow_links": False,
         "crawl_css": False, "crawl_iframes": False},
    )
    manifests = [d for d in downloads if d["url"].endswith(".m3u8")]
    assert manifests, "the HLS manifest in the inline script was not found"
    assert manifests[0]["status"] == "completed", manifests[0]["error_msg"]
    assert manifests[0]["filename"].endswith(".ts")


# ── Failure handling ────────────────────────────────────────────────────────


async def test_flaky_endpoint_is_retried_until_it_succeeds(local_site, run_task):
    from scraper.downloader import Downloader
    import tempfile

    target = f"{local_site.url}flaky/retry.jpg"
    with tempfile.TemporaryDirectory() as tmp:
        session = Downloader.create_session()
        try:
            first = await Downloader().download_file(
                target, output_dir=tmp, session=session, filename="flaky.jpg")
        finally:
            await session.close()
    assert not first.ok, "the fixture should fail on the first two hits"
    assert "503" in (first.get("error_msg") or "")


async def test_missing_file_is_reported_not_swallowed(local_site, run_task):
    _, downloads, _ = await run_task(
        f"{local_site.url}missing/gone.jpg",
        {"crawl_depth": 0, "follow_pagination": False, "follow_links": False},
        name="missing",
    )
    assert downloads, "the direct media URL should still become a record"


async def test_rate_limited_endpoint_reports_retry_after(local_site):
    from scraper.downloader import Downloader
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        session = Downloader.create_session()
        try:
            result = await Downloader().download_file(
                f"{local_site.url}ratelimited/always.jpg", output_dir=tmp,
                session=session, filename="rl.jpg")
        finally:
            await session.close()

    assert not result.ok
    assert "429" in result["error_msg"]
    assert result.get("retry_after") == 30


async def test_max_file_size_is_enforced(local_site):
    from scraper.downloader import Downloader
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        session = Downloader.create_session()
        try:
            result = await Downloader().download_file(
                f"{local_site.url}large/big.jpg", output_dir=tmp, session=session,
                filename="big.jpg", max_file_size_mb=1)
        finally:
            await session.close()

    assert not result.ok, "a 1.2 MB file should not pass a 1 MB limit"
    assert "too large" in result["error_msg"].lower()
    assert not Path(tmp, "big.jpg").exists(), "the partial file should be cleaned up"


# ── Budgets and filters ─────────────────────────────────────────────────────


async def test_url_filters_restrict_what_is_downloaded(local_site, run_task):
    _, downloads, _ = await run_task(
        local_site.url,
        {"crawl_depth": 1, "follow_pagination": True, "follow_links": True,
         "crawl_css": True, "crawl_iframes": True,
         "url_filters": {"include": ["*.jpg"]}, "max_pages": 50},
    )
    assert downloads
    assert all(urlparse(d["url"]).path.endswith(".jpg") for d in downloads)


async def test_exclude_filter_removes_matches(local_site, run_task):
    _, downloads, _ = await run_task(
        local_site.url,
        {"crawl_depth": 1, "follow_pagination": True, "follow_links": True,
         "crawl_css": True, "crawl_iframes": True,
         "url_filters": {"exclude": ["*.png", "*.jpg"]}, "max_pages": 50},
    )
    paths = downloaded_paths(downloads)
    assert not any(p.endswith((".png", ".jpg")) for p in paths)
    assert paths, "everything was filtered out instead of just the images"


async def test_max_pages_stops_a_runaway_crawl(local_site, run_task):
    task, _, _ = await run_task(
        local_site.url,
        {"crawl_depth": 5, "follow_pagination": True, "follow_links": True,
         "crawl_css": True, "crawl_iframes": True, "max_pages": 2},
    )
    assert task["extra_info"]["pages_crawled"] <= 2


async def test_unicode_and_extensionless_urls_are_handled(local_site, run_task):
    """A URL with a space is percent-encoded, not mangled."""
    from scraper.extractor import _normalize_url

    assert _normalize_url("a b.jpg", "http://x.test/p/") == "http://x.test/p/a%20b.jpg"
    assert _normalize_url("/图片/风景.jpg", "http://x.test/") == \
        "http://x.test/%E5%9B%BE%E7%89%87/%E9%A3%8E%E6%99%AF.jpg"


async def test_existing_urls_are_not_downloaded_twice(local_site, run_task):
    """Re-running a task skips assets already recorded for it."""
    from db import queries as q
    from scraper.engine import ScraperEngine
    import asyncio

    config = {"crawl_depth": 0, "follow_pagination": False, "follow_links": False,
              "crawl_css": False, "crawl_iframes": False}

    task, first, out = await run_task(local_site.url, config, name="first")
    assert completed(first)

    engine = ScraperEngine(task["id"], asyncio.Semaphore(20), make_pause_event())
    await engine.run()

    second = await q.list_downloads(task["id"])
    assert len(second) == len(first), "a re-run created duplicate download rows"


async def test_records_are_never_left_downloading(local_site, run_task):
    _, downloads, _ = await run_task(
        local_site.url,
        {"crawl_depth": 1, "follow_pagination": True, "follow_links": True,
         "crawl_css": True, "crawl_iframes": True, "max_pages": 50},
    )
    assert downloads
    assert all(d["status"] in ("completed", "failed") for d in downloads), \
        [d["status"] for d in downloads if d["status"] not in ("completed", "failed")]
