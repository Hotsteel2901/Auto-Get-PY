import pytest
from scraper.extractor import extract_media_urls, MEDIA_EXTENSIONS


def test_extract_image_links():
    html = """
    <html><body>
    <img src="photo.jpg">
    <img src="/images/logo.png">
    <a href="document.pdf">PDF</a>
    <script>var x = "other.txt"</script>
    </body></html>
    """
    urls = extract_media_urls(html, "http://example.com/page/")
    exts = [u.split(".")[-1] for u in urls]
    assert "jpg" in exts
    assert "png" in exts
    assert "pdf" in exts


def test_extract_video_links():
    html = '<source src="movie.mp4"><a href="clip.avi">clip</a>'
    urls = extract_media_urls(html, "http://example.com")
    assert any("mp4" in u for u in urls)
    assert any("avi" in u for u in urls)


def test_extract_absolute_urls():
    html = '<img src="/images/photo.jpg"><img src="https://cdn.example.com/img.png">'
    urls = extract_media_urls(html, "http://example.com")
    assert "http://example.com/images/photo.jpg" in urls
    assert "https://cdn.example.com/img.png" in urls


def test_filter_include():
    html = '<img src="a.jpg"><img src="b.png"><img src="c.gif">'
    urls = extract_media_urls(html, "http://example.com", include_filters=["*.jpg", "*.png"])
    assert len(urls) == 2


def test_filter_exclude():
    html = '<img src="a.jpg"><img src="b.png">'
    urls = extract_media_urls(html, "http://example.com", exclude_filters=["*.png"])
    assert len(urls) == 1
    assert "b.png" not in urls[0]


def test_skip_non_media():
    html = '<a href="/about.html">About</a><a href="/style.css">CSS</a>'
    urls = extract_media_urls(html, "http://example.com")
    assert len(urls) == 0


def test_extract_direct_file_links():
    html = '''
    <html><body>
    <a href="https://example.com/download/file123">Download</a>
    <a href="https://cdn.example.com/media/video.mp4">Video</a>
    <a href="https://files.example.com/get?file=doc.pdf">PDF</a>
    </body></html>
    '''
    urls = extract_media_urls(html, "http://example.com")
    assert any("download" in u.lower() for u in urls)
    assert any(".mp4" in u for u in urls)
    assert any(".pdf" in u for u in urls)


def test_extract_generic_media_urls():
    html = '''
    <html><body>
    <a href="https://example.com/image.jpg">Image</a>
    <a href="https://example.com/audio.mp3">Audio</a>
    <a href="https://example.com/archive.zip">Archive</a>
    </body></html>
    '''
    urls = extract_media_urls(html, "http://example.com")
    assert any(".jpg" in u for u in urls)
    assert any(".mp3" in u for u in urls)
    assert any(".zip" in u for u in urls)
