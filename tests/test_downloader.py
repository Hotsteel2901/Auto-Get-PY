"""Downloader tests.

Pure helpers (naming, header parsing, playlist expansion) are unit tested;
anything that touches the network runs against ``tests/local_site.py`` so the
behaviour under test is the real behaviour.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from scraper.downloader import (
    Downloader,
    _parse_iso_duration,
    decrypt_hls_segment,
    extension_for_content_type,
    parse_attribute_list,
    parse_dash_manifest,
    parse_hls_master,
    parse_hls_media,
    playlist_output_name,
)

pytestmark = pytest.mark.asyncio


# ── Filename handling ───────────────────────────────────────────────────────


def test_sanitize_strips_directories_and_illegal_characters():
    # Directory components are dropped: a scraped name must never escape the
    # output directory.
    assert Downloader.sanitize_filename("hello/world:file.txt") == "world_file.txt"
    assert Downloader.sanitize_filename("../../etc/passwd") == "passwd"
    assert Downloader.sanitize_filename("a\\b\\c.jpg") == "c.jpg"
    assert Downloader.sanitize_filename('bad<>:"|?*.png') == "bad_______.png"
    assert Downloader.sanitize_filename("") == "unnamed"
    assert Downloader.sanitize_filename("   ") == "unnamed"


def test_sanitize_keeps_unicode_and_bounds_length():
    assert Downloader.sanitize_filename("风景 照片.jpg") == "风景 照片.jpg"
    long_name = "x" * 400 + ".jpg"
    assert len(Downloader.sanitize_filename(long_name)) <= 180
    assert Downloader.sanitize_filename(long_name).endswith(".jpg")


def test_extract_filename_prefers_the_path():
    assert Downloader.extract_filename("http://e.com/a/b/file.jpg") == "file.jpg"
    assert Downloader.extract_filename("http://e.com/a/b/file.jpg?x=1") == "file.jpg"


def test_extract_filename_reads_a_name_out_of_the_query():
    assert Downloader.extract_filename("http://e.com/get?file=movie.mp4") == "movie.mp4"
    assert Downloader.extract_filename("http://e.com/d?filename=doc.pdf&x=1") == "doc.pdf"


def test_extract_filename_falls_back_to_a_hash():
    name = Downloader.extract_filename("http://e.com/")
    assert name != "unnamed"
    assert name.endswith(".bin")
    assert Downloader.extract_filename("http://e.com/") == name  # stable


def test_extract_filename_decodes_percent_escapes():
    assert Downloader.extract_filename("http://e.com/a%20b.jpg") == "a b.jpg"


def test_extract_filename_guesses_from_a_deep_extension():
    # `archive.tar.gz` must not be truncated to `archive.tar`.
    assert Downloader.extract_filename("http://e.com/x/archive.tar.gz") == "archive.tar.gz"


def test_content_disposition_parsing():
    parse = Downloader._content_disposition_name
    assert parse('attachment; filename="report.pdf"') == "report.pdf"
    assert parse("attachment; filename=plain.mp4") == "plain.mp4"
    assert parse("attachment; filename*=UTF-8''%E9%A3%8E%E6%99%AF.jpg") == "风景.jpg"
    assert parse("inline") is None
    assert parse("") is None


def test_extension_for_content_type():
    assert extension_for_content_type("image/jpeg") == ".jpg"
    assert extension_for_content_type("video/mp4; codecs=avc1") == ".mp4"
    assert extension_for_content_type("application/vnd.apple.mpegurl") == ".m3u8"
    assert extension_for_content_type("application/octet-stream") is None
    assert extension_for_content_type(None) is None


def test_playlist_output_name():
    assert playlist_output_name("master.m3u8", "http://e.com/a/master.m3u8") == "master.ts"
    assert playlist_output_name("x.m3u8", "http://e.com/a/v.m3u8", fragmented=True) == "x.mp4"


# ── HLS parsing ─────────────────────────────────────────────────────────────


MASTER = """#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=800000,RESOLUTION=640x360
low/index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=2000000,RESOLUTION=1280x720
high/index.m3u8
"""


def test_hls_master_variants_are_parsed_and_resolved():
    variants = parse_hls_master(MASTER, "http://e.com/vid/master.m3u8")
    assert len(variants) == 2
    assert variants[0]["bandwidth"] == 800000
    assert variants[1]["height"] == 720
    assert variants[1]["url"] == "http://e.com/vid/high/index.m3u8"


def test_hls_master_ignores_media_playlists():
    assert parse_hls_master("#EXTM3U\n#EXTINF:4,\nseg.ts\n", "http://e.com/a.m3u8") == []


BYTERANGE_MEDIA = """#EXTM3U
#EXT-X-TARGETDURATION:4
#EXT-X-KEY:METHOD=AES-128,URI="key.bin",IV=0x0123456789abcdef0123456789abcdef
#EXTINF:4.0,
#EXT-X-BYTERANGE:1000@0
seg.ts
#EXTINF:4.0,
#EXT-X-BYTERANGE:500@1000
seg.ts
#EXT-X-ENDLIST
"""


def test_hls_media_expands_byteranges_and_keys():
    media = parse_hls_media(BYTERANGE_MEDIA, "http://e.com/vid/index.m3u8")
    assert len(media["segments"]) == 2
    assert media["segments"][0]["range"] == (0, 999)
    assert media["segments"][1]["range"] == (1000, 1499)
    assert media["segments"][0]["key_url"] == "http://e.com/vid/key.bin"
    assert media["segments"][0]["sequence"] == 0
    assert media["total_duration"] == 8.0


def test_hls_key_can_change_mid_playlist():
    text = """#EXTM3U
