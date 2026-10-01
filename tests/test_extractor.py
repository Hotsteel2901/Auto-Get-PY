"""Extraction tests.

Covers the URL normalisation rules — which are where the subtle bugs live —
plus one test per discovery strategy so a regression names itself.
"""

from __future__ import annotations

import pytest

from scraper.extractor import (
    MEDIA_EXTENSIONS,
    apply_url_filters,
    canonicalize_url,
    decode_body,
    detect_encoding,
    extract_css_urls,
    extract_iframe_urls,
    extract_inline_base64_images,
    extract_media_urls,
    extract_noscript_template_urls,
    extract_page_links,
    find_meta_refresh_url,
    find_next_page_url,
    guess_extension_from_content_type,
    _normalize_url,
)

BASE = "http://example.com/page/"


# ── URL normalisation ───────────────────────────────────────────────────────


def test_spaces_are_percent_encoded_not_left_raw():
    """Unquoting without re-quoting produces un-requestable URLs."""
    assert _normalize_url("a b.jpg", BASE) == "http://example.com/page/a%20b.jpg"
    assert _normalize_url("/img/my photo.jpg", BASE) == \
        "http://example.com/img/my%20photo.jpg"


def test_already_encoded_urls_are_not_double_encoded():
    assert _normalize_url("a%20b.jpg", BASE) == "http://example.com/page/a%20b.jpg"


def test_contrived_path_traversal_is_normalised_away():
    assert _normalize_url("../../etc/passwd", BASE) == "http://example.com/etc/passwd"


def test_non_ascii_paths_are_encoded():
    assert _normalize_url("/图片/风景.jpg", BASE) == \
        "http://example.com/%E5%9B%BE%E7%89%87/%E9%A3%8E%E6%99%AF.jpg"


def test_international_domain_becomes_punycode():
    assert _normalize_url("http://例え.jp/a.jpg", BASE) == "http://xn--r8jz45g.jp/a.jpg"


def test_scheme_relative_urls_inherit_the_page_scheme():
    assert _normalize_url("//cdn.example.com/a.jpg", "https://example.com/") == \
        "https://cdn.example.com/a.jpg"


def test_html_entities_are_decoded():
    assert _normalize_url("a.jpg?x=1&amp;y=2", BASE) == \
        "http://example.com/page/a.jpg?x=1&y=2"


def test_escaped_slashes_from_json_are_unescaped():
    assert _normalize_url(r"https:\/\/cdn.example.com\/a.jpg", BASE) == \
        "https://cdn.example.com/a.jpg"
    assert _normalize_url("https:\\u002F\\u002Fcdn.example.com/a.jpg", BASE) == \
        "https://cdn.example.com/a.jpg"


def test_fragments_are_dropped():
    assert _normalize_url("/a.jpg#frag", BASE) == "http://example.com/a.jpg"


def test_junk_is_rejected():
    for junk in ["", None, "#anchor", "javascript:void(0)", "mailto:a@b.c",
                 "data:image/png;base64,AAA", "blob:http://x/abc",
                 "tel:+1234", "ftp://example.com/a.jpg"]:
        assert _normalize_url(junk, BASE) is None, junk


# ── Extraction strategies ───────────────────────────────────────────────────


def test_plain_attributes():
    urls = extract_media_urls(
        '<img src="photo.jpg"><img src="/images/logo.png">'
        '<a href="document.pdf">PDF</a><script>var x = "other.txt"</script>',
        BASE)
    extensions = {u.rsplit(".", 1)[-1] for u in urls}
    assert {"jpg", "png", "pdf"} <= extensions


def test_query_strings_are_preserved():
    urls = extract_media_urls('<img src="/a.jpg?w=800&sig=abc">', BASE)
    assert "http://example.com/a.jpg?w=800&sig=abc" in urls


def test_multi_suffix_extensions_are_not_truncated():
    urls = extract_media_urls('<a href="/dl/archive.tar.gz">x</a>', BASE)
    assert "http://example.com/dl/archive.tar.gz" in urls


def test_srcset_yields_every_candidate():
    urls = extract_media_urls(
        '<img srcset="/a-480.jpg 480w, /a-1280.jpg 1280w" src="/a.jpg">', BASE)
    assert {"http://example.com/a-480.jpg", "http://example.com/a-1280.jpg"} <= set(urls)


def test_lazy_and_style_attributes():
    urls = extract_media_urls(
        '<img data-src="/lazy.jpg">'
        '<div style="background-image:url(\'/bg.jpg\')"></div>'
        '<div data-background="/bg2.png"></div>', BASE)
    assert {"http://example.com/lazy.jpg", "http://example.com/bg.jpg",
            "http://example.com/bg2.png"} <= set(urls)


