from scraper.decryptors.base import BaseDecryptor


class XORDecoder(BaseDecryptor):
    name = "xor"
    priority = 30

    async def can_handle(self, content: bytes, context: dict) -> bool:
        return bool(context.get("xor_key"))

    async def decrypt(self, content: bytes, context: dict) -> bytes:
        key = bytes.fromhex(context["xor_key"])
        return bytes(content[i] ^ key[i % len(key)] for i in range(len(content)))