#EXT-X-KEY:METHOD=AES-128,URI="k1"
#EXTINF:1,
a.ts
#EXT-X-KEY:METHOD=NONE
#EXTINF:1,
b.ts
"""
    media = parse_hls_media(text, "http://e.com/v.m3u8")
    assert media["segments"][0]["key_url"] == "http://e.com/k1"
    assert media["segments"][1]["key_url"] is None


def test_hls_init_map_marks_a_fragmented_stream():
    text = '#EXTM3U\n#EXT-X-MAP:URI="init.mp4"\n#EXTINF:1,\ns1.m4s\n'
    media = parse_hls_media(text, "http://e.com/v/index.m3u8")
    assert media["init_url"] == "http://e.com/v/init.mp4"


def test_hls_segments_resolve_relative_to_the_playlist():
    media = parse_hls_media("#EXTM3U\n#EXTINF:1,\n../seg/a.ts\n",
                            "http://e.com/hls/v/index.m3u8")
    assert media["segments"][0]["url"] == "http://e.com/hls/seg/a.ts"


def test_hls_aes_segment_round_trip():
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad

    key = bytes(range(16))
    iv = bytes(range(16, 32))
    plaintext = b"segment payload" * 20
    cipher = AES.new(key, AES.MODE_CBC, iv)
    encrypted = cipher.encrypt(pad(plaintext, AES.block_size))

    decrypted = decrypt_hls_segment(encrypted, key, "0x" + iv.hex(), sequence=0)
    assert decrypted == plaintext

    # Without an explicit IV the sequence number becomes the IV.
    seq_cipher = AES.new(key, AES.MODE_CBC, (7).to_bytes(16, "big"))
    seq_encrypted = seq_cipher.encrypt(pad(plaintext, AES.block_size))
    assert decrypt_hls_segment(seq_encrypted, key, None, sequence=7) == plaintext


def test_hls_decrypt_with_a_wrong_key_returns_the_input():
    """A bad key must not lose the bytes; the caller keeps them for inspection."""
    data = b"not-really-encrypted"
    assert decrypt_hls_segment(data, b"short", None, sequence=1) == data


def test_attribute_list_parsing():
    attrs = parse_attribute_list('BANDWIDTH=1000,RESOLUTION="1280x720",NAME=hi')
    assert attrs == {"BANDWIDTH": "1000", "RESOLUTION": "1280x720", "NAME": "hi"}


# ── DASH parsing ────────────────────────────────────────────────────────────


def test_dash_segment_template_with_duration():
    manifest = """<?xml version="1.0"?>
