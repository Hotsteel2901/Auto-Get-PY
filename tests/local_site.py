"""A local, self-contained test website used for end-to-end crawler tests.

Serves a deliberately awkward site that exercises every discovery path the
scraper claims to support:

* media in ``<img>``, ``srcset``, lazy ``data-src``, ``og:``, JSON-LD, JS strings
* pagination via ``rel=next`` and a Chinese "下一页" link
* an ``<iframe>`` whose content has its own media
* an external stylesheet with ``url()`` plus a nested ``@import``
* a ``<noscript>`` fallback holding the *real* image URL
* HTTP cookies that media requests depend on (hotlink protection)
* ``Content-Disposition`` filenames that differ from the URL path
* an HLS (``.m3u8``) stream in both master and variant form
* a flaky endpoint that fails twice before succeeding
* robots.txt, sitemap.xml and an RSS feed
"""

from __future__ import annotations

import asyncio
import re
from urllib.parse import urljoin

from aiohttp import web

# ── Fake binary payloads ────────────────────────────────────────────────────

JPEG = b"\xff\xd8\xff\xe0" + b"jpeg-payload-" * 40 + b"\xff\xd9"
PNG = b"\x89PNG\r\n\x1a\n" + b"png-payload-" * 60
PDF = b"%PDF-1.4\n" + b"pdf-body-" * 80 + b"\n%%EOF"
TS_SEGMENT = b"G" * 188 * 4  # one fake MPEG-TS packet set

FLAKY_HITS: dict[str, int] = {}

INDEX_HTML = """<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<title>Media Test Site</title>
<base href="/">
<link rel="stylesheet" href="style.css">
<link rel="alternate" type="application/rss+xml" href="/feed.xml">
<meta property="og:image" content="/img/og.jpg">
<meta name="twitter:image" content="/img/twitter.png">
<script type="application/ld+json">
{"@type":"VideoObject","contentUrl":"/vid/clip.mp4","thumbnailUrl":"/img/thumb.jpg"}
</script>
</head><body>
<h1>Gallery</h1>
<img src="/img/hero.jpg" alt="hero">
<img srcset="/img/small.jpg 480w, /img/large.jpg 1280w" src="/img/fallback.jpg">
<img data-src="/img/lazy.jpg">
<div style="background-image:url('/img/bg.jpg')"></div>
<video poster="/img/poster.jpg" src="/vid/clip.mp4"></video>
<video><source src="/vid/clip.webm" type="video/webm"></video>
<audio src="/audio/song.mp3"></audio>
<a href="/dl/report">Download the report</a>
<a href="/docs/manual.pdf">Manual</a>
<a href="?page=2" rel="next">Next</a>
<a href="/page/3">下一页</a>
<a href="/blog/post-1">A blog post</a>
<a href="/protected/secret.jpg">Members only</a>
<a href="/about">About</a>
<iframe src="/frag.html"></iframe>
<noscript><img src="/img/noscript-real.jpg"></noscript>
<template><img data-original="/img/template.jpg"></template>
<script>
  var player = {"hls": "/vid/stream/master.m3u8", "poster": "/img/js-poster.jpg"};
  fetch("/api/media");
</script>
</body></html>"""

PAGE2_HTML = """<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Gallery page 2</title></head><body>
<img src="/img/page2-a.jpg">
<img src="/img/page2-b.jpg">
<a href="/page/4">下一页</a>
</body></html>"""

PAGE3_HTML = """<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Chinese pagination page</title></head><body>
<img src="/img/cn-page.jpg">
</body></html>"""

BLOG_HTML = """<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Blog post</title></head><body>
<img src="/img/blog.jpg">
</body></html>"""

FRAG_HTML = """<!DOCTYPE html><html><head><meta charset="utf-8"></head><body>
<img src="/img/iframe-image.jpg">
<video src="/vid/iframe-video.mp4"></video>
</body></html>"""

STYLE_CSS = """@import url("nested.css");
body { background: url('/img/css-bg.jpg') no-repeat; }
@font-face { font-family: X; src: url('/fonts/body.woff2') format('woff2'); }
"""

NESTED_CSS = """@import "deeper.css";
.hero { background-image: url(/img/nested-bg.png); }
"""

DEEPER_CSS = """.deep { background-image: url("/img/deeper-bg.png"); }
"""

MASTER_M3U8 = """#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=800000,RESOLUTION=640x360
low/index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=2000000,RESOLUTION=1280x720
high/index.m3u8
"""

VARIANT_M3U8 = """#EXTM3U
#EXT-X-VERSION:3
#EXT-X-TARGETDURATION:4
#EXT-X-MEDIA-SEQUENCE:0
#EXTINF:4.0,
seg0.ts
#EXTINF:4.0,
seg1.ts
#EXTINF:4.0,
seg2.ts
#EXT-X-ENDLIST
"""

ROBOTS_TXT = """User-agent: *
Disallow: /private/
Sitemap: /sitemap.xml
Crawl-delay: 0
"""

