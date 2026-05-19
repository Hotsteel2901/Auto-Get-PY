import pytest
from scraper.decryptors.aes_dec import AESDecoder
from scraper.decryptors.xor_dec import XORDecoder
from scraper.decryptors.url_sign_dec import URLSignDecoder
from scraper.decryptors.custom_dec import CustomExprDecoder


@pytest.mark.asyncio
async def test_aes_can_handle_with_key():
    dec = AESDecoder()
    ctx = {"aes_key": "0123456789abcdef0123456789abcdef"}
    assert await dec.can_handle(b"anything", ctx) is True


@pytest.mark.asyncio
async def test_aes_can_handle_without_key():
    dec = AESDecoder()
    assert await dec.can_handle(b"anything", {}) is False


@pytest.mark.asyncio
async def test_aes_cbc_decrypt():
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad
    key = b"0123456789abcdef0123456789abcdef"
    iv = b"0123456789abcdef"
    cipher = AES.new(key, AES.MODE_CBC, iv)
    plaintext = b"Hello Secret World!!!"
    ciphertext = cipher.encrypt(pad(plaintext, 16))
    ctx = {"aes_key": key.hex(), "aes_iv": iv.hex(), "aes_mode": "cbc"}
    dec = AESDecoder()
    result = await dec.decrypt(ciphertext, ctx)
    assert result == plaintext


@pytest.mark.asyncio
async def test_xor_single_byte():
    dec = XORDecoder()
    ctx = {"xor_key": "55"}
    ciphertext = bytes(b ^ 0x55 for b in b"Hello")
    result = await dec.decrypt(ciphertext, ctx)
    assert result == b"Hello"


@pytest.mark.asyncio
async def test_url_sign_strip():
    dec = URLSignDecoder()
    content = b"http://example.com/file.jpg?sign=abc123&expires=99999&token=xyz"
    result = await dec.decrypt(content, {})
    assert b"sign=" not in result
    assert result == b"http://example.com/file.jpg"


@pytest.mark.asyncio
async def test_custom_expr():
    dec = CustomExprDecoder()
    ctx = {"custom_expr": "bytes(b ^ 0xFF for b in content)"}
    content = bytes(b ^ 0xFF for b in b"Hello")
    result = await dec.decrypt(content, ctx)
    assert result == b"Hello"