def test_open_graph_twitter_and_schema():
    html = """<meta property="og:image" content="/og.jpg">
    <meta name="twitter:image" content="/tw.png">
    <script type="application/ld+json">
    {"@type":"VideoObject","contentUrl":"/clip.mp4","thumbnailUrl":"/thumb.jpg"}
    </script>"""
    urls = set(extract_media_urls(html, BASE))
    assert {"http://example.com/og.jpg", "http://example.com/tw.png",
            "http://example.com/clip.mp4", "http://example.com/thumb.jpg"} <= urls


def test_json_arrays_and_blobs_are_walked():
    html = """<script>
    var cfg = {"files":[{"src":"/a.jpg"},{"nested":{"u":"/b.png"}}]};
    </script>"""
    urls = set(extract_media_urls(html, BASE))
    assert {"http://example.com/a.jpg", "http://example.com/b.png"} <= urls


def test_noscript_and_template_content():
    html = ('<noscript><img src="/real.jpg"></noscript>'
            '<template><img data-original="/tpl.jpg"></template>')
    urls = set(extract_noscript_template_urls(html, BASE))
    assert {"http://example.com/real.jpg", "http://example.com/tpl.jpg"} <= urls


def test_video_audio_sources_and_poster():
    html = ('<video poster="/p.jpg" src="/v.mp4"></video>'
            '<video><source src="/alt.webm"></video>'
            '<audio src="/a.mp3"></audio>')
    urls = set(extract_media_urls(html, BASE))
    assert {"http://example.com/p.jpg", "http://example.com/v.mp4",
            "http://example.com/alt.webm", "http://example.com/a.mp3"} <= urls


def test_playlist_urls_are_found_anywhere():
    urls = set(extract_media_urls(
        '<script>player.load("https://cdn.example.com/hls/index.m3u8?tok=1")</script>',
        BASE))
    assert "https://cdn.example.com/hls/index.m3u8?tok=1" in urls


def test_extensionless_download_links_are_kept():
    html = ('<a href="https://example.com/download/file123">dl</a>'
            '<a href="https://files.example.com/get?file=doc.pdf">pdf</a>')
    urls = set(extract_media_urls(html, BASE))
    assert "https://example.com/download/file123" in urls
    assert "https://files.example.com/get?file=doc.pdf" in urls


def test_css_urls_and_imports():
    css = """@import url("nested.css");
    body { background: url('/img/bg.jpg'); }
    @font-face { font-family: X; src: url('/fonts/x.woff2'); }"""
    media, imports = extract_css_urls(css, "http://example.com/css/style.css")
    assert "http://example.com/img/bg.jpg" in media
    assert "http://example.com/fonts/x.woff2" in media
    assert imports == ["http://example.com/css/nested.css"]


def test_filters():
    urls = extract_media_urls('<img src="a.jpg"><img src="b.png"><img src="c.gif">',
                              BASE, include_filters=["*.jpg", "*.png"])
    assert len(urls) == 2

    urls = extract_media_urls('<img src="a.jpg"><img src="b.png">', BASE,
                              exclude_filters=["*.png"])
    assert len(urls) == 1 and urls[0].endswith("a.jpg")

    # The shared helper the engine also uses.
    assert apply_url_filters(["http://x/a.jpg", "http://x/b.mp4"],
                             ["*.jpg"], None) == ["http://x/a.jpg"]


def test_non_media_pages_are_ignored():
    assert extract_media_urls(
        '<a href="/about.html">About</a><a href="/style.css">CSS</a>', BASE) == []


def test_iframes_are_returned():
    urls = extract_iframe_urls('<iframe src="/embed/1"></iframe>'
                               '<iframe src="https://other.test/x"></iframe>', BASE)
    assert urls == ["http://example.com/embed/1", "https://other.test/x"]


def test_media_extensions_cover_the_documented_formats():
    expected = {".jpg", ".png", ".mp4", ".mkv", ".m3u8", ".mpd", ".mp3",
                ".flac", ".pdf", ".epub", ".zip", ".rar", ".7z", ".woff2"}
    assert expected <= set(MEDIA_EXTENSIONS)


# ── Pagination ──────────────────────────────────────────────────────────────


def test_rel_next_is_preferred():
    html = '<a href="/page/2" rel="next">Next</a><a href="/page/3">下一页</a>'
    assert find_next_page_url(html, "http://example.com/page/1") == \
        "http://example.com/page/2"


