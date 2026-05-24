import re
from scraper.decryptors.base import BaseDecryptor


class HexDecoder(BaseDecryptor):
    name = "hex"
    priority = 10

    async def can_handle(self, content: bytes, context: dict) -> bool:
        try:
            text = content.decode("ascii", errors="ignore").strip()
            return bool(re.fullmatch(r"([0-9a-fA-F]{2})+", text)) and len(text) >= 8
        except Exception:
            return False

    async def decrypt(self, content: bytes, context: dict) -> bytes:
        text = content.decode("ascii", errors="ignore").strip()
        return bytes.fromhex(text)