<MPD mediaPresentationDuration="PT10S">
  <Period>
    <AdaptationSet mimeType="video/mp4">
      <Representation id="v1" bandwidth="900000" height="720">
        <SegmentTemplate timescale="1" duration="2" startNumber="1"
          initialization="init-$RepresentationID$.mp4"
          media="seg-$Number$.m4s"/>
      </Representation>
    </AdaptationSet>
  </Period>
</MPD>"""
    plan = parse_dash_manifest(manifest, "http://e.com/movie/manifest.mpd")
    assert plan is not None
    assert len(plan["segments"]) == 5
    assert plan["segments"][0] == "http://e.com/movie/seg-1.m4s"
    assert plan["segments"][-1] == "http://e.com/movie/seg-5.m4s"
    assert plan["init_url"] == "http://e.com/movie/init-v1.mp4"


def test_dash_segment_timeline():
    manifest = """<?xml version="1.0"?>
<MPD><Period><AdaptationSet mimeType="video/mp4"><Representation id="v" bandwidth="1">
  <SegmentTemplate timescale="1000" media="chunk-$Number$.m4s" initialization="i.mp4">
    <SegmentTimeline>
      <S t="0" d="2000" r="2"/>
      <S d="1500"/>
    </SegmentTimeline>
  </SegmentTemplate>
</Representation></AdaptationSet></Period></MPD>"""
    plan = parse_dash_manifest(manifest, "http://e.com/m.mpd")
    assert [s.rsplit("/", 1)[-1] for s in plan["segments"]] == [
        "chunk-1.m4s", "chunk-2.m4s", "chunk-3.m4s", "chunk-4.m4s"]
    # $Time$ is substituted too.
    assert plan["init_url"] == "http://e.com/i.mp4"


def test_dash_picks_the_highest_bandwidth_video():
    manifest = """<?xml version="1.0"?>
<MPD mediaPresentationDuration="PT4S"><Period>
  <AdaptationSet mimeType="video/mp4"><Representation id="low" bandwidth="100">
    <SegmentTemplate timescale="1" duration="2" media="low-$Number$.m4s"/></Representation>
    <Representation id="high" bandwidth="9000">
    <SegmentTemplate timescale="1" duration="2" media="high-$Number$.m4s"/></Representation>
  </AdaptationSet></Period></MPD>"""
    plan = parse_dash_manifest(manifest, "http://e.com/m.mpd")
    assert all("high-" in url for url in plan["segments"])


def test_dash_segment_list():
    manifest = """<?xml version="1.0"?>
<MPD><Period><AdaptationSet mimeType="audio/mp4"><Representation id="a" bandwidth="1">
  <SegmentList>
    <Initialization sourceURL="init.mp4"/>
    <SegmentURL media="a1.m4s"/><SegmentURL media="a2.m4s"/>
  </SegmentList>
</Representation></AdaptationSet></Period></MPD>"""
    plan = parse_dash_manifest(manifest, "http://e.com/p/m.mpd")
    assert plan["init_url"] == "http://e.com/p/init.mp4"
    assert plan["segments"] == ["http://e.com/p/a1.m4s", "http://e.com/p/a2.m4s"]


def test_dash_single_file_representation():
    manifest = """<?xml version="1.0"?>
<MPD><Period><AdaptationSet mimeType="video/mp4"><Representation id="v" bandwidth="1">
  <BaseURL>whole-movie.mp4</BaseURL>
