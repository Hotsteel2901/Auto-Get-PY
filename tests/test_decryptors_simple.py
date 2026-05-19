import pytest
from scraper.decryptors.base64_dec import Base64Decoder
from scraper.decryptors.hex_dec import HexDecoder
from scraper.decryptors.rot47_dec import Rot47Decoder
from scraper.decryptors import register, run_pipeline


@pytest.mark.asyncio
async def test_base64_can_handle():
    dec = Base64Decoder()
    assert await dec.can_handle(b"SGVsbG8gV29ybGQ=", {}) is True
    assert await dec.can_handle(b"\xff\xfe\x00\x01", {}) is False


@pytest.mark.asyncio
async def test_base64_decrypt():
    dec = Base64Decoder()
    result = await dec.decrypt(b"SGVsbG8gV29ybGQ=", {})
    assert result == b"Hello World"


@pytest.mark.asyncio
async def test_hex_can_handle():
    dec = HexDecoder()
    assert await dec.can_handle(b"48656c6c6f", {}) is True
    assert await dec.can_handle(b"hello world", {}) is False


@pytest.mark.asyncio
async def test_hex_decrypt():
    dec = HexDecoder()
    result = await dec.decrypt(b"48656c6c6f", {})
    assert result == b"Hello"


@pytest.mark.asyncio
async def test_rot47_roundtrip():
    dec = Rot47Decoder()
    original = b"Hello World 123!"
    encoded = await dec.decrypt(original, {})
    decoded = await dec.decrypt(encoded, {})
    assert decoded == original
    assert encoded != original


@pytest.mark.asyncio
async def test_pipeline_with_base64():
    from scraper.decryptors.base import _registry
    _registry.clear()
    register(Base64Decoder())
    register(HexDecoder())
    result = await run_pipeline(b"SGVsbG8gV29ybGQ=", ["base64", "hex"], {})
    assert result.data == b"Hello World"