SITEMAP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>/sm/a</loc></url>
  <url><loc>/sm/b</loc></url>
</urlset>
"""

FEED_XML = """<?xml version="1.0"?>
<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/">
<channel><title>Feed</title>
<item>
  <title>Ep 1</title>
  <link>/feed-post-1</link>
  <enclosure url="/audio/ep1.mp3" type="audio/mpeg"/>
  <media:content url="/audio/ep1-hi.mp3"/>
</item>
</channel></rss>
"""

SITEMAP_PAGE_A = """<html><head><meta charset="utf-8"></head><body>
<img src="/img/sitemap-a.jpg"></body></html>"""

SITEMAP_PAGE_B = """<html><head><meta charset="utf-8"></head><body>
<img src="/img/sitemap-b.jpg"></body></html>"""

FEED_POST_1 = """<html><head><meta charset="utf-8"></head><body>
<img src="/img/feed-post.jpg"></body></html>"""


def make_app() -> web.Application:
    app = web.Application()

    def html(body: str) -> web.Response:
        return web.Response(text=body, content_type="text/html", charset="utf-8")

    # ── Pages ───────────────────────────────────────────────────────────────

    async def index(request: web.Request) -> web.Response:
        # `?page=2` is the pagination target advertised by rel=next on page 1,
        # so the same route has to serve both.
        body = INDEX_HTML if not request.query.get("page") else PAGE2_HTML
        resp = html(body)
        # Hotlink protection: media under /protected/ needs this cookie.
        resp.set_cookie("session", "abc123", path="/")
        return resp

    async def page(request: web.Request) -> web.Response:
        n = request.match_info["n"]
        return html(PAGE2_HTML if n == "2" else PAGE3_HTML)

    async def blog(request: web.Request) -> web.Response:
        return html(BLOG_HTML)

    async def frag(request: web.Request) -> web.Response:
        return html(FRAG_HTML)

    async def sitemap_page(request: web.Request) -> web.Response:
        key = request.match_info["key"]
        return html(SITEMAP_PAGE_A if key == "a" else SITEMAP_PAGE_B)

    async def feed_post(request: web.Request) -> web.Response:
        return html(FEED_POST_1)

    async def query_page(request: web.Request) -> web.Response:
        return html(PAGE2_HTML)

    # ── Assets ──────────────────────────────────────────────────────────────

    async def img(request: web.Request) -> web.Response:
        name = request.match_info["name"]
        if name.endswith(".png"):
            return web.Response(body=PNG, content_type="image/png")
        return web.Response(body=JPEG, content_type="image/jpeg")

    async def media(request: web.Request) -> web.Response:
        path = request.match_info["path"]
        if path.endswith(".mp4"):
            return web.Response(body=b"\x00\x00\x00\x18ftypmp42" + JPEG, content_type="video/mp4")
        if path.endswith(".webm"):
            return web.Response(body=b"\x1a\x45\xdf\xa3" + JPEG, content_type="video/webm")
        if path.endswith(".mp3"):
            return web.Response(body=b"ID3" + JPEG, content_type="audio/mpeg")
        return web.Response(body=JPEG, content_type="application/octet-stream")

    async def css(request: web.Request) -> web.Response:
        name = request.match_info["name"]
        mapping = {"style.css": STYLE_CSS, "nested.css": NESTED_CSS, "deeper.css": DEEPER_CSS}
        return web.Response(text=mapping.get(name, "/* empty */"), content_type="text/css")

    async def font(request: web.Request) -> web.Response:
        return web.Response(body=b"wOFF" + JPEG, content_type="font/woff2")

    async def report(request: web.Request) -> web.Response:
        """No file extension in the URL, but a Content-Disposition filename."""
        return web.Response(
            body=PDF,
            content_type="application/pdf",
            headers={"Content-Disposition": 'attachment; filename="quarterly-report.pdf"'},
        )

    async def manual(request: web.Request) -> web.Response:
        return web.Response(body=PDF, content_type="application/pdf")

    # ── HLS ─────────────────────────────────────────────────────────────────

    async def m3u8_master(request: web.Request) -> web.Response:
        return web.Response(text=MASTER_M3U8, content_type="application/vnd.apple.mpegurl")

    async def m3u8_variant(request: web.Request) -> web.Response:
        return web.Response(text=VARIANT_M3U8, content_type="application/vnd.apple.mpegurl")

    async def ts_segment(request: web.Request) -> web.Response:
        return web.Response(body=TS_SEGMENT, content_type="video/mp2t")

    # ── Protection / flakiness ──────────────────────────────────────────────

    async def protected(request: web.Request) -> web.Response:
        """Only served when the session cookie from `/` is presented."""
        if request.cookies.get("session") != "abc123":
            raise web.HTTPForbidden(text="hotlink protection")
        return web.Response(body=JPEG, content_type="image/jpeg")

    async def needs_referer(request: web.Request) -> web.Response:
        """Only served when a Referer header is present."""
        if not request.headers.get("Referer"):
            raise web.HTTPForbidden(text="referer required")
        return web.Response(body=JPEG, content_type="image/jpeg")

    async def flaky(request: web.Request) -> web.Response:
        key = "flaky"
        FLAKY_HITS[key] = FLAKY_HITS.get(key, 0) + 1
        if FLAKY_HITS[key] < 3:
            raise web.HTTPServiceUnavailable(text="try again")
        return web.Response(body=JPEG, content_type="image/jpeg")

    async def always_429(request: web.Request) -> web.Response:
        raise web.HTTPTooManyRequests(text="slow down")

    async def not_found_media(request: web.Request) -> web.Response:
        raise web.HTTPNotFound(text="gone")

    async def slow(request: web.Request) -> web.Response:
        await asyncio.sleep(float(request.query.get("s", "1")))
        return web.Response(body=JPEG, content_type="image/jpeg")

    async def large(request: web.Request) -> web.Response:
        """~1.2 MB, used to exercise the max-file-size guard."""
        return web.Response(body=b"\xff\xd8\xff\xe0" + b"L" * (1200 * 1024),
                            content_type="image/jpeg")

    async def unicode_name(request: web.Request) -> web.Response:
        return web.Response(body=JPEG, content_type="image/jpeg")

    # ── Discovery files ─────────────────────────────────────────────────────

    async def robots(request: web.Request) -> web.Response:
        return web.Response(text=ROBOTS_TXT, content_type="text/plain")

    async def sitemap(request: web.Request) -> web.Response:
        return web.Response(text=SITEMAP_XML, content_type="application/xml")

    async def feed(request: web.Request) -> web.Response:
        return web.Response(text=FEED_XML, content_type="application/rss+xml")

    async def api_media(request: web.Request) -> web.Response:
        return web.json_response({"items": [{"url": "/img/api-item.jpg"}]})

    # ── Routes ──────────────────────────────────────────────────────────────

    app.router.add_get("/", index)
    app.router.add_get("/page/{n}", page)
    app.router.add_get("/blog/post-1", blog)
    app.router.add_get("/about", _about)
    app.router.add_get("/frag.html", frag)
    app.router.add_get("/sm/{key}", sitemap_page)
    app.router.add_get("/feed-post-1", feed_post)
    app.router.add_get("/search", query_page)

    app.router.add_get("/img/{name}", img)
    app.router.add_get("/vid/{path:.*}", media)
    app.router.add_get("/audio/{path:.*}", media)
    app.router.add_get("/css/{name}", css)
    app.router.add_get("/style.css", lambda r: web.Response(text=STYLE_CSS, content_type="text/css"))
    app.router.add_get("/nested.css", lambda r: web.Response(text=NESTED_CSS, content_type="text/css"))
    app.router.add_get("/deeper.css", lambda r: web.Response(text=DEEPER_CSS, content_type="text/css"))
    app.router.add_get("/fonts/{name}", font)
    app.router.add_get("/dl/report", report)
    app.router.add_get("/docs/manual.pdf", manual)

    app.router.add_get("/vid/stream/master.m3u8", m3u8_master)
    app.router.add_get("/vid/stream/{q}/index.m3u8", m3u8_variant)
    app.router.add_get("/vid/stream/{q}/{seg}", ts_segment)

    app.router.add_get("/protected/secret.jpg", protected)
    app.router.add_get("/hotlink/needs-referer.jpg", needs_referer)
    app.router.add_get("/flaky/retry.jpg", flaky)
    app.router.add_get("/ratelimited/always.jpg", always_429)
    app.router.add_get("/missing/gone.jpg", not_found_media)
    app.router.add_get("/slow/{name}", slow)
    app.router.add_get("/large/{name}", large)
    app.router.add_get("/unicode/{name}", unicode_name)

    app.router.add_get("/robots.txt", robots)
    app.router.add_get("/sitemap.xml", sitemap)
    app.router.add_get("/feed.xml", feed)
    app.router.add_get("/api/media", api_media)

    return app


async def _about(request: web.Request) -> web.Response:
    return web.Response(text="<html><body>about</body></html>", content_type="text/html")


class LocalSite:
    """Context manager that runs the test site on a free port."""

    def __init__(self) -> None:
        self._runner: web.AppRunner | None = None
        self.port: int = 0

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/"

    async def __aenter__(self) -> "LocalSite":
        FLAKY_HITS.clear()
        self._runner = web.AppRunner(make_app())
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", 0)
        await site.start()
        self.port = site._server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *exc) -> None:
        if self._runner:
            await self._runner.cleanup()


def absolute(base: str, path: str) -> str:
    return urljoin(base, path)


def normalize(url: str) -> str:
    """Strip a test-site origin so assertions can compare paths."""
    return re.sub(r"^http://127\.0\.0\.1:\d+", "", url)