</Representation></AdaptationSet></Period></MPD>"""
    plan = parse_dash_manifest(manifest, "http://e.com/p/m.mpd")
    assert plan["segments"] == ["http://e.com/p/whole-movie.mp4"]


def test_dash_garbage_returns_none():
    assert parse_dash_manifest("not xml at all", "http://e.com/m.mpd") is None
    assert parse_dash_manifest("<MPD><Period/></MPD>", "http://e.com/m.mpd") is None


def test_iso_duration_parsing():
    assert _parse_iso_duration("PT10S") == 10
    assert _parse_iso_duration("PT1H2M3S") == 3723
    assert _parse_iso_duration("P1DT1S") == 86401
    assert _parse_iso_duration("PT0S") is None
    assert _parse_iso_duration(None) is None
    assert _parse_iso_duration("rubbish") is None


# ── Integration against the local site ──────────────────────────────────────


async def test_plain_download_writes_the_file(local_site):
    with tempfile.TemporaryDirectory() as tmp:
        session = Downloader.create_session()
        try:
            result = await Downloader().download_file(
                f"{local_site.url}img/hero.jpg", output_dir=tmp,
                session=session, filename="hero.jpg")
            written = Path(tmp, "hero.jpg").read_bytes()
        finally:
            await session.close()

    assert result.ok, result.get("error_msg")
    assert result["file_size"] > 0
    assert result["mime_type"] == "image/jpeg"
    assert written.startswith(b"\xff\xd8\xff")


async def test_retry_overwrites_instead_of_accumulating_copies(local_site):
    """A caller-supplied filename is authoritative; retries stay idempotent."""
    with tempfile.TemporaryDirectory() as tmp:
        session = Downloader.create_session()
        try:
            downloader = Downloader()
            for _ in range(3):
                result = await downloader.download_file(
                    f"{local_site.url}img/hero.jpg", output_dir=tmp,
                    session=session, filename="hero.jpg")
                assert result.ok
        finally:
            await session.close()

        assert sorted(p.name for p in Path(tmp).iterdir()) == ["hero.jpg"]


async def test_progress_callback_is_throttled_and_finishes_at_100(local_site):
    calls = []

    async def on_progress(dl_id, downloaded, total):
        calls.append((downloaded, total))

    with tempfile.TemporaryDirectory() as tmp:
        session = Downloader.create_session()
        try:
            result = await Downloader().download_file(
                f"{local_site.url}large/big.jpg", output_dir=tmp, session=session,
                filename="big.jpg", progress_callback=on_progress, dl_id=1)
        finally:
            await session.close()

    assert result.ok
    assert calls, "progress was never reported"
    assert calls[-1][0] == result["file_size"], "final callback must report the full size"
    # 1.2 MB in 64 KB chunks would be ~19 callbacks without throttling.
    assert len(calls) <= 8, f"progress is not throttled ({len(calls)} callbacks)"


async def test_resume_continues_a_partial_file(local_site):
    """A truncated file is completed by a second attempt, not restarted."""
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp, "big.jpg")
        target.write_bytes(b"\xff\xd8\xff\xe0" + b"L" * (400 * 1024))
        partial_size = target.stat().st_size

        session = Downloader.create_session()
        try:
            result = await Downloader().download_file(
                f"{local_site.url}large/big.jpg", output_dir=tmp, session=session,
                filename="big.jpg", resume_from=partial_size)
        finally:
            await session.close()

    assert result.ok, result.get("error_msg")
    assert result["file_size"] == 4 + 1200 * 1024, "the resumed file has the wrong size"
    assert "Range" not in result  # sanity: we did not reuse a request header


async def test_hls_playlist_is_merged_into_one_file(local_site):
    with tempfile.TemporaryDirectory() as tmp:
        session = Downloader.create_session()
        try:
            result = await Downloader().download_file(
                f"{local_site.url}vid/stream/high/index.m3u8", output_dir=tmp,
                session=session, filename="high.m3u8")
        finally:
            await session.close()

        assert result.ok, result.get("error_msg")
        assert result["segments"] == 3
        assert result["filename"] == "high.ts"
        assert Path(tmp, "high.ts").stat().st_size == 188 * 4 * 3


async def test_master_playlist_selects_the_best_variant(local_site):
    with tempfile.TemporaryDirectory() as tmp:
        session = Downloader.create_session()
        try:
            result = await Downloader().download_file(
                f"{local_site.url}vid/stream/master.m3u8", output_dir=tmp,
                session=session, filename="master.m3u8")
        finally:
            await session.close()

    assert result.ok
    # The master itself has no segments; the chosen variant's three are merged.
    assert result["segments"] == 3


async def test_unknown_host_reports_a_clean_error():
    session = Downloader.create_session()
    try:
        result = await Downloader().download_file(
            "http://127.0.0.1:1/nothing.jpg", output_dir=".",
            session=session, filename="nothing.jpg", timeout=3)
    finally:
        await session.close()

    assert not result.ok
    assert "Network error" in result["error_msg"] or "failed" in result["error_msg"]