def test_chinese_pagination_is_understood():
    html = '<a href="/page/5">下一页</a>'
    assert find_next_page_url(html, "http://example.com/page/4") == \
        "http://example.com/page/5"


def test_pagination_never_goes_backwards():
    html = '<a href="/page/1">下一页</a>'
    assert find_next_page_url(html, "http://example.com/page/5") is None


def test_pagination_skips_visited_targets():
    html = '<a href="/page/2" rel="next">Next</a>'
    assert find_next_page_url(
        html, "http://example.com/page/1",
        visited={"http://example.com/page/2"}) is None


def test_class_based_pagination():
    html = '<a class="pagination-next" href="/list?p=3">»</a>'
    assert find_next_page_url(html, "http://example.com/list?p=2") == \
        "http://example.com/list?p=3"


def test_meta_refresh_detection():
    html = '<meta http-equiv="refresh" content="0; url=/moved/">'
    assert find_meta_refresh_url(html, BASE) == "http://example.com/moved/"


# ── Crawlable links ─────────────────────────────────────────────────────────


def test_page_links_respect_the_domain_and_skip_assets():
    html = ('<a href="/a">A</a><a href="https://other.test/b">B</a>'
            '<a href="/style.css">C</a><a href="#top">D</a>'
            '<a href="/login">E</a>')
    links = extract_page_links(html, "http://example.com/", same_domain=True)
    assert links == ["http://example.com/a"]


def test_page_links_allowed_paths_and_limit():
    html = "".join(f'<a href="/keep/{i}">x</a>' for i in range(10))
    html += '<a href="/skip/1">y</a>'
    links = extract_page_links(html, "http://example.com/", allowed_paths=["/keep/"],
                               max_links=3)
    assert len(links) == 3
    assert all("/keep/" in link for link in links)


# ── Encoding ────────────────────────────────────────────────────────────────


def test_charset_from_the_header_wins():
    assert detect_encoding({"content-type": "text/html; charset=UTF-8"}, b"") == "utf-8"


def test_legacy_chinese_charsets_map_to_gb18030():
    """gb2312 is a subset of gb18030, which decodes both correctly."""
    assert detect_encoding({"content-type": "text/html; charset=gb2312"}, b"") == "gb18030"
    assert detect_encoding({}, b'<meta charset="gbk">') == "gb18030"


def test_latin1_maps_to_cp1252_like_browsers_do():
    assert detect_encoding({"content-type": "text/html; charset=iso-8859-1"}, b"") == "cp1252"


def test_meta_charset_is_read_from_the_body():
    assert detect_encoding({}, b'<html><head><meta charset="Shift_JIS">') == "shift_jis"


def test_bom_detection():
    assert detect_encoding({}, b"\xef\xbb\xbfhello") == "utf-8-sig"
    assert detect_encoding({}, b"\xff\xfeh\x00i\x00") == "utf-16-le"


def test_decode_body_is_forgiving():
    text, encoding = decode_body(b'<meta charset="utf-8">caf\xc3\xa9')
    assert "café" in text
    assert encoding == "utf-8"

    # Invalid bytes for the declared encoding must not raise.
    text, _ = decode_body(b'<meta charset="utf-8">\xff\xfe bad', {})
    assert isinstance(text, str)


# ── Misc helpers ────────────────────────────────────────────────────────────


def test_canonicalize_strips_tracking_parameters():
    left = canonicalize_url("http://E.com/A/?utm_source=x&id=2&fbclid=y#frag")
    right = canonicalize_url("http://e.com/A?id=2")
    assert left == right


def test_inline_base64_images_are_decoded(tmp_path):
    import base64

    payload = base64.b64encode(b"\x89PNG" + b"x" * 2000).decode()
    html = f'<img src="data:image/png;base64,{payload}">'
    results = extract_inline_base64_images(html, str(tmp_path))
    assert len(results) == 1
    assert results[0]["format"] == "png"
    assert results[0]["size"] == 2004
    assert results[0]["saved_path"] and (tmp_path / results[0]["saved_path"].split("\\")[-1].split("/")[-1]).exists()


def test_content_type_to_extension():
    assert guess_extension_from_content_type("image/jpeg") == ".jpg"
    assert guess_extension_from_content_type("video/mp4; codecs=avc1") == ".mp4"
    assert guess_extension_from_content_type("application/dash+xml") == ".mpd"
    assert guess_extension_from_content_type("application/octet-stream") is None
